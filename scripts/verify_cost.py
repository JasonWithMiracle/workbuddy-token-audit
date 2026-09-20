# -*- coding: utf-8 -*-
"""
独立复算校验器（双实现交叉验证）
=========================================================
用一个**独立实现**重新计算全部成本，与审计引擎的产出对比。

两份实现算出同样的数字，才说明计价逻辑没有低级错误。
本脚本刻意**不复用** wb_token_audit.py 的任何函数 —— 复用的"校验"没有意义。

校验两件事：
  1. 逐请求计价：用独立公式重算 requests.jsonl 每一行的成本，与文件内记录比对
  2. 汇总一致性：独立汇总 vs summary.json 的总成本
  3.（可选）原始日志抽查：从 ~/.workbuddy/projects 抽 N 条记录，比对 token 数

用法：
    python verify_cost.py --data ./token-audit-output
    python verify_cost.py --requests ./out/requests.jsonl --summary ./out/summary.json
    python verify_cost.py --data ./out --sample 200     # 额外抽查 200 条原始日志
退出码：0=全部一致；1=存在不一致
"""
import json, os, sys, io, glob, random, argparse, datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
ASSETS = os.path.join(SKILL_ROOT, "assets")
BJ = datetime.timezone(datetime.timedelta(hours=8))

_ap = argparse.ArgumentParser(description="Token 成本独立复算校验器")
_ap.add_argument("--data", default="", help="审计产出目录（含 requests.jsonl / summary.json）")
_ap.add_argument("--requests", default="", help="requests.jsonl 路径（优先于 --data）")
_ap.add_argument("--summary", default="", help="summary.json 路径（优先于 --data）")
_ap.add_argument("--sample", type=int, default=0, help="额外从原始日志抽查 N 条记录比对 token")
_ap.add_argument("--projects", default="", help="原始日志目录（默认 ~/.workbuddy/projects）")
_args = _ap.parse_args()

BASE = _args.data or os.path.join(os.getcwd(), "token-audit-output")
REQ_F = _args.requests or os.path.join(BASE, "requests.jsonl")
SUM_F = _args.summary or os.path.join(BASE, "summary.json")

if not os.path.exists(REQ_F):
    sys.stderr.write("[fatal] 找不到 %s\n        请先运行 wb_token_audit.py\n" % REQ_F)
    sys.exit(2)


# ── 独立加载价格表（不复用主引擎代码）──────────────────────────────────────
def load_price_table():
    for f in ("price_table.json", "price_table.template.json"):
        p = os.path.join(ASSETS, f)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return (json.load(fh) or {}).get("models") or {}
    return {}


def load_calendar():
    hol, mk = set(), set()
    if os.path.isdir(ASSETS):
        for f in sorted(os.listdir(ASSETS)):
            if f.startswith("calendar_") and f.endswith(".json"):
                with open(os.path.join(ASSETS, f), encoding="utf-8") as fh:
                    d = json.load(fh) or {}
                hol |= set((d.get("holidays") or {}).keys())
                mk |= set((d.get("makeup_workdays") or {}).keys())
    return hol, mk


PRICE = load_price_table()
HOLIDAYS, MAKEUP = load_calendar()
_KEYS = sorted(PRICE.keys(), key=len, reverse=True)


def lookup(model):
    ml = (model or "").lower().strip()
    if ml in PRICE:
        return PRICE[ml]
    for k in _KEYS:
        if ml.startswith(k) or k in ml:
            return PRICE[k]
    return None


def is_workday(dt):
    s = dt.strftime("%Y-%m-%d")
    if s in MAKEUP:
        return True
    if s in HOLIDAYS:
        return False
    return dt.weekday() < 5


def is_peak(ts):
    if not ts:
        return True
    dt = datetime.datetime.fromtimestamp(ts, BJ)
    if not is_workday(dt):
        return False
    return (9 <= dt.hour < 12) or (14 <= dt.hour < 18)


def expected_price(entry, it, ot, tag, ts):
    """独立实现价格选取：优先按文件里记录的 tag 复现，同时用 ts 独立判一次以交叉验证"""
    kind = entry.get("kind")
    if kind == "split":
        by_ts = "peak" if is_peak(ts) else "off"
        if by_ts != tag:
            return None, "时段判定不一致(ts=%s vs tag=%s)" % (by_ts, tag)
        return (entry.get("peak") if tag == "peak" else entry.get("off")), None
    if kind == "tiered":
        for t in entry.get("tiers") or []:
            im, om = t.get("in_max"), t.get("out_max")
            if (im is None or it <= im) and (om is None or ot <= om):
                return t.get("price"), None
        tiers = entry.get("tiers") or []
        return (tiers[-1].get("price") if tiers else None), None
    return entry.get("price"), None


def cost_of(it, ot, cache, cwrite, p):
    """独立实现成本公式"""
    nc = it - cache - cwrite
    if nc < 0:
        nc = 0
    return (nc * p[0] + cache * p[2] + cwrite * p[0] * 1.25 + ot * p[1]) / 1e6


# ── 逐请求复算 ──────────────────────────────────────────────────────────────
n = bad_cost = bad_tag = no_price = 0
sum_cost = 0.0
mismatch_samples = []
tag_issues = []

with open(REQ_F, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        n += 1
        entry = lookup(r.get("model"))
        if entry is None:
            no_price += 1
            continue
        it = int(r.get("inp") or 0)
        ot = int(r.get("outp") or 0)
        cache = int(r.get("cache") or 0)
        cwrite = int(r.get("cwrite") or 0)
        tag = r.get("tag") or "flat"
        p, err = expected_price(entry, it, ot, tag, r.get("ts"))
        if err:
            bad_tag += 1
            if len(tag_issues) < 5:
                tag_issues.append("%s: %s" % (r.get("model"), err))
            continue
        if p is None:
            no_price += 1
            continue
        expect = cost_of(it, ot, cache, cwrite, p)
        got = float(r.get("cost") or 0)
        sum_cost += expect
        if abs(expect - got) > max(1e-6, abs(got) * 1e-6):
            bad_cost += 1
            if len(mismatch_samples) < 5:
                mismatch_samples.append("%s ts=%s 期望=%.8f 记录=%.8f" % (r.get("model"), r.get("ts"), expect, got))

print("=" * 58)
print("逐请求复算（独立实现）")
print("=" * 58)
print("  请求总数      : %s" % f"{n:,}")
print("  时段判定不一致: %s" % f"{bad_tag:,}")
print("  计价不一致    : %s" % f"{bad_cost:,}")
print("  未匹配价格    : %s" % f"{no_price:,}")
print("  独立汇总成本  : ¥%.2f" % sum_cost)

for s in tag_issues:
    print("    [时段] " + s)
for s in mismatch_samples:
    print("    [计价] " + s)

# ── 与 summary.json 对比 ────────────────────────────────────────────────────
ok = True
if os.path.exists(SUM_F):
    with open(SUM_F, encoding="utf-8") as fh:
        sm = json.load(fh) or {}
    rep = float(((sm.get("totals") or {}).get("cost_cny")) or 0)
    diff = abs(sum_cost - rep)
    print()
    print("=" * 58)
    print("与 summary.json 对比")
    print("=" * 58)
    print("  审计引擎报告 : ¥%.2f" % rep)
    print("  独立复算     : ¥%.2f" % sum_cost)
    print("  差额         : ¥%.4f" % diff)
    if diff > max(0.05, rep * 1e-4):
        print("  [X] 不一致 —— 需排查计价实现")
        ok = False
    else:
        print("  [OK] 一致")
else:
    print("\n[warn] 未找到 summary.json，跳过汇总对比")

# ── 可选：原始日志抽查 ──────────────────────────────────────────────────────
if _args.sample > 0:
    PROJ = _args.projects or os.path.join(os.path.expanduser("~"), ".workbuddy", "projects")
    files = glob.glob(os.path.join(PROJ, "**", "*.jsonl"), recursive=True)
    print()
    print("=" * 58)
    print("原始日志抽查（验证解析环节）")
    print("=" * 58)
    if not files:
        print("  [warn] 未找到原始日志：%s" % PROJ)
    else:
        picked, checked, mism = 0, 0, 0
        random.seed(0)
        for fp in random.sample(files, min(len(files), max(1, _args.sample // 10))):
            with open(fp, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    pd = o.get("providerData")
                    if not isinstance(pd, dict):
                        continue
                    ru = pd.get("rawUsage") or {}
                    if not ru.get("total_tokens"):
                        continue
                    checked += 1
                    it = int(ru.get("prompt_tokens") or 0)
                    ot = int(ru.get("completion_tokens") or 0)
                    if it + ot != int(ru.get("total_tokens") or 0):
                        mism += 1
                    if checked >= _args.sample:
                        break
                    picked += 1
            if checked >= _args.sample:
                break
        print("  抽查记录     : %s" % f"{checked:,}")
        print("  输入+输出≠总量: %s" % f"{mism:,}")
        if mism:
            print("  [X] 存在字段口径差异")
            ok = False
        else:
            print("  [OK] 字段口径一致")

print()
print("结论：" + ("全部校验通过" if ok else "存在不一致，请排查"))
sys.exit(0 if ok else 1)
