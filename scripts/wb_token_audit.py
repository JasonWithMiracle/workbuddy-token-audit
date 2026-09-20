# -*- coding: utf-8 -*-
"""
WorkBuddy Token 消耗审计引擎 v3 —— 外部价格表 + 每日首刷 + 请求级峰谷/分段
=========================================================
v3 相对 v2 的变更：
  1. 价格表外部化：从 price_table.json 读取，不再硬编码；支持三种计价形态
       flat   固定单价
       split  分时（按每条请求时间戳判高峰/空闲）
       tiered 分段（按每条请求的 input/output 长度判档，用于智谱 GLM）
  2. 每日首刷：当日首次调用时自动触发价格刷新（refresh_prices.py，混合模式：
     自动抓取 + 失败降级为人工清单）；当日后续调用直接复用。
     命令行 --force-refresh 可强制刷新，--no-refresh 可跳过检查。
  3. 日历外部化：calendar_YYYY.json 按年维护，按数据实际涉及年份自动加载；
     缺年份则告警（不静默兜底）。
  4. 双时长口径与峰谷统计沿用 v2。

数据源（全部本机、只读）：
  A) ~/.workbuddy/projects/**/*.jsonl → providerData.rawUsage（请求级真实 usage）
  B) ~/.workbuddy/workbuddy.db → sessions / session_usage

用法：
  python wb_token_audit.py                     # 正常执行（含当日首刷检查）
  python wb_token_audit.py --force-refresh      # 强制刷新价格表后执行
  python wb_token_audit.py --no-refresh         # 跳过刷新检查（离线）
"""
import json, os, glob, sys, io, csv, sqlite3, shutil, tempfile, collections, datetime, argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 目录约定：<skill_root>/scripts/ 本文件所在；<skill_root>/assets/ 存放价格表与日历
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
ASSETS = os.path.join(SKILL_ROOT, "assets")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

HOME = os.path.expanduser("~")
WB = os.path.join(HOME, ".workbuddy")
PROJ = os.path.join(WB, "projects")
DB = os.path.join(WB, "workbuddy.db")
PRICE_F = os.path.join(ASSETS, "price_table.json")
BJ = datetime.timezone(datetime.timedelta(hours=8))

_ap = argparse.ArgumentParser(description="WorkBuddy Token 消耗审计引擎")
_ap.add_argument("--force-refresh", action="store_true", help="强制刷新价格表")
_ap.add_argument("--no-refresh", action="store_true", help="跳过价格表新鲜度检查")
_ap.add_argument("--out", default="", help="产出目录（默认 <当前目录>/token-audit-output）")
_ap.add_argument("--projects", default="", help="WorkBuddy 日志目录（默认 ~/.workbuddy/projects）")
_ap.add_argument("--db", default="", help="workbuddy.db 路径（默认 ~/.workbuddy/workbuddy.db）")
_args = _ap.parse_args()

if _args.projects:
    PROJ = _args.projects
if _args.db:
    DB = _args.db
OUTDIR = _args.out or os.path.join(os.getcwd(), "token-audit-output")
os.makedirs(OUTDIR, exist_ok=True)


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ── 0. 价格表：当日首刷 ─────────────────────────────────────────────────────
print("[price] 检查价格表新鲜度…")
refresh_info = {}
if _args.no_refresh:
    try:
        import refresh_prices as rp
        rp.ensure_price_table()
    except Exception:
        pass
    pt = load_json(PRICE_F) or {}
    print(f"[price] 跳过刷新检查（离线模式）；当前核实日期 {pt.get('verified_at','(无)')}")
else:
    try:
        import refresh_prices as rp
        rp.ensure_price_table()
        st = rp.check()
        if (not st["is_fresh"]) or _args.force_refresh:
            why = "强制刷新" if _args.force_refresh else f"价格表核实日期 {st['verified_at'] or '(无)'} ≠ 今天 {st['today']}"
            print(f"[price] {why} → 执行当日首次刷新")
            refresh_info = rp.refresh(force=_args.force_refresh)
        else:
            print(f"[price] 价格表已于 {st['verified_at']} 刷新，当日复用")
            refresh_info = dict(skipped=True, verified_at=st["verified_at"])
    except Exception as e:
        print(f"[price] 刷新器异常（{type(e).__name__}: {e}），改用现有价格表继续")

PT = load_json(PRICE_F) or {}
if not PT.get("models"):
    print("[fatal] price_table.json 缺失或为空，无法计价。请先运行 refresh_prices.py")
    sys.exit(1)
PRICE_MODELS = PT["models"]
import pricing_core as pc
_PMODEL_KEYS = sorted(PRICE_MODELS.keys(), key=len, reverse=True)
PENDING_MANUAL = PT.get("pending_manual") or []
if PENDING_MANUAL:
    print(f"[price] 待人工核实 {len(PENDING_MANUAL)} 家：")
    for x in PENDING_MANUAL:
        print("   -", x)


def lookup(model):
    """统一委托 pricing_core（匹配优先级：精确 → 最长前缀 → 包含）"""
    return pc.lookup(PRICE_MODELS, model)


# ── 1. 扫描 jsonl，收集请求记录（先收集再计价，避免两遍 IO）────────────────
files = glob.glob(os.path.join(PROJ, "**", "*.jsonl"), recursive=True)
print(f"[scan] jsonl {len(files)}")

REQS = []
n_rec = n_usage = 0
for fp in files:
    parts = fp.replace("\\", "/").split("/")
    parent_sid = None
    if "subagents" in parts:
        i = parts.index("subagents")
        parent_sid = parts[i - 1] if i > 0 else None
    try:
        with open(fp, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                n_rec += 1
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                pd = o.get("providerData")
                if not isinstance(pd, dict):
                    continue
                ru = pd.get("rawUsage") or {}
                u = pd.get("usage") or {}
                tt = ru.get("total_tokens") or u.get("totalTokens")
                if not tt:
                    continue
                n_usage += 1
                sid = o.get("sessionId") or parent_sid
                if not sid:
                    continue
                it = int(ru.get("prompt_tokens") or u.get("inputTokens") or 0)
                ot = int(ru.get("completion_tokens") or u.get("outputTokens") or 0)
                ptd = ru.get("prompt_tokens_details") or {}
                ch = ru.get("prompt_cache_hit_tokens")
                if ch is None:
                    ch = ptd.get("cached_tokens") or 0
                ch = int(ch or 0)
                cw = int(ptd.get("cached_creation_tokens") or ptd.get("cache_write_tokens")
                         or ru.get("prompt_cache_write_tokens") or ru.get("cache_creation_input_tokens") or 0)
                m = pd.get("model") or pd.get("requestModelId") or pd.get("requestModelName") or "unknown"
                ts = None
                v = o.get("timestamp")
                if isinstance(v, (int, float)):
                    ts = v / 1000.0 if v > 1e12 else float(v)
                elif isinstance(v, str):
                    for f_ in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
                        try:
                            import calendar as _cal
                            ts = _cal.timegm(datetime.datetime.strptime(v.strip(), f_).timetuple())
                            break
                        except Exception:
                            pass
                REQS.append((sid, o.get("cwd"), m, it, ot, ch, cw, ts))
    except Exception:
        continue

print(f"[scan] 记录 {n_rec}  含 usage {n_usage}")

# ── 2. 日历：按数据涉及年份加载 ─────────────────────────────────────────────
years = set()
for r in REQS:
    if r[7]:
        years.add(datetime.datetime.fromtimestamp(r[7], BJ).year)
if not years:
    years = {datetime.datetime.now(BJ).year}
CALS = {}
missing_years = []
for y in sorted(years):
    p = os.path.join(ASSETS, f"calendar_{y}.json")
    if os.path.exists(p):
        CALS[y] = load_json(p) or {}
    else:
        missing_years.append(y)
print(f"[calendar] 数据涉及年份 {sorted(years)}；已加载 {sorted(CALS)}"
      + (f"；缺 {missing_years}（将按周一至周五兜底，请补录 calendar_YYYY.json）" if missing_years else ""))
for y in missing_years:
    print(f"[calendar][warn] 缺少 {y} 年节假日与调休表 —— 该年调休上班日/法定假日将无法识别")


IS_WORKDAY = pc.make_workday_fn(CALS)


def is_workday(d):
    return IS_WORKDAY(d)


def is_peak(ts):
    return pc.is_peak(ts, IS_WORKDAY)


# ── 3. 计价：统一委托 pricing_core（避免出现多套实现互相漂移）──────────────
def calc_cost(it, ot, ch, cw, price):
    return pc.calc_cost(it, ot, ch, cw, price)


def price_for(ent, it, ot, ts):
    """→ (price_list, tag)；tag ∈ flat / peak / off / tier"""
    return pc.resolve_price(ent, it, ot, ts, IS_WORKDAY)


# ── 4. 读数据库 ─────────────────────────────────────────────────────────────
tmp = os.path.join(tempfile.gettempdir(), "_wb_audit_db")
os.makedirs(tmp, exist_ok=True)
for suf in ("", "-wal", "-shm"):
    s = DB + suf
    if os.path.exists(s):
        try:
            shutil.copy2(s, os.path.join(tmp, "workbuddy.db" + suf))
        except Exception:
            pass
con = sqlite3.connect(os.path.join(tmp, "workbuddy.db"))
con.row_factory = sqlite3.Row
cur = con.cursor()
sessions, usage = {}, {}
try:
    for r in cur.execute("SELECT * FROM sessions"):
        d = dict(r)
        sessions[d["id"]] = d
except Exception as e:
    print("[warn] sessions:", e)
try:
    for r in cur.execute("SELECT * FROM session_usage"):
        d = dict(r)
        credit = None
        if d.get("credit_json"):
            try:
                credit = json.loads(d["credit_json"])
            except Exception:
                credit = None
        usage[d["session_id"]] = {"used": d.get("used"), "size": d.get("size"),
                                  "credit_total": round(sum(credit.values()), 4) if credit else None}
except Exception as e:
    print("[warn] session_usage:", e)
con.close()
print(f"[db] sessions={len(sessions)}  session_usage={len(usage)}")

# ── 5. 聚合 ─────────────────────────────────────────────────────────────────
sess = {}
model_stat = collections.Counter()
model_tag = collections.Counter()
unknown = collections.Counter()
tag_stat = collections.Counter()
REQ_OUT = []          # 逐请求明细，供看板与独立核算器复用（单一数据源）


def bucket(sid, cwd_hint):
    if sid not in sess:
        meta = sessions.get(sid) or {}
        sess[sid] = dict(
            sid=sid, title=meta.get("title") or meta.get("custom_title") or "",
            custom_title=meta.get("custom_title") or "",
            cwd=(meta.get("cwd") or cwd_hint or ""),
            is_auto=1 if meta.get("is_background_automation") else 0,
            status=meta.get("status") or "",
            models=collections.Counter(),
            it=0, ot=0, ch=0, cw=0, reqs=0,
            cost=0.0, cost_all_peak=0.0, cost_all_off=0.0,
            p_it=0, p_ot=0, p_ch=0, p_reqs=0, p_cost=0.0,
            o_it=0, o_ot=0, o_ch=0, o_reqs=0, o_cost=0.0,
            times=[], has_meta=sid in sessions, subagent_files=0,
            kinds=set(),
        )
    return sess[sid]


for sid, cwd, m, it, ot, ch, cw, ts in REQS:
    b = bucket(sid, cwd)
    ent = lookup(m)
    model_stat[m] += 1
    if ent is None:
        unknown[m] += 1
        continue
    price, tag = price_for(ent, it, ot, ts)
    if price is None:
        unknown[m] += 1
        continue
    c = calc_cost(it, ot, ch, cw, price)
    b["kinds"].add(ent.get("kind"))
    model_tag[f"{m}|{tag}"] += 1
    tag_stat[tag] += 1
    REQ_OUT.append(dict(ts=ts, model=m, inp=it, outp=ot, cache=ch, cwrite=cw,
                        tag=tag, cost=round(c, 8), sid=sid))

    if ent.get("kind") == "split":
        c_peak = calc_cost(it, ot, ch, cw, ent["peak"])
        c_off = calc_cost(it, ot, ch, cw, ent["off"])
        if tag == "peak":
            b["p_it"] += it; b["p_ot"] += ot; b["p_ch"] += ch
            b["p_reqs"] += 1; b["p_cost"] += c
        else:
            b["o_it"] += it; b["o_ot"] += ot; b["o_ch"] += ch
            b["o_reqs"] += 1; b["o_cost"] += c
    else:
        c_peak = c_off = c

    b["it"] += it; b["ot"] += ot; b["ch"] += ch; b["cw"] += cw
    b["reqs"] += 1
    b["cost"] += c
    b["cost_all_peak"] += c_peak
    b["cost_all_off"] += c_off
    b["models"][m] += 1
    if ts:
        b["times"].append(ts)

for fp in files:
    parts = fp.replace("\\", "/").split("/")
    if "subagents" in parts:
        i = parts.index("subagents")
        pid = parts[i - 1] if i > 0 else None
        if pid and pid in sess:
            sess[pid]["subagent_files"] += 1


def ws_name(cwd):
    if not cwd:
        return "(未知)"
    c = cwd.replace("\\", "/").rstrip("/")
    return c.split("/")[-1] or "(未知)"


def active_minutes(times, gap_min=30):
    if len(times) < 2:
        return 0.0
    t = sorted(times)
    total = 0.0
    for i in range(1, len(t)):
        dt = t[i] - t[i - 1]
        if dt <= gap_min * 60:
            total += dt
    return round(total / 60.0, 1)


sess_list = []
for sid, b in sess.items():
    u = usage.get(sid) or {}
    times = sorted(b["times"])
    span = round((times[-1] - times[0]) / 60.0, 1) if len(times) >= 2 else 0.0
    act = active_minutes(times)
    mixed = ("split" in b["kinds"]) and b["p_reqs"] > 0 and b["o_reqs"] > 0
    kinds = b["kinds"]
    sess_list.append(dict(
        sid=sid,
        title=(b["custom_title"] or b["title"] or "(无标题)")[:60],
        workspace=ws_name(b["cwd"]), cwd=b["cwd"],
        is_auto=b["is_auto"], status=b["status"],
        reqs=b["reqs"],
        input_tokens=b["it"], output_tokens=b["ot"], total_tokens=b["it"] + b["ot"],
        cache_hit_tokens=b["ch"],
        cache_hit_rate=round(b["ch"] / b["it"] * 100, 2) if b["it"] else 0.0,
        peak_reqs=b["p_reqs"], off_reqs=b["o_reqs"],
        peak_tokens=b["p_it"] + b["p_ot"], off_tokens=b["o_it"] + b["o_ot"],
        peak_cost_cny=round(b["p_cost"], 4), off_cost_cny=round(b["o_cost"], 4),
        cost_cny=round(b["cost"], 4),
        cost_avg_peak_cny=round((b["cost_all_peak"] + b["cost_all_off"]) / 2, 4),
        cost_all_peak_cny=round(b["cost_all_peak"], 4),
        cost_all_off_cny=round(b["cost_all_off"], 4),
        peak_ratio=round(b["p_reqs"] / b["reqs"] * 100, 1) if b["reqs"] else 0.0,
        cross_period=mixed, split_used=("split" in kinds),
        tiered_used=("tiered" in kinds),
        duration_span_min=span, duration_active_min=act,
        top_model=(b["models"].most_common(1)[0][0] if b["models"] else ""),
        hour_used=u.get("used"), ctx_size=u.get("size"), credit_total=u.get("credit_total"),
        started_at=(datetime.datetime.fromtimestamp(times[0], BJ).strftime("%Y-%m-%d %H:%M:%S") if times else ""),
        ended_at=(datetime.datetime.fromtimestamp(times[-1], BJ).strftime("%Y-%m-%d %H:%M:%S") if times else ""),
        subagent_files=b["subagent_files"], has_meta=b["has_meta"],
    ))
sess_list.sort(key=lambda r: r["total_tokens"], reverse=True)

ws_agg = {}
for r in sess_list:
    a = ws_agg.setdefault(r["workspace"], dict(
        workspace=r["workspace"], sessions=0, auto_sessions=0, reqs=0,
        input_tokens=0, output_tokens=0, total_tokens=0, cache_hit_tokens=0,
        peak_reqs=0, off_reqs=0, cost_cny=0.0, cost_all_peak_cny=0.0,
        cost_all_off_cny=0.0, last_active=""))
    a["sessions"] += 1
    a["auto_sessions"] += r["is_auto"]
    for k in ("reqs", "input_tokens", "output_tokens", "total_tokens",
              "cache_hit_tokens", "peak_reqs", "off_reqs"):
        a[k] += r[k]
    a["cost_cny"] += r["cost_cny"]
    a["cost_all_peak_cny"] += r["cost_all_peak_cny"]
    a["cost_all_off_cny"] += r["cost_all_off_cny"]
    if r["ended_at"] > a["last_active"]:
        a["last_active"] = r["ended_at"]
ws_rows = sorted(ws_agg.values(), key=lambda x: x["total_tokens"], reverse=True)
for a in ws_rows:
    for k in ("cost_cny", "cost_all_peak_cny", "cost_all_off_cny"):
        a[k] = round(a[k], 4)
    a["cache_hit_rate"] = round(a["cache_hit_tokens"] / a["input_tokens"] * 100, 2) if a["input_tokens"] else 0.0
    a["peak_ratio"] = round(a["peak_reqs"] / a["reqs"] * 100, 1) if a["reqs"] else 0.0

auto_rows = [r for r in sess_list if r["is_auto"]]
manual_rows = [r for r in sess_list if not r["is_auto"]]


def subtotal(rows):
    return dict(sessions=len(rows), reqs=sum(r["reqs"] for r in rows),
                input_tokens=sum(r["input_tokens"] for r in rows),
                output_tokens=sum(r["output_tokens"] for r in rows),
                total_tokens=sum(r["total_tokens"] for r in rows),
                cache_hit_tokens=sum(r["cache_hit_tokens"] for r in rows),
                peak_reqs=sum(r["peak_reqs"] for r in rows),
                off_reqs=sum(r["off_reqs"] for r in rows),
                cost_cny=round(sum(r["cost_cny"] for r in rows), 4))


day_agg = {}
for r in sess_list:
    if not r["started_at"]:
        continue
    a = day_agg.setdefault(r["started_at"][:10], dict(
        date=r["started_at"][:10], sessions=0, reqs=0, total_tokens=0,
        peak_reqs=0, off_reqs=0, peak_tokens=0, off_tokens=0, cost_cny=0.0))
    a["sessions"] += 1; a["reqs"] += r["reqs"]; a["total_tokens"] += r["total_tokens"]
    a["peak_reqs"] += r["peak_reqs"]; a["off_reqs"] += r["off_reqs"]
    a["peak_tokens"] += r["peak_tokens"]; a["off_tokens"] += r["off_tokens"]
    a["cost_cny"] += r["cost_cny"]
day_rows = sorted(day_agg.values(), key=lambda x: x["date"])
for a in day_rows:
    a["cost_cny"] = round(a["cost_cny"], 4)

model_rows = []
for m, cnt in model_stat.most_common():
    ent = lookup(m)
    kind = (ent or {}).get("kind")
    model_rows.append(dict(
        model=m, requests=cnt, matched_key=next((k for k in _PMODEL_KEYS if m.lower().startswith(k)), None),
        kind=kind,
        split=(kind == "split"), tiered=(kind == "tiered"),
        peak_price=((ent or {}).get("peak") if kind == "split" else
                    ((ent or {}).get("price") if kind == "flat" else
                     (((ent or {}).get("tiers") or [{}])[0].get("price")))),
        off_price=((ent or {}).get("off") if kind == "split" else
                   ((ent or {}).get("price") if kind == "flat" else
                    (((ent or {}).get("tiers") or [{}])[-1].get("price")))),
        peak_requests=model_tag.get(m + "|peak", 0),
        off_requests=model_tag.get(m + "|off", 0),
        source=(ent or {}).get("source"), url=(ent or {}).get("url"),
        verified_at=(ent or {}).get("verified_at"),
        note=(ent or {}).get("note"), promo=(ent or {}).get("promo"),
        unknown=(ent is None),
    ))

split_sessions = [r for r in sess_list if r["split_used"]]
p_reqs = sum(r["peak_reqs"] for r in sess_list)
o_reqs = sum(r["off_reqs"] for r in sess_list)
p_cost = sum(r["peak_cost_cny"] for r in sess_list)
o_cost = sum(r["off_cost_cny"] for r in sess_list)
cross = [r for r in sess_list if r["cross_period"]]
DUR = sorted([r["duration_span_min"] for r in sess_list if r["duration_span_min"] > 0])
ACT = sorted([r["duration_active_min"] for r in sess_list if r["duration_active_min"] > 0])


def med(a):
    return round(a[len(a) // 2], 1) if a else 0


summary = dict(
    generated_at=datetime.datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"),
    engine="v3",
    price_table=dict(
        verified_at=PT.get("verified_at"), verify_method=PT.get("verify_method"),
        pending_manual=PT.get("pending_manual") or [],
        refresh=refresh_info,
        priority=PT.get("priority"),
    ),
    calendar=dict(loaded=sorted(CALS), missing=missing_years),
    totals=dict(
        sessions=len(sess_list), requests=n_usage,
        input_tokens=sum(r["input_tokens"] for r in sess_list),
        output_tokens=sum(r["output_tokens"] for r in sess_list),
        total_tokens=sum(r["total_tokens"] for r in sess_list),
        cache_hit_tokens=sum(r["cache_hit_tokens"] for r in sess_list),
        cost_cny=round(sum(r["cost_cny"] for r in sess_list), 2),
        cost_all_peak_cny=round(sum(r["cost_all_peak_cny"] for r in sess_list), 2),
        cost_all_off_cny=round(sum(r["cost_all_off_cny"] for r in sess_list), 2),
        days=len(day_rows),
    ),
    peak_off=dict(split_sessions=len(split_sessions), peak_requests=p_reqs, off_requests=o_reqs,
                  peak_cost_cny=round(p_cost, 2), off_cost_cny=round(o_cost, 2),
                  cross_period_sessions=len(cross)),
    duration=dict(
        span_median_min=med(DUR), span_mean_min=round(sum(DUR) / len(DUR), 1) if DUR else 0,
        span_max_min=max(DUR) if DUR else 0,
        active_median_min=med(ACT), active_mean_min=round(sum(ACT) / len(ACT), 1) if ACT else 0,
        active_max_min=max(ACT) if ACT else 0,
        active_ratio=round(sum(ACT) / sum(DUR) * 100, 1) if DUR and sum(DUR) else 0),
    tag_stat=dict(tag_stat),
    auto=subtotal(auto_rows), manual=subtotal(manual_rows),
    unknown_models=dict(unknown),
)
t = summary["totals"]
t["cache_hit_rate"] = round(t["cache_hit_tokens"] / t["input_tokens"] * 100, 2) if t["input_tokens"] else 0.0
t["avg_cost_per_session"] = round(t["cost_cny"] / t["sessions"], 4) if t["sessions"] else 0


def dump_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# 逐请求明细：看板与独立核算器共用同一份，避免各脚本重复解析日志、重复计价
with open(os.path.join(OUTDIR, "requests.jsonl"), "w", encoding="utf-8") as f:
    for r in REQ_OUT:
        f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
print(f"[out] requests.jsonl: {len(REQ_OUT):,} 条逐请求明细")

dump_csv(os.path.join(OUTDIR, "sessions.csv"), sess_list,
         ["sid", "title", "workspace", "is_auto", "status", "reqs", "input_tokens", "output_tokens",
          "total_tokens", "cache_hit_tokens", "cache_hit_rate",
          "started_at", "ended_at", "duration_span_min", "duration_active_min",
          "peak_reqs", "off_reqs", "peak_ratio", "peak_tokens", "off_tokens",
          "cross_period", "split_used", "tiered_used",
          "peak_cost_cny", "off_cost_cny", "cost_cny", "cost_avg_peak_cny",
          "cost_all_peak_cny", "cost_all_off_cny",
          "top_model", "hour_used", "ctx_size", "credit_total", "subagent_files"])
dump_csv(os.path.join(OUTDIR, "workspaces.csv"), ws_rows,
         ["workspace", "sessions", "auto_sessions", "reqs", "input_tokens", "output_tokens",
          "total_tokens", "cache_hit_tokens", "cache_hit_rate",
          "peak_reqs", "off_reqs", "peak_ratio", "cost_cny",
          "cost_all_peak_cny", "cost_all_off_cny", "last_active"])
dump_csv(os.path.join(OUTDIR, "automations.csv"), auto_rows,
         ["sid", "title", "workspace", "reqs", "total_tokens", "started_at", "ended_at",
          "duration_span_min", "duration_active_min", "peak_reqs", "off_reqs", "cost_cny"])
dump_csv(os.path.join(OUTDIR, "daily.csv"), day_rows,
         ["date", "sessions", "reqs", "total_tokens", "peak_reqs", "off_reqs",
          "peak_tokens", "off_tokens", "cost_cny"])
dump_csv(os.path.join(OUTDIR, "models.csv"), model_rows,
         ["model", "requests", "matched_key", "kind", "split", "tiered",
          "peak_price", "off_price", "peak_requests", "off_requests",
          "source", "url", "verified_at", "unknown"])

data = dict(summary=summary, sessions=sess_list, workspaces=ws_rows,
            automations=auto_rows, daily=day_rows, models=model_rows)
with open(os.path.join(OUTDIR, "audit_data.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)
with open(os.path.join(OUTDIR, "summary.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1)

print("\n=== 总计 ===")
for kk, vv in summary["totals"].items():
    print(f"  {kk}: {vv:,}" if isinstance(vv, (int, float)) else f"  {kk}: {vv}")
print("\n=== 分时（峰 / 谷）===")
po = summary["peak_off"]
print(f"  参与分时会话 {po['split_sessions']}  跨时段 {po['cross_period_sessions']}")
print(f"  高峰请求 {po['peak_requests']:,}  空闲请求 {po['off_requests']:,}")
print(f"  实际 ¥{t['cost_cny']:,.2f} | 全高峰 ¥{t['cost_all_peak_cny']:,.2f} | 全空闲 ¥{t['cost_all_off_cny']:,.2f}")
print("\n=== 计价形态命中 ===")
for kk, vv in summary["tag_stat"].items():
    print(f"  {kk}: {vv:,}")
print("\n=== 时长 ===")
for kk, vv in summary["duration"].items():
    print(f"  {kk}: {vv}")
print("\n输出目录:", OUTDIR)
