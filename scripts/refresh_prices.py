# -*- coding: utf-8 -*-
"""
价格表刷新器（混合模式：自动抓取 + 失败降级）
=========================================================
职责：
  1. 读 price_sources.json（厂商官方定价页登记表）
  2. 逐厂商抓取主来源页，用"关键词锚点"验证页面可解析且结构未变
  3. 自动通过者 → 更新 price_table.json 的 verified_at（标记 auto）
     抓取失败或锚点缺失 → 输出待人工核实清单（标记 needs_manual），
     由 Agent 用官方页核实后写回（不静默跳过）

用法：
  python refresh_prices.py --check        # 只检查新鲜度，不抓取
  python refresh_prices.py --refresh      # 执行刷新（当日首次调用时自动触发）
  python refresh_prices.py --force        # 强制刷新（忽略当日已刷新标记）
  python refresh_prices.py --json         # 以 JSON 输出结果，便于程序消费
"""
import json, os, sys, io, ssl, shutil, argparse, datetime, urllib.request, urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 目录约定：<skill_root>/scripts/ 本文件所在；<skill_root>/assets/ 存放价格表与日历
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)
ASSETS = os.path.join(SKILL_ROOT, "assets")
os.makedirs(ASSETS, exist_ok=True)
SOURCES_F = os.path.join(ASSETS, "price_sources.json")
PRICE_F = os.path.join(ASSETS, "price_table.json")
TEMPLATE_F = os.path.join(ASSETS, "price_table.template.json")
LOG_F = os.path.join(ASSETS, "price_refresh_log.json")
BJ = datetime.timezone(datetime.timedelta(hours=8))


def ensure_price_table():
    """首次运行时从模板生成可写价格表（模板随仓库分发，实例文件不入库）"""
    if not os.path.exists(PRICE_F) and os.path.exists(TEMPLATE_F):
        shutil.copy2(TEMPLATE_F, PRICE_F)
        return True
    return False
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def today():
    return datetime.datetime.now(BJ).strftime("%Y-%m-%d")


def fetch(url, timeout=20, use_proxy=True):
    """抓取页面文本；use_proxy=False 时绕过系统代理（国内站点常需直连）"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    if use_proxy:
        opener = urllib.request.build_opener()
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "replace")


def fetch_any(url, timeout=20):
    """先走系统代理，失败则绕过代理直连（覆盖国内外混合来源）"""
    errs = []
    for use_proxy in (True, False):
        try:
            return fetch(url, timeout=timeout, use_proxy=use_proxy)
        except Exception as e:
            errs.append(f"{'proxy' if use_proxy else 'direct'}:{type(e).__name__}: {e}")
    raise RuntimeError(" | ".join(errs))


def strip_html(html):
    """粗略去标签，便于关键词检索"""
    import re
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", s)


def probe_vendor(vk, vc):
    """→ dict(status, label, detail, url, anchors_hit)"""
    srcs = vc.get("sources") or []
    must = vc.get("must_contain") or []
    anchors = vc.get("expect_anchors") or []
    last_err = ""
    for s in srcs:
        url = s.get("url")
        label = s.get("label") or url
        if not url:
            continue
        try:
            html = fetch_any(url)
            text = strip_html(html)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue
        low = text.lower()
        miss_must = [k for k in must if k.lower() not in low]
        if miss_must:
            last_err = f"{label} 缺少必要关键词 {miss_must}（可能页面改版或需登录）"
            continue
        hit = [k for k in anchors if k.lower() in low]
        ratio = len(hit) / len(anchors) if anchors else 1.0
        if ratio >= 0.6:
            return dict(status="auto_ok", label=label, url=url,
                        detail=f"锚点命中 {len(hit)}/{len(anchors)}", anchors_hit=hit)
        last_err = f"{label} 锚点命中不足 {len(hit)}/{len(anchors)}"
    return dict(status="needs_manual", label=(srcs[0].get("label") if srcs else ""),
                url=(srcs[0].get("url") if srcs else ""),
                detail=last_err or "无可抓取来源", anchors_hit=[])


def load(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def check():
    """只检查新鲜度"""
    pt = load(PRICE_F) or {}
    va = pt.get("verified_at", "")
    return dict(verified_at=va, is_fresh=(va == today()), today=today())


def refresh(force=False, quiet=False):
    ensure_price_table()
    pt = load(PRICE_F) or {}
    src = load(SOURCES_F) or {}
    log = load(LOG_F) or {}
    va = pt.get("verified_at", "")

    if va == today() and not force:
        res = dict(skipped=True, reason=f"价格表已于 {va} 刷新，当日复用", verified_at=va)
        if not quiet:
            print(f"[refresh] 跳过：价格表已于 {va} 刷新（当日复用）")
        return res

    vendors = src.get("vendors") or {}
    results = {}
    auto_ok, manual = [], []
    for vk, vc in vendors.items():
        r = probe_vendor(vk, vc)
        results[vk] = dict(name=vc.get("name", vk), **r)
        if r["status"] == "auto_ok":
            auto_ok.append((vk, vc))
        else:
            manual.append((vk, vc, r))

    # 按「厂商 → 其名下模型」归属表精确更新（避免模糊匹配误伤）
    models = pt.setdefault("models", {})
    stamp = today()
    vmods = {}
    for vk, vc in vendors.items():
        vmods[vk] = set(vc.get("models", []))
    auto_keys = {a[0] for a in auto_ok}
    for key, mv in models.items():
        for vk, ms in vmods.items():
            if key in ms:
                if vk in auto_keys:
                    mv["verified_at"] = stamp
                    mv["verify_method"] = "auto"
                break

    if not manual:
        pt["verified_at"] = stamp
        pt["verify_method"] = "auto"
    else:
        pt["verified_at"] = stamp
        pt["verify_method"] = "partial"
        pt["pending_manual"] = [f"{vc.get('name', vk)}（{r['detail']}）" for vk, vc, r in manual]

    save(PRICE_F, pt)
    log_entry = dict(
        at=datetime.datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"),
        forced=force, auto_ok=[a[0] for a in auto_ok],
        needs_manual=[dict(vendor=m[0], name=m[1].get("name"), detail=m[2]["detail"],
                           url=m[2]["url"]) for m in manual],
        results=results,
    )
    hist = log.get("history") or []
    hist.append(log_entry)
    save(LOG_F, dict(last=log_entry, history=hist[-30:]))

    if not quiet:
        print(f"[refresh] 自动确认 {len(auto_ok)} 家：" +
              (", ".join(vendors[k].get('name', k) for k, _ in auto_ok) or "无"))
        if manual:
            print(f"[refresh] 需人工核实 {len(manual)} 家（已写入 price_table.json 的 pending_manual）：")
            for vk, vc, r in manual:
                print(f"   - {vc.get('name', vk)}：{r['detail']}")
                print(f"     来源：{r['url']}")
    return dict(skipped=False, auto_ok=[a[0] for a in auto_ok],
                needs_manual=[m[0] for m in manual], verified_at=stamp)


def main():
    ap = argparse.ArgumentParser(description="价格表刷新器")
    ap.add_argument("--check", action="store_true", help="只检查新鲜度")
    ap.add_argument("--refresh", action="store_true", help="执行刷新")
    ap.add_argument("--force", action="store_true", help="强制刷新")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    a = ap.parse_args()

    if a.check:
        r = check()
    elif a.refresh or a.force:
        r = refresh(force=a.force)
    else:
        r = check()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        if a.check:
            print(f"价格表核实日期：{r['verified_at'] or '(无)'}　今天：{r['today']}　"
                  f"状态：{'新鲜' if r['is_fresh'] else '已过期，需刷新'}")


if __name__ == "__main__":
    main()
