# -*- coding: utf-8 -*-
"""
计价核心（纯函数，无副作用）
=========================================================
把价格表加载、峰谷判定、分段判档、成本公式抽出来，供引擎与测试共用。
本模块**不解析任何输入参数、不读写产出目录**，只做纯计算，便于单元测试。

价格表结构（assets/price_table.json）：
    {"models": {"<key>": {"kind": "flat|split|tiered", ...}}}
      flat   : {"price": [输入, 输出, 缓存命中]}
      split  : {"peak": [...], "off": [...]}
      tiered : {"tiers": [{"in_max": int|None, "out_max": int|None, "price": [...]}]}

日历结构（assets/calendar_YYYY.json）：
    {"holidays": {"YYYY-MM-DD": "名称"}, "makeup_workdays": {"YYYY-MM-DD": "说明"}}
"""
import os, json, datetime

BJ = datetime.timezone(datetime.timedelta(hours=8))
PEAK_WINDOWS = ((9, 12), (14, 18))     # 高峰窗口（小时，左闭右开）


# ── 加载 ────────────────────────────────────────────────────────────────────
def load_price_models(assets_dir):
    """读价格表；优先实例文件，其次模板。返回 models 字典。"""
    for fn in ("price_table.json", "price_table.template.json"):
        p = os.path.join(assets_dir, fn)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as fh:
                    return (json.load(fh) or {}).get("models") or {}
            except Exception:
                continue
    return {}


def load_calendars(assets_dir, years=None):
    """读日历。years 为 None 时加载目录下全部年份。返回 {year: cal_dict}"""
    out = {}
    if not os.path.isdir(assets_dir):
        return out
    for fn in sorted(os.listdir(assets_dir)):
        if not (fn.startswith("calendar_") and fn.endswith(".json")):
            continue
        try:
            y = int(fn[len("calendar_"):-len(".json")])
        except Exception:
            continue
        if years is not None and y not in years:
            continue
        try:
            with open(os.path.join(assets_dir, fn), encoding="utf-8") as fh:
                out[y] = json.load(fh) or {}
        except Exception:
            continue
    return out


# ── 模型匹配 ────────────────────────────────────────────────────────────────
def lookup(models, model):
    """按 精确 → 最长前缀 → 包含 三级匹配价格表条目；未命中返回 None"""
    if not models:
        return None
    ml = (model or "").lower().strip()
    if ml in models:
        return models[ml]
    for k in sorted(models.keys(), key=len, reverse=True):
        if ml.startswith(k.lower()):
            return models[k]
    for k in sorted(models.keys(), key=len, reverse=True):
        if k.lower() in ml:
            return models[k]
    return None


# ── 日历与峰谷 ──────────────────────────────────────────────────────────────
def make_workday_fn(calendars):
    """→ is_workday(datetime) 。判定顺序：调休上班日 → 法定放假日 → 周一至周五"""
    hol, mk = set(), set()
    for _y, cal in (calendars or {}).items():
        hol |= set((cal.get("holidays") or {}).keys())
        mk |= set((cal.get("makeup_workdays") or {}).keys())

    def is_workday(dt):
        s = dt.strftime("%Y-%m-%d")
        if s in mk:
            return True
        if s in hol:
            return False
        return dt.weekday() < 5

    return is_workday


def is_peak(ts, is_workday_fn):
    """北京时间高峰判定：工作日 09:00-12:00、14:00-18:00"""
    if not ts:
        return True
    dt = datetime.datetime.fromtimestamp(ts, BJ)
    if not is_workday_fn(dt):
        return False
    return any(a <= dt.hour < b for a, b in PEAK_WINDOWS)


# ── 判档与取价 ──────────────────────────────────────────────────────────────
def pick_tier(entry, inp, outp):
    """分段取价：返回第一个满足 in<=in_max 且 out<=out_max 的档；无匹配取最后一档"""
    tiers = entry.get("tiers") or []
    for t in tiers:
        im, om = t.get("in_max"), t.get("out_max")
        if (im is None or inp <= im) and (om is None or outp <= om):
            return t.get("price")
    return tiers[-1].get("price") if tiers else None


def resolve_price(entry, inp, outp, ts, is_workday_fn):
    """→ (price_list, tag)；tag ∈ flat / peak / off / tier"""
    kind = (entry or {}).get("kind")
    if kind == "flat":
        return entry.get("price"), "flat"
    if kind == "split":
        pk = is_peak(ts, is_workday_fn)
        return (entry.get("peak") if pk else entry.get("off")), ("peak" if pk else "off")
    if kind == "tiered":
        return pick_tier(entry, inp, outp), "tier"
    # 无 kind 字段时按固定价兜底
    return entry.get("price"), "flat"


# ── 成本公式 ────────────────────────────────────────────────────────────────
def calc_cost(inp, outp, cache, cwrite, price):
    """成本（元）。price = [输入价, 输出价, 缓存命中价]（元/百万 token）"""
    p_in, p_out, p_cache = price
    non_cached = max(0, inp - cache - cwrite)
    return (non_cached * p_in + cache * p_cache + cwrite * p_in * 1.25 + outp * p_out) / 1e6


def safe_div(a, b, default=0.0):
    """安全除法：分母为 0 或异常时返回默认值"""
    try:
        return (a / b) if b else default
    except Exception:
        return default
