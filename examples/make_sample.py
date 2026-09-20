# -*- coding: utf-8 -*-
"""
生成脱敏示例报告（examples/）
=========================================================
用途：开源仓库需要一份可预览的产出样例，但不能包含任何真实任务名与工作空间名。
本脚本用**虚构的**会话/工作空间/时间数据构造 audit_data.json，
再调用与真实流程相同的报告生成器产出示例，保证示例结构与真实产出一致。

用法：
    python examples/make_sample.py
产出：
    examples/sample_report/  （脱敏示例 HTML + MD + CSV）
"""
import json, os, sys, io, random, datetime, subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(SKILL_ROOT, "assets")
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
OUT = os.path.join(HERE, "sample_report")
BJ = datetime.timezone(datetime.timedelta(hours=8))
random.seed(20260920)

# ── 虚构数据（完全脱敏：任务名、工作空间名、ID 均为编造）──────────────────
WS = [
    ("backend-refactor", 9), ("data-pipeline", 7), ("docs-site", 5),
    ("mobile-app", 4), ("infra-tools", 3), ("research-notes", 2),
]
TASKS = [
    "重构用户认证模块", "批量处理 CSV 报表", "梳理数据同步流程",
    "编写部署文档", "排查接口超时问题", "汇总季度指标看板",
    "迁移旧版配置格式", "整理测试用例清单", "优化慢查询与索引",
    "搭建本地调试环境", "校对术语表译法", "归档历史构建产物",
    "设计任务看板字段", "统一日志格式规范", "拆分大型组件模块",
    "排查依赖版本冲突", "生成接口对照文档", "评估第三方服务选型",
    "清理废弃分支与标签", "补全单元测试覆盖", "校验数据迁移结果",
    "编写发布回滚预案", "整理会议决议要点", "核对埋点事件命名",
    "演练故障恢复流程", "聚合多渠道反馈", "重写解析器边界处理",
    "统一错误码定义", "梳理权限模型", "盘点未完成事项",
]
MODELS = [
    ("hy3", 0.70), ("deepseek-v4-flash", 0.12), ("hy3-x", 0.08),
    ("hy4-preview", 0.03), ("glm-5.3-flash", 0.04), ("glm-4.7", 0.02),
    ("deepseek-v4-pro", 0.01),
]


def load_price():
    for f in ("price_table.json", "price_table.template.json"):
        p = os.path.join(ASSETS, f)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return json.load(fh).get("models", {})
    return {}


PRICE = load_price()


def price_of(m):
    for k in sorted(PRICE, key=len, reverse=True):
        if m.lower().startswith(k.lower()) or k.lower() in m.lower():
            v = PRICE[k]
            if v.get("kind") == "split":
                return v["peak"], v["off"], "split"
            if v.get("kind") == "tiered":
                t = (v.get("tiers") or [{}])[-1].get("price") or [1, 4, 0.25]
                return t, t, "tiered"
            return v.get("price") or [1, 4, 0.25], v.get("price") or [1, 4, 0.25], "flat"
    return [1, 4, 0.25], [1, 4, 0.25], "flat"


def pick_model():
    r, acc = random.random(), 0.0
    for m, w in MODELS:
        acc += w
        if r <= acc:
            return m
    return MODELS[0][0]


sessions, ws_map, day_map = [], {}, {}
base = datetime.datetime(2026, 7, 27, 9, 0, tzinfo=BJ)

for i, (ws, n) in enumerate(WS):
    for j in range(n):
        title = TASKS[(i * 7 + j) % len(TASKS)]
        m = pick_model()
        peak_p, off_p, kind = price_of(m)
        reqs = random.randint(20, 900)
        is_auto = 1 if (i >= 4 and j % 3 == 0) else 0
        cross = (kind == "split" and random.random() < 0.25)
        if cross:
            peak_reqs = int(reqs * random.uniform(0.3, 0.7))
        elif kind == "split":
            peak_reqs = reqs if random.random() < 0.5 else 0
        else:
            peak_reqs = 0
        off_reqs = reqs - peak_reqs if kind == "split" else 0

        avg_in = random.randint(40000, 180000)
        cache_rate = random.uniform(0.90, 0.995)
        it = avg_in * reqs
        ch = int(it * cache_rate)
        ot = reqs * random.randint(60, 700)

        def cost(p):
            nc = max(0, it - ch)
            return (nc * p[0] + ch * p[2] + ot * p[1]) / 1e6

        c_peak, c_off = cost(peak_p), cost(off_p)
        mix = (peak_reqs / reqs) if reqs else 0
        actual = c_peak * mix + c_off * (1 - mix) if kind == "split" else c_peak

        start = base + datetime.timedelta(days=random.randint(0, 54), hours=random.randint(0, 14))
        span = random.choice([6, 12, 25, 48, 90, 180, 400])
        end = start + datetime.timedelta(minutes=span)
        active = round(span * random.uniform(0.15, 0.9), 1)

        sid = f"sample-{i:02d}{j:02d}"
        sessions.append(dict(
            sid=sid, title=title, workspace=ws, is_auto=is_auto, status="completed",
            reqs=reqs, input_tokens=it, output_tokens=ot, total_tokens=it + ot,
            cache_hit_tokens=ch, cache_hit_rate=round(ch / it * 100, 2),
            peak_reqs=peak_reqs, off_reqs=off_reqs,
            peak_tokens=int(it * mix) if kind == "split" else 0,
            off_tokens=int(it * (1 - mix)) if kind == "split" else 0,
            peak_cost_cny=round(c_peak, 4), off_cost_cny=round(c_off, 4),
            cost_cny=round(actual, 4),
            cost_avg_peak_cny=round((c_peak + c_off) / 2, 4),
            cost_all_peak_cny=round(c_peak, 4), cost_all_off_cny=round(c_off, 4),
            peak_ratio=round(mix * 100, 1), cross_period=cross,
            split_used=(kind == "split"), tiered_used=(kind == "tiered"),
            duration_span_min=span, duration_active_min=active,
            top_model=m, hour_used=random.randint(20000, 190000), ctx_size=192000,
            credit_total=None,
            started_at=start.strftime("%Y-%m-%d %H:%M:%S"),
            ended_at=end.strftime("%Y-%m-%d %H:%M:%S"),
            subagent_files=random.randint(0, 4), has_meta=True,
        ))

sessions.sort(key=lambda r: r["total_tokens"], reverse=True)


def sub(rows, key):
    return sum(r[key] for r in rows)


for r in sessions:
    a = ws_map.setdefault(r["workspace"], dict(
        workspace=r["workspace"], sessions=0, auto_sessions=0, reqs=0, input_tokens=0,
        output_tokens=0, total_tokens=0, cache_hit_tokens=0, peak_reqs=0, off_reqs=0,
        cost_cny=0.0, cost_all_peak_cny=0.0, cost_all_off_cny=0.0, last_active=""))
    a["sessions"] += 1; a["auto_sessions"] += r["is_auto"]
    for k in ("reqs", "input_tokens", "output_tokens", "total_tokens",
              "cache_hit_tokens", "peak_reqs", "off_reqs"):
        a[k] += r[k]
    for k in ("cost_cny", "cost_all_peak_cny", "cost_all_off_cny"):
        a[k] += r[k]
    if r["ended_at"] > a["last_active"]:
        a["last_active"] = r["ended_at"]
ws_rows = sorted(ws_map.values(), key=lambda x: x["total_tokens"], reverse=True)
for a in ws_rows:
    for k in ("cost_cny", "cost_all_peak_cny", "cost_all_off_cny"):
        a[k] = round(a[k], 4)
    a["cache_hit_rate"] = round(a["cache_hit_tokens"] / a["input_tokens"] * 100, 2) if a["input_tokens"] else 0
    a["peak_ratio"] = round(a["peak_reqs"] / a["reqs"] * 100, 1) if a["reqs"] else 0

for r in sessions:
    d = r["started_at"][:10]
    a = day_map.setdefault(d, dict(date=d, sessions=0, reqs=0, total_tokens=0, peak_reqs=0,
                                   off_reqs=0, peak_tokens=0, off_tokens=0, cost_cny=0.0))
    a["sessions"] += 1
    for k in ("reqs", "total_tokens", "peak_reqs", "off_reqs", "peak_tokens", "off_tokens", "cost_cny"):
        a[k] += r[k]
day_rows = sorted(day_map.values(), key=lambda x: x["date"])
for a in day_rows:
    a["cost_cny"] = round(a["cost_cny"], 4)

auto_rows = [r for r in sessions if r["is_auto"]]
manual_rows = [r for r in sessions if not r["is_auto"]]
model_rows = []
for m, _w in MODELS:
    rr = [r for r in sessions if r["top_model"] == m]
    if not rr:
        continue
    pk, of, kind = price_of(m)
    model_rows.append(dict(
        model=m, requests=sum(r["reqs"] for r in rr), matched_key=m, kind=kind,
        split=(kind == "split"), tiered=(kind == "tiered"), peak_price=pk, off_price=of,
        peak_requests=sum(r["peak_reqs"] for r in rr), off_requests=sum(r["off_reqs"] for r in rr),
        source="(示例数据)", url="", verified_at="2026-09-20",
        note=None, promo=None, unknown=False))

tot_in, tot_out = sub(sessions, "input_tokens"), sub(sessions, "output_tokens")
tot_ch = sub(sessions, "cache_hit_tokens")
tot_cost = round(sub(sessions, "cost_cny"), 2)
tot_peak = round(sub(sessions, "cost_all_peak_cny"), 2)
tot_off = round(sub(sessions, "cost_all_off_cny"), 2)
DUR = sorted(r["duration_span_min"] for r in sessions if r["duration_span_min"] > 0)
ACT = sorted(r["duration_active_min"] for r in sessions if r["duration_active_min"] > 0)


def med(a):
    return round(a[len(a) // 2], 1) if a else 0


ts = {"flat": 0, "peak": 0, "off": 0, "tier": 0}
for r in sessions:
    if r["tiered_used"]:
        ts["tier"] += r["reqs"]
    elif r["split_used"]:
        ts["peak"] += r["peak_reqs"]; ts["off"] += r["off_reqs"]
    else:
        ts["flat"] += r["reqs"]

summary = dict(
    generated_at=datetime.datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"),
    engine="sample",
    price_table=dict(verified_at="2026-09-20", verify_method="auto",
                     pending_manual=[], priority="模型原厂价优先",
                     refresh=dict(skipped=True, verified_at="2026-09-20", auto_ok=[])),
    calendar=dict(loaded=[2026], missing=[]),
    totals=dict(sessions=len(sessions), requests=sum(r["reqs"] for r in sessions),
                input_tokens=tot_in, output_tokens=tot_out, total_tokens=tot_in + tot_out,
                cache_hit_tokens=tot_ch,
                cache_hit_rate=round(tot_ch / tot_in * 100, 2),
                cost_cny=tot_cost, cost_all_peak_cny=tot_peak, cost_all_off_cny=tot_off,
                days=len(day_rows), avg_cost_per_session=round(tot_cost / len(sessions), 4)),
    peak_off=dict(split_sessions=len([r for r in sessions if r["split_used"]]),
                  peak_requests=sub(sessions, "peak_reqs"), off_requests=sub(sessions, "off_reqs"),
                  peak_cost_cny=round(sub(sessions, "peak_cost_cny"), 2),
                  off_cost_cny=round(sub(sessions, "off_cost_cny"), 2),
                  cross_period_sessions=len([r for r in sessions if r["cross_period"]])),
    duration=dict(span_median_min=med(DUR), span_mean_min=round(sum(DUR) / len(DUR), 1) if DUR else 0,
                  span_max_min=max(DUR) if DUR else 0,
                  active_median_min=med(ACT),
                  active_mean_min=round(sum(ACT) / len(ACT), 1) if ACT else 0,
                  active_max_min=max(ACT) if ACT else 0,
                  active_ratio=round(sum(ACT) / sum(DUR) * 100, 1) if DUR and sum(DUR) else 0),
    tag_stat=ts,
    auto=dict(sessions=len(auto_rows), reqs=sub(auto_rows, "reqs"),
              input_tokens=sub(auto_rows, "input_tokens"), output_tokens=sub(auto_rows, "output_tokens"),
              total_tokens=sub(auto_rows, "total_tokens"), cache_hit_tokens=sub(auto_rows, "cache_hit_tokens"),
              peak_reqs=sub(auto_rows, "peak_reqs"), off_reqs=sub(auto_rows, "off_reqs"),
              cost_cny=round(sub(auto_rows, "cost_cny"), 4)),
    manual=dict(sessions=len(manual_rows), reqs=sub(manual_rows, "reqs"),
                input_tokens=sub(manual_rows, "input_tokens"), output_tokens=sub(manual_rows, "output_tokens"),
                total_tokens=sub(manual_rows, "total_tokens"), cache_hit_tokens=sub(manual_rows, "cache_hit_tokens"),
                peak_reqs=sub(manual_rows, "peak_reqs"), off_reqs=sub(manual_rows, "off_reqs"),
                cost_cny=round(sub(manual_rows, "cost_cny"), 4)),
    unknown_models={},
)

os.makedirs(OUT, exist_ok=True)
data = dict(summary=summary, sessions=sessions, workspaces=ws_rows,
            automations=auto_rows, daily=day_rows, models=model_rows)
DATA_F = os.path.join(OUT, "audit_data.json")
with open(DATA_F, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)

print(f"[sample] 已生成脱敏数据：{len(sessions)} 个虚构会话 / {len(ws_rows)} 个工作空间")
print(f"[sample] 数据文件：{DATA_F}")

# 调用与真实流程相同的报告生成器
PY = sys.executable
for script in ("gen_report.py", "gen_markdown.py"):
    p = os.path.join(SCRIPTS, script)
    if os.path.exists(p):
        r = subprocess.run([PY, p, "--data", DATA_F, "--out", OUT],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(f"[sample] {script}: {(r.stdout or r.stderr or '').strip()[:160]}")

# 同时导出示例 CSV，便于读者看到数据结构
import csv


def dump(name, rows, cols):
    with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


dump("sessions.csv", sessions,
     ["sid", "title", "workspace", "is_auto", "reqs", "input_tokens", "output_tokens", "total_tokens",
      "cache_hit_tokens", "cache_hit_rate", "started_at", "ended_at", "duration_span_min",
      "duration_active_min", "peak_reqs", "off_reqs", "peak_ratio", "cost_cny"])
dump("workspaces.csv", ws_rows,
     ["workspace", "sessions", "reqs", "total_tokens", "cache_hit_rate", "peak_reqs", "off_reqs", "cost_cny"])
print(f"[sample] 完成，产出目录：{OUT}")
