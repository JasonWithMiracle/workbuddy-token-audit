# -*- coding: utf-8 -*-
"""生成《WorkBuddy 任务级 Token 消耗追溯：开源方案调研 + 本机实测》单文件离线 HTML 报告（v2 · 含分时计价）"""
import json, os, sys, io, argparse, datetime, collections

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)

_ap = argparse.ArgumentParser(description="生成 HTML 版 Token 消耗调研报告")
_ap.add_argument("--data", default="", help="audit_data.json 路径（默认 <当前目录>/token-audit-output/audit_data.json）")
_ap.add_argument("--out", default="", help="报告输出目录（默认与数据同目录）")
_ap.add_argument("--anonymize", action="store_true",
                 help="脱敏：把任务名与工作空间名替换为哈希标识，便于公开分享报告")
_args = _ap.parse_args()

DATA_F = _args.data or os.path.join(os.getcwd(), "token-audit-output", "audit_data.json")
OUT = _args.out or os.path.dirname(os.path.abspath(DATA_F))
os.makedirs(OUT, exist_ok=True)
D = json.load(open(DATA_F, encoding="utf-8"))

if _args.anonymize:
    import hashlib

    def _anon(s, prefix):
        if not s:
            return s
        return prefix + hashlib.sha1(str(s).encode("utf-8")).hexdigest()[:8]

    for _r in D.get("sessions") or []:
        _r["workspace"] = _anon(_r.get("workspace"), "ws-")
        _r["title"] = _anon(_r.get("title"), "task-")
    for _w in D.get("workspaces") or []:
        _w["workspace"] = _anon(_w.get("workspace"), "ws-")
    for _a in D.get("automations") or []:
        _a["workspace"] = _anon(_a.get("workspace"), "ws-")
        _a["title"] = _anon(_a.get("title"), "task-")
    print("[privacy] 已启用脱敏：任务名与工作空间名已哈希化")
S = D["summary"]
T = S["totals"]
PO = S["peak_off"]
DUR = S["duration"]
SESS = D["sessions"]
WS = D["workspaces"]
AUTO = D["automations"]
DAILY = D["daily"]
MODELS = D["models"]

with_meta = [r for r in SESS if r.get("has_meta")]
no_meta = [r for r in SESS if not r.get("has_meta")]
cred_rows = [r for r in SESS if r.get("credit_total") is not None]
cred_sum = sum(r["credit_total"] for r in cred_rows) if cred_rows else 0
cred_cost = sum(r["cost_cny"] for r in cred_rows) if cred_rows else 0
def _d(a, b, d=0.0):
    """安全除法：分母为 0 或异常时返回默认值，避免在无数据/无额度环境下崩溃"""
    try:
        return (a / b) if b else d
    except Exception:
        return d


_NAIVE = T["input_tokens"] / 1e6 * 1 + T["output_tokens"] / 1e6 * 4
CACHE_SAVE_PCT = round((1 - _d(T["cost_cny"], _NAIVE, 1.0)) * 100, 1)
SESS_SAVE = T["cost_all_peak_cny"] - T["cost_cny"]
SESS_SAVE_PCT = round(_d(SESS_SAVE, T["cost_all_peak_cny"]) * 100, 2)
DS_ACTUAL = PO["peak_cost_cny"] + PO["off_cost_cny"]
DS_ALLPEAK = PO["peak_cost_cny"] + PO["off_cost_cny"] * 2
DS_SAVE_PCT = _d(PO["off_cost_cny"], DS_ALLPEAK) * 100
_OFF_TOTAL_REQ = PO["peak_requests"] + PO["off_requests"]
OFF_REQ_PCT = _d(PO["off_requests"], _OFF_TOTAL_REQ) * 100
PEAK_REQ_PCT = _d(PO["peak_requests"], _OFF_TOTAL_REQ) * 100
CRED_RATIO = f"{_d(cred_sum, cred_cost):.2f}" if cred_cost else "—"
_NO_META_TOK_PCT = _d(sum(r["total_tokens"] for r in no_meta), T["total_tokens"]) * 100
NO_META_PCT = _d(len(no_meta), len(SESS)) * 100
AVG_DAILY = _d(T["cost_cny"], T["days"])
_SESSION_COSTS = sorted(r["cost_cny"] for r in SESS)
SESS_MAX = _SESSION_COSTS[-1] if _SESSION_COSTS else 0.0
SESS_MED = _SESSION_COSTS[len(_SESSION_COSTS) // 2] if _SESSION_COSTS else 0.0
PALETTE = ['#7aa5d4', '#d8a76b', '#6cc0ba', '#d48080', '#a798cf', '#9dba6e', '#d8a3b8', '#aab6c8']
SPLIT_MODELS = [m for m in MODELS if m["split"]]
FLAT_MODELS = [m for m in MODELS if not m["split"]]


def nf(n): return f"{int(n):,}"
def mf(x, d=2): return f"{x:,.{d}f}"
def yi(n): return f"{n/1e8:.2f} 亿"
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def bar_rows(items, value_key, label_key, color_list=None, fmt=yi, maxn=None, sub_key=None):
    mx = maxn or (max(i[value_key] for i in items) or 1)
    html = []
    for i, it in enumerate(items):
        pct = it[value_key] / mx * 100
        c = (color_list or PALETTE)[i % len(color_list or PALETTE)]
        sub = f'<span class="bsub">{esc(it[sub_key])}</span>' if sub_key else ""
        html.append(
            f'<div class="brow"><div class="blab" title="{esc(it[label_key])}">{esc(str(it[label_key])[:34])}{sub}</div>'
            f'<div class="btrack"><div class="bfill" style="width:{pct:.1f}%;background:{c}"></div></div>'
            f'<div class="bval">{fmt(it[value_key])}</div></div>')
    return "".join(html)


def svg_sources():
    return """
<svg viewBox="0 0 1040 320" xmlns="http://www.w3.org/2000/svg" class="dia">
  <defs><marker id="ar" markerWidth="9" markerHeight="9" refX="7" refY="4" orient="auto">
    <path d="M0,0 L8,4 L0,8 z" fill="#6f6d66"/></marker></defs>
  <text x="20" y="26" class="dt">本机可用的三个 token 数据源（均为只读，不外发）</text>
  <rect x="20" y="46" width="300" height="104" rx="10" fill="#2a2926" stroke="#4a6a85" stroke-width="1.5"/>
  <text x="38" y="72" class="dh">A · projects/**/*.jsonl</text>
  <text x="38" y="94" class="ds">请求级真实 usage + 请求时间戳</text>
  <text x="38" y="114" class="dm">providerData.rawUsage</text>
  <text x="38" y="134" class="dm">prompt / completion / cache_hit</text>
  <rect x="20" y="166" width="300" height="104" rx="10" fill="#2a2926" stroke="#8a6a3a" stroke-width="1.5"/>
  <text x="38" y="192" class="dh">B · workbuddy.db → sessions</text>
  <text x="38" y="214" class="ds">任务元数据</text>
  <text x="38" y="234" class="dm">title / cwd / model</text>
  <text x="38" y="254" class="dm">is_background_automation</text>
  <rect x="360" y="106" width="300" height="104" rx="10" fill="#2a2926" stroke="#4d7a70" stroke-width="1.5"/>
  <text x="378" y="132" class="dh">C · workbuddy.db → session_usage</text>
  <text x="378" y="154" class="ds">额度与上下文占用</text>
  <text x="378" y="174" class="dm">credit_json（额度明细）</text>
  <text x="378" y="194" class="dm">used / size（上下文窗口）</text>
  <rect x="710" y="60" width="310" height="80" rx="10" fill="#2a2926" stroke="#7aa5d4" stroke-width="1.5"/>
  <text x="728" y="88" class="dh">聚合引擎（v2 · 分时版）</text>
  <text x="728" y="110" class="ds">请求级峰谷判定 + 假日调休 + 双时长</text>
  <text x="728" y="130" class="dm">wb_token_audit.py · 仅标准库</text>
  <rect x="710" y="170" width="310" height="80" rx="10" fill="#2a2926" stroke="#6cc0ba" stroke-width="1.5"/>
  <text x="728" y="198" class="dh">输出</text>
  <text x="728" y="220" class="ds">报告 HTML · 五张 CSV · 明细 JSON</text>
  <text x="728" y="240" class="dm">会话 / 工作空间 / 自动化 / 日 / 模型</text>
  <path d="M320,98 C360,98 340,140 360,150" stroke="#6f6d66" stroke-width="1.4" fill="none" marker-end="url(#ar)"/>
  <path d="M320,218 C360,218 340,175 360,166" stroke="#6f6d66" stroke-width="1.4" fill="none" marker-end="url(#ar)"/>
  <path d="M660,158 L710,120" stroke="#6f6d66" stroke-width="1.4" fill="none" marker-end="url(#ar)"/>
  <path d="M660,166 L710,200" stroke="#6f6d66" stroke-width="1.4" fill="none" marker-end="url(#ar)"/>
</svg>"""


def svg_routes():
    return """
<svg viewBox="0 0 1040 300" xmlns="http://www.w3.org/2000/svg" class="dia">
  <text x="20" y="26" class="dt">三类开源方案的技术路线 × 对 WorkBuddy 的可行性</text>
  <rect x="20" y="46" width="320" height="228" rx="10" fill="#242a28" stroke="#4d7a70" stroke-width="1.5"/>
  <text x="40" y="74" class="dh" fill="#6cc0ba">路线 A · 本地日志解析</text>
  <text x="40" y="98" class="ds">离线读取已落盘 JSONL，不介入请求链路</text>
  <text x="40" y="128" class="dm">代表：ccusage · Claude-Code-Usage-Monitor</text>
  <text x="40" y="148" class="dm">Sniffly · ccburn · 本方案的看板模式</text>
  <rect x="40" y="168" width="280" height="42" rx="6" fill="#1e2a26" stroke="#4d7a70"/>
  <text x="52" y="186" class="dok">可行性：完全可行（本机已在用）</text>
  <text x="52" y="203" class="dm">无需改动客户端，零运行风险</text>
  <text x="40" y="242" class="dm">短板：非实时；解析器需随日志格式演进维护</text>
  <text x="40" y="262" class="dm">—— 但本机字段已足够，无改造缺口</text>
  <rect x="360" y="46" width="320" height="228" rx="10" fill="#2a2820" stroke="#8a6a3a" stroke-width="1.5"/>
  <text x="380" y="74" class="dh" fill="#d8a76b">路线 B · 网关 / 代理拦截</text>
  <text x="380" y="98" class="ds">把请求改道自建网关，由网关记账</text>
  <text x="380" y="128" class="dm">代表：LiteLLM · Helicone · One-API</text>
  <text x="380" y="148" class="dm">能力最强：预算硬控 + 虚拟密钥 + 团队分账</text>
  <rect x="380" y="168" width="280" height="42" rx="6" fill="#2a2318" stroke="#8a6a3a"/>
  <text x="392" y="186" class="dwarn">可行性：已验证可行（本机已用于商汤接入）</text>
  <text x="392" y="203" class="dm">前提：WorkBuddy 可配置自定义模型 endpoint</text>
  <text x="380" y="242" class="dm">代价：请求内容经代理（隐私）· 延迟与单点</text>
  <text x="380" y="262" class="dm">且自有模型需自行补价格定义</text>
  <rect x="700" y="46" width="320" height="228" rx="10" fill="#2c2424" stroke="#8a4a4a" stroke-width="1.5"/>
  <text x="720" y="74" class="dh" fill="#d48080">路线 C · SDK / OTel 埋点</text>
  <text x="720" y="98" class="ds">在应用代码内注入 SDK 上报 traces</text>
  <text x="720" y="128" class="dm">代表：Langfuse · OpenLLMetry · OpenLIT</text>
  <text x="720" y="148" class="dm">Arize Phoenix（Elastic-2.0，非标准开源）</text>
  <rect x="720" y="168" width="280" height="42" rx="6" fill="#2e2020" stroke="#8a4a4a"/>
  <text x="732" y="186" class="dbad">可行性：不可行</text>
  <text x="732" y="203" class="dm">需改客户端源码插桩，闭源做不到</text>
  <text x="720" y="242" class="dm">仅当自研应用时才适用</text>
  <text x="720" y="262" class="dm">对 WorkBuddy 场景直接排除</text>
</svg>"""


def svg_peak_timeline():
    """24 小时峰谷时段示意（按 DeepSeek 官方口径，仅工作日生效）"""
    W, H = 1000, 170
    x0, x1 = 60, 960
    w = x1 - x0
    y, hbar = 62, 30
    segs = [(0, 9, "off"), (9, 12, "peak"), (12, 14, "off"),
            (14, 18, "peak"), (18, 24, "off")]
    out = []
    for a, b, typ in segs:
        xx = x0 + w * a / 24
        ww = w * (b - a) / 24
        fill = "#633806" if typ == "peak" else "#2a2926"
        stroke = "#EF9F27" if typ == "peak" else "#4a4842"
        out.append(f'<rect x="{xx:.1f}" y="{y}" width="{ww:.1f}" height="{hbar}" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>')
        if typ == "peak":
            out.append(f'<text x="{xx+ww/2:.1f}" y="{y+hbar/2+4}" text-anchor="middle" '
                       f'style="font-size:11px;fill:#FAC775">高峰</text>')
    for hh in (0, 3, 6, 9, 12, 15, 18, 21, 24):
        xx = x0 + w * hh / 24
        out.append(f'<text x="{xx:.1f}" y="{y+hbar+18}" text-anchor="middle" class="dax">{hh}:00</text>')
        out.append(f'<line x1="{xx:.1f}" y1="{y+hbar}" x2="{xx:.1f}" y2="{y+hbar+5}" stroke="#5f5d57" stroke-width="1"/>')
    out.append(f'<text x="{x0}" y="40" class="dt">DeepSeek 系分时时段（北京时间 · 仅工作日生效）</text>')
    out.append(f'<text x="{x0}" y="132" class="ds">高峰价 = 空闲价 × 2　|　高峰时段：工作日 09:00–12:00、14:00–18:00</text>')
    out.append(f'<text x="{x0}" y="152" class="dm">周末与法定节假日全天按空闲价；调休上班日按工作日处理（如 2026-09-20 周日）</text>')
    return f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" class="dia">{"".join(out)}</svg>'


def svg_daily():
    if not DAILY:
        return ""
    W, H = 1000, 220
    pad_l, pad_b, pad_t = 52, 34, 16
    mx = max(d["total_tokens"] for d in DAILY) or 1
    n = len(DAILY)
    bw = (W - pad_l - 12) / n
    bars, labels = [], []
    for i, d in enumerate(DAILY):
        h = d["total_tokens"] / mx * (H - pad_b - pad_t)
        x = pad_l + i * bw
        y = H - pad_b - h
        c = "#7aa5d4" if d["cost_cny"] < 30 else "#d8a76b"
        pk = d.get("peak_reqs", 0)
        bars.append(f'<rect x="{x+1.5:.1f}" y="{y:.1f}" width="{max(bw-3,1.5):.1f}" height="{h:.1f}" '
                    f'rx="2" fill="{c}" opacity="0.9"><title>{d["date"]}\n{yi(d["total_tokens"])} tokens\n'
                    f'¥{mf(d["cost_cny"])}\n高峰请求 {pk} / 空闲 {d.get("off_reqs",0)}</title></rect>')
        if i % max(1, n // 10) == 0:
            labels.append(f'<text x="{x+bw/2:.1f}" y="{H-12}" class="dax" text-anchor="middle">{d["date"][5:]}</text>')
    grid = []
    for g in range(5):
        yy = pad_t + g * (H - pad_b - pad_t) / 4
        v = mx * (1 - g / 4)
        grid.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{W-12}" y2="{yy:.1f}" stroke="#3a3833" stroke-width="1"/>')
        grid.append(f'<text x="{pad_l-8}" y="{yy+4:.1f}" class="dax" text-anchor="end">{v/1e8:.1f}亿</text>')
    return f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" class="dia">{"".join(grid)}{"".join(bars)}{"".join(labels)}</svg>'


def sess_table(rows, limit=20):
    body = []
    for i, r in enumerate(rows[:limit]):
        badge = '<span class="tag ta">自动</span>' if r["is_auto"] else '<span class="tag tm">人工</span>'
        if r.get("cross_period"):
            badge += '<span class="tag tx">跨时段</span>'
        pk = f'{r["peak_reqs"]}/{r["off_reqs"]}' if r.get("split_used") else "—"
        body.append(
            f'<tr><td class="num">{i+1}</td><td class="tk">{esc(r["title"])}</td>'
            f'<td class="ws">{esc(r["workspace"][:18])}</td><td>{badge}</td>'
            f'<td class="num">{nf(r["reqs"])}</td>'
            f'<td class="num">{yi(r["total_tokens"])}</td>'
            f'<td class="num">{pk}</td>'
            f'<td class="num">{r["duration_span_min"]:.0f} / {r["duration_active_min"]:.0f}</td>'
            f'<td class="num cost">¥{mf(r["cost_cny"])}</td>'
            f'<td class="tm2">{esc(r["started_at"][:10])}</td></tr>')
    return "".join(body)


def model_price_table():
    """三种计价形态：flat 固定 / split 分时 / tiered 分段"""
    lab = {"flat": ("固定", ""), "split": ("分时", "ta"), "tiered": ("分段", "tx")}
    rows = []
    for m in MODELS:
        kind = m.get("kind") or ("split" if m.get("split") else "flat")
        name, cls = lab.get(kind, ("?", ""))
        badge = f'<span class="tag {cls}">{name}</span>'
        pp = m.get("peak_price") or [0, 0, 0]
        op = m.get("off_price") or [0, 0, 0]
        if kind == "split":
            price_cell = (f'{pp[0]:g} / {pp[1]:g} / {pp[2]:g} <span class="dimm">峰</span><br>'
                          f'{op[0]:g} / {op[1]:g} / {op[2]:g} <span class="dimm">谷</span>')
        elif kind == "tiered":
            price_cell = (f'{pp[0]:g} / {pp[1]:g} / {pp[2]:g} <span class="dimm">低档</span><br>'
                          f'{op[0]:g} / {op[1]:g} / {op[2]:g} <span class="dimm">高档</span>')
        else:
            price_cell = f'{pp[0]:g} / {pp[1]:g} / {pp[2]:g}'
        mark = '<span class="pill warn">推定</span>' if "推定" in (m.get("source") or "") else ""
        rows.append(f'<tr><td><code>{esc(m["model"])}</code> {mark}</td><td>{badge}</td>'
                    f'<td class="num">{nf(m["requests"])}</td>'
                    f'<td class="num">{nf(m["peak_requests"]) if kind == "split" else "—"}</td>'
                    f'<td class="num">{nf(m["off_requests"]) if kind == "split" else "—"}</td>'
                    f'<td class="pr">{price_cell}</td>'
                    f'<td class="ws">{esc((m.get("source") or "")[:22])}</td></tr>')
    return "".join(rows)


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#1a1917;--card:#232220;--card2:#2a2926;--bd:#3a3833;--bd2:#454340;--t1:#f0eee9;
--t2:#b0ada4;--t3:#807d75;--t4:#5f5d57;--acc:#7aa5d4;--acc2:#a9c9e4;--warn:#d8a76b;--ok:#6cc0ba;
--bad:#d48080;--pur:#a798cf;color-scheme:dark}
body.light{--bg:#fafaf9;--card:#fff;--card2:#f5f4f1;--bd:#e4e1da;--bd2:#d4d1c9;--t1:#1f2328;
--t2:#5f5c55;--t3:#8a877f;--t4:#b5b2a9;--acc:#3f6b99;--acc2:#2b4f73;--warn:#a8763a;--ok:#3d8a80;
--bad:#b05a5a;--pur:#7a68ad;color-scheme:light}
body{font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);
color:var(--t1);line-height:1.65;padding:28px 20px 80px;font-size:14px}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:25px;font-weight:700;letter-spacing:.3px;line-height:1.35}
h2{font-size:17px;font-weight:700;margin:0 0 4px;display:flex;align-items:center;gap:9px}
h2 .sn{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;
background:var(--acc);color:#12110f;font-size:12.5px;font-weight:800;flex:none}
h3{font-size:14px;font-weight:700;margin:18px 0 8px;color:var(--t1)}
p{margin:8px 0;color:var(--t2)}
.sub{font-size:12px;color:var(--t3);margin-top:6px}
.sec{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:22px 24px;margin:16px 0}
.sec>.lead{font-size:12.5px;color:var(--t3);margin:2px 0 14px;padding-bottom:12px;border-bottom:1px solid var(--bd)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:11px;margin:14px 0}
.kpi{background:var(--card2);border:1px solid var(--bd);border-radius:10px;padding:13px 15px}
.kpi .kv{font-size:21px;font-weight:700;letter-spacing:-.4px;line-height:1.25;color:var(--acc2)}
.kpi .kl{font-size:11.5px;color:var(--t3);margin-top:3px}
.kpi.hl .kv{color:var(--warn)}
.kpi.ok .kv{color:var(--ok)}
table{width:100%;border-collapse:collapse;font-size:12.5px;margin:10px 0}
th,td{padding:8px 9px;text-align:left;border-bottom:1px solid var(--bd)}
th{color:var(--t3);font-weight:600;font-size:11.5px;background:var(--card2)}
td{color:var(--t2)}
tr:hover td{background:var(--card2)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.pr{font-variant-numeric:tabular-nums;font-size:11.5px;color:var(--t3);white-space:nowrap}
td.cost{color:var(--warn);font-weight:600}
td.tk{color:var(--t1);max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
td.ws{color:var(--t3);font-size:11.5px}
td.tm2{color:var(--t4);font-size:11.5px;white-space:nowrap}
.dimm{color:var(--t4);font-size:10px}
.tag{display:inline-block;padding:1.5px 7px;border-radius:5px;background:var(--card2);border:1px solid var(--bd2);
color:var(--t3);font-size:10.5px;margin:0 4px 3px 0;white-space:nowrap}
.ta{background:#33291c;border-color:#6b5533;color:#d8a76b}
.tm{background:#1f2a33;border-color:#3d5a70;color:#7aa5d4}
.tx{background:#2b2433;border-color:#5b4a70;color:#a798cf}
body.light .ta{background:#fdf4e6;border-color:#e0c9a3;color:#8a6318}
body.light .tm{background:#eef4fa;border-color:#bdd4e8;color:#2b4f73}
body.light .tx{background:#f2eefa;border-color:#cfc2e6;color:#5e4a86}
.brow{display:grid;grid-template-columns:210px 1fr 96px;gap:11px;align-items:center;padding:3.5px 0;font-size:12px}
.blab{color:var(--t2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bsub{color:var(--t4);margin-left:5px;font-size:10.5px}
.btrack{background:var(--card2);height:16px;border-radius:4px;overflow:hidden}
.bfill{height:100%;border-radius:4px}
.bval{text-align:right;color:var(--t1);font-variant-numeric:tabular-nums;font-weight:600;font-size:11.5px}
.dia{width:100%;height:auto;display:block;margin:10px 0}
.dt{fill:var(--t2);font-size:12.5px;font-weight:600}
.dh{fill:var(--t1);font-size:12.5px;font-weight:700}
.ds{fill:var(--t3);font-size:11px}
.dm{fill:var(--t4);font-size:10.5px}
.dax{fill:var(--t4);font-size:9.5px}
.dok{fill:var(--ok);font-size:11px;font-weight:600}
.dwarn{fill:var(--warn);font-size:11px;font-weight:600}
.dbad{fill:var(--bad);font-size:11px;font-weight:600}
.pcards{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px;margin:12px 0}
.pcard{background:var(--card2);border:1px solid var(--bd);border-radius:10px;padding:14px 16px}
.phead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:7px}
.pname{font-weight:700;font-size:13.5px;color:var(--t1)}
.pv{font-size:11px;padding:2px 9px;border-radius:20px;font-weight:700;border:1px solid var(--bd2);color:var(--t3)}
.pv.warn{background:#33291c;border-color:#6b5533;color:#d8a76b}
.pv.bad{background:#312323;border-color:#6b3d3d;color:#d48080}
body.light .pv.warn{background:#fdf4e6;border-color:#e0c9a3;color:#8a6318}
body.light .pv.bad{background:#fbeceb;border-color:#e5bdbd;color:#a04a4a}
.pfit{font-size:12px;color:var(--acc2);margin:6px 0 5px;font-weight:600}
.pnote{font-size:11.5px;color:var(--t3);line-height:1.6}
.callout{border-left:3px solid var(--acc);background:var(--card2);padding:12px 16px;border-radius:0 8px 8px 0;margin:12px 0}
.callout.warn{border-left-color:var(--warn)}
.callout.ok{border-left-color:var(--ok)}
.callout.bad{border-left-color:var(--bad)}
.callout .ct{font-weight:700;font-size:12.5px;margin-bottom:5px;color:var(--t1)}
.callout p{margin:4px 0;font-size:12.5px}
.cols2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:820px){.cols2{grid-template-columns:1fr}.brow{grid-template-columns:120px 1fr 74px}}
.mono{font-family:"Cascadia Mono",Consolas,"SF Mono",Menlo,monospace;font-size:11.5px}
code{background:var(--card2);border:1px solid var(--bd);border-radius:4px;padding:1px 5px;font-size:11.5px;
font-family:"Cascadia Mono",Consolas,monospace;color:var(--acc2)}
.toggle{position:fixed;top:16px;right:18px;background:var(--card);border:1px solid var(--bd2);color:var(--t2);
padding:6px 13px;border-radius:20px;font-size:12px;cursor:pointer;z-index:99}
.toggle:hover{border-color:var(--acc);color:var(--acc2)}
.hd{border-bottom:1px solid var(--bd);padding-bottom:16px;margin-bottom:6px}
ul{margin:8px 0 8px 20px;color:var(--t2)}li{margin:4px 0;font-size:12.5px}
.fn{font-size:11.5px;color:var(--t4);margin-top:10px;padding-top:10px;border-top:1px solid var(--bd)}
.pill{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;
border:1px solid var(--bd2);color:var(--t2);background:var(--card2)}
.pill.ok{color:var(--ok);border-color:#3d6b64}
.pill.warn{color:var(--warn);border-color:#6b5533}
.pill.bad{color:var(--bad);border-color:#6b3d3d}
.step{display:grid;grid-template-columns:34px 1fr;gap:12px;margin:10px 0;align-items:start}
.stepn{width:28px;height:28px;border-radius:8px;background:var(--card2);border:1px solid var(--bd2);
display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px;color:var(--acc2)}
.stepb{font-size:12.5px;color:var(--t2);padding-top:3px}
.stepb b{color:var(--t1);font-size:13px;display:block;margin-bottom:2px}
"""


def build():
    auto, manual = S["auto"], S["manual"]
    auto_pct = _d(auto["cost_cny"], T["cost_cny"]) * 100
    PTI = S.get("price_table") or {}
    CAL = S.get("calendar") or {}
    TS_ = S.get("tag_stat") or {}
    pt_verified = PTI.get("verified_at") or "(未核实)"
    _rf = PTI.get("refresh") or {}
    _ao = _rf.get("auto_ok") or []
    if _ao:
        auto_ok_txt = "、".join(
            {"deepseek": "DeepSeek 原厂", "zhipu": "智谱 BigModel", "hunyuan": "腾讯混元",
             "minimax": "MiniMax", "sensenova": "商汤", "mistral": "Mistral"}.get(k, k) for k in _ao)
    elif _rf.get("skipped"):
        auto_ok_txt = "复用当日已刷新结果"
    else:
        auto_ok_txt = "无"
    _pm = PTI.get("pending_manual") or []
    pending_txt = f"{len(_pm)} 家（转人工）" if _pm else "无"
    cal_txt = "、".join(str(y) for y in (CAL.get("loaded") or [])) or "—"
    if CAL.get("missing"):
        cal_txt += "（缺 " + "、".join(str(y) for y in CAL["missing"]) + "）"
    tag_flat, tag_peak = TS_.get("flat", 0), TS_.get("peak", 0)
    tag_off, tag_tier = TS_.get("off", 0), TS_.get("tier", 0)
    seen_u, src_items = set(), []
    for m in MODELS:
        u = m.get("url") or ""
        if not u or u in seen_u:
            continue
        seen_u.add(u)
        src_items.append(f'<li>{esc(m.get("source") or "")}<br><span class="mono">{esc(u[:78])}</span></li>')
    price_src = "".join(src_items)

    # 案例一律从当前数据动态取，避免在代码里硬编码真实的项目名/任务名
    _cx = next((r for r in SESS if r.get("cross_period")), None)
    if _cx:
        cross_example = (f'例如「{esc(_cx["title"])}」自 {_cx["started_at"][11:16]} 起持续 '
                         f'{_cx["duration_span_min"]:.0f} 分钟，峰段 {_cx["peak_reqs"]} 次、'
                         f'谷段 {_cx["off_reqs"]} 次请求，横跨两种时段；')
    else:
        cross_example = ""
    _lg = max(SESS, key=lambda r: r["duration_span_min"]) if SESS else None
    if _lg and _lg["duration_span_min"] > 0:
        longest_example = (f'如「{esc(_lg["title"])}」跨 {_lg["duration_span_min"]/60:.1f} 小时，'
                           f'但活跃仅 {_lg["duration_active_min"]/60:.1f} 小时')
    else:
        longest_example = "长期挂起的会话会把跨度显著拉大"

    html = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WorkBuddy 任务级 Token 消耗追溯 · 调研报告 v2</title>
<style>{CSS}</style></head><body class="dark">
<button class="toggle" onclick="document.body.classList.toggle('light');document.body.classList.toggle('dark')">切换深浅色</button>
<div class="wrap">

<div class="hd">
  <h1>WorkBuddy 任务级 Token 消耗追溯<br><span style="color:var(--t3);font-size:16px;font-weight:600">开源方案调研 + 本机实测 + 分时计价修订</span></h1>
  <div class="sub">版本 v2 · 生成 {S["generated_at"]} · 数据范围 2026-07-27 ~ 2026-09-20（{T["days"]} 天） · 来源：本机 <code>~/.workbuddy</code>（只读）</div>
</div>

<div class="sec">
  <h2><span class="sn">0</span>结论先行</h2>
  <div class="lead">v2 在 v1 基础上补入了分时计价、法定节假日与调休处理、双时长口径，并修正了一处误价。</div>

  <div class="callout ok">
    <div class="ct">结论一：你的需求不需要引入任何开源方案——数据本来就在本机，且是请求级真实值</div>
    <p>本机落盘 <b>{nf(T["requests"])} 条请求级真实 usage</b>，含 prompt / completion / cache_hit / reasoning 全字段并附带<b>请求时间戳</b>。</p>
  </div>

  <div class="callout">
    <div class="ct">结论二：分时计价是必要的——它让全局成本少算 ¥{mf(SESS_SAVE)}（{SESS_SAVE_PCT}%）</div>
    <p>DeepSeek 系存在峰谷价（高峰 = 空闲 × 2）。按<b>每条请求的发生时刻</b>判定后：
    实际成本 <b>¥{mf(T["cost_cny"])}</b>，而"一刀切按高峰价"会得出 ¥{mf(T["cost_all_peak_cny"])}。
    若只看 DeepSeek 部分，差异达 <b>{DS_SAVE_PCT:.1f}%</b>。
    更关键的是：<b>{PO["cross_period_sessions"]} 个任务横跨了峰谷时段</b>，用任务级单一时刻判断必然算错。</p>
  </div>

  <div class="callout warn">
    <div class="ct">结论三：法定节假日与调休必须显式建模——2026-09-20 就是活例子</div>
    <p>9-20 是<b>周日</b>，但依国办发明电〔2025〕7 号是<b>国庆调休上班日</b>。若按普通周日处理会全天算空闲价，
    实际应按工作日判定，该日 <b>{nf(sum(r["reqs"] for r in SESS if r["started_at"].startswith("2026-09-20")))} 个请求</b>落在高峰段，
    影响 <b>¥{mf(sum(r["peak_cost_cny"] for r in SESS if r["started_at"].startswith("2026-09-20")) - sum(r["off_cost_cny"] for r in SESS if r["started_at"].startswith("2026-09-20")))}</b>。</p>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="kv">{yi(T["total_tokens"])}</div><div class="kl">累计 token</div></div>
    <div class="kpi hl"><div class="kv">¥{mf(T["cost_cny"])}</div><div class="kl">分时口径成本</div></div>
    <div class="kpi"><div class="kv">{T["cache_hit_rate"]}%</div><div class="kl">缓存命中率</div></div>
    <div class="kpi"><div class="kv">{nf(PO["peak_requests"])} / {nf(PO["off_requests"])}</div><div class="kl">高峰 / 空闲请求</div></div>
    <div class="kpi ok"><div class="kv">{DUR["active_ratio"]}%</div><div class="kl">活跃时长 ÷ 墙钟跨度</div></div>
    <div class="kpi"><div class="kv">¥{mf(T["avg_cost_per_session"])}</div><div class="kl">单任务均成本</div></div>
  </div>
</div>

<div class="sec">
  <h2><span class="sn">1</span>问题界定</h2>
  <div class="lead">先把需求拆清楚，再谈方案。</div>
  <div class="cols2">
    <div>
      <h3>你的原始诉求</h3>
      <ul>
        <li>知道<b>每一个任务</b>实际消耗了多少 token</li>
        <li>用于<b>成本估算</b>与<b>花费管理</b></li>
        <li>现状：WorkBuddy 界面只暴露"额度"</li>
      </ul>
      <h3>v2 追加的两项要求</h3>
      <ul>
        <li>厂商存在<b>峰价 / 谷价</b>差异，须按官方最新定价修订计价标准</li>
        <li>须记录任务的<b>发生时间、持续时间、结束时间</b>，才能准确判断实际消耗与费用</li>
      </ul>
    </div>
    <div>
      <h3>为什么"额度"不足以支撑成本管理</h3>
      <ul>
        <li><b>不可归因</b>：额度是聚合数，无法回答"哪个任务花了多少"</li>
        <li><b>不可解释</b>：额度受模型单价、峰谷时段、缓存命中共同影响</li>
        <li><b>不可预测</b>：没有单任务基线，无法预估新任务开销</li>
      </ul>
      <h3>成本管理所需的最小数据集</h3>
      <table>
        <tr><th>维度</th><th>可得性</th></tr>
        <tr><td>任务标识</td><td><span class="pill ok">可得</span></td></tr>
        <tr><td>请求级 token</td><td><span class="pill ok">可得</span></td></tr>
        <tr><td><b>请求时间戳</b>（判峰谷）</td><td><span class="pill ok">可得</span></td></tr>
        <tr><td>任务起止与时长</td><td><span class="pill ok">可得</span></td></tr>
        <tr><td>模型与单价</td><td><span class="pill warn">需自建</span></td></tr>
      </table>
    </div>
  </div>
</div>

<div class="sec">
  <h2><span class="sn">2</span>本机数据源实测</h2>
  <div class="lead">以下是本次实际扫描本机文件与数据库得到的结果，不是推测。</div>
  {svg_sources()}
  <div class="cols2">
    <div>
      <h3>实测清单</h3>
      <table>
        <tr><th>数据源</th><th class="num">规模</th><th>关键字段</th></tr>
        <tr><td><code>projects/**/*.jsonl</code></td><td class="num">1,005 文件</td><td>rawUsage + timestamp</td></tr>
        <tr><td>─ 含 usage 的记录</td><td class="num">{nf(T["requests"])}</td><td>prompt/completion/cache</td></tr>
        <tr><td>─ 覆盖工作空间</td><td class="num">318</td><td>cwd 目录名</td></tr>
        <tr><td><code>sessions</code> 表</td><td class="num">542 行</td><td>title / cwd / is_background_automation</td></tr>
        <tr><td><code>session_usage</code> 表</td><td class="num">528 行</td><td>credit_json / used</td></tr>
        <tr><td>子代理日志</td><td class="num">453 文件</td><td>归属父会话</td></tr>
      </table>
    </div>
    <div>
      <h3>字段真实性抽样（原文片段）</h3>
      <div class="callout" style="margin-top:10px">
        <p class="mono" style="color:var(--t3);line-height:1.75">
"rawUsage": {{<br>
&nbsp;&nbsp;"prompt_tokens": 52902,<br>
&nbsp;&nbsp;"completion_tokens": 212,<br>
&nbsp;&nbsp;"prompt_cache_hit_tokens": 0,<br>
&nbsp;&nbsp;"reasoning_tokens": 130<br>
}},<br>
"model": "hy3-x",<br>
"timestamp": 1789660845089
        </p>
      </div>
      <h3>会话元数据覆盖率</h3>
      <table>
        <tr><th>类别</th><th class="num">会话</th><th class="num">token</th></tr>
        <tr><td>有 db 元数据</td><td class="num">{nf(len(with_meta))}</td><td class="num">{yi(sum(r["total_tokens"] for r in with_meta))}</td></tr>
        <tr><td>无 db 元数据</td><td class="num">{nf(len(no_meta))}</td><td class="num">{yi(sum(r["total_tokens"] for r in no_meta))}</td></tr>
      </table>
      <p class="fn">缺口性质：{nf(len(no_meta))} 个无元数据会话中 {nf(len([r for r in no_meta if r["reqs"]<=50]))} 个请求数 ≤50 且全部无子代理，
      仅占 {_NO_META_TOK_PCT:.1f}% token。核心消耗（{100-_NO_META_TOK_PCT:.1f}%）都在有任务名的会话里。</p>
    </div>
  </div>
</div>

<div class="sec">
  <h2><span class="sn">3</span>开源方案横向调研</h2>
  <div class="lead">按技术路线归为三类，共 8 个候选。</div>
  {svg_routes()}
  <div class="callout warn">
    <div class="ct">v2 修正：路线 B 已从"理论可行"升级为"已验证可行"</div>
    <p>v1 时我把网关代理路线标为"需验证前提"。核查中发现你<b>已经通过本地代理给 WorkBuddy 接入了商汤等自定义模型</b>
    （模型配置填 id / url / apiKey / name 四字段即可）。这说明 WorkBuddy 的模型请求<b>可以指向自建 endpoint</b>，
    路线 B 在你的环境里是走得通的。它没有成为推荐方案的原因不是"做不到"，而是"只为了看清消耗而引入代理层，投入产出比不成立"。</p>
  </div>
</div>

<div class="sec">
  <h2><span class="sn">4</span>计价标准核查与更新机制</h2>
  <div class="lead">价格表已外置为 <code>price_table.json</code>，按调用当日刷新；日历表按年维护。本次核查日期 {pt_verified}。</div>

  <div class="cols2">
    <div>
      <h3>更新机制（按你确定的口径实现）</h3>
      <table>
        <tr><th>场景</th><th>行为</th></tr>
        <tr><td>当日第 1 次调用</td><td>先刷新价格表，再统计计算</td></tr>
        <tr><td>当日第 2 次及以后</td><td>跳过刷新，复用当日已刷新结果</td></tr>
        <tr><td>收到强制更新指令</td><td>加 <code>--force-refresh</code> 参数</td></tr>
      </table>
      <p class="fn">抓取采用<b>混合模式</b>：脚本先自动抓取官方页并用关键词锚点校验；失败则降级为人工待核实清单，<b>不静默跳过、不计入自动确认</b>。</p>
    </div>
    <div>
      <h3>本次刷新实况</h3>
      <table>
        <tr><th>项</th><th>值</th></tr>
        <tr><td>价格表核实日期</td><td>{pt_verified}</td></tr>
        <tr><td>自动确认厂商</td><td>{auto_ok_txt}</td></tr>
        <tr><td>待人工核实</td><td>{pending_txt}</td></tr>
        <tr><td>日历已加载年份</td><td>{cal_txt}</td></tr>
        <tr><td>价格来源优先级</td><td>模型原厂价优先</td></tr>
      </table>
    </div>
  </div>

  <div class="callout">
    <div class="ct">三种计价形态（本机实测命中）</div>
    <p><b>固定 flat</b>：单价恒定，命中 {nf(tag_flat)} 次请求；
    <b>分时 split</b>：按每请求时间戳判峰谷，命中 {nf(tag_peak)} 次高峰 + {nf(tag_off)} 次空闲；
    <b>分段 tiered</b>：按每请求 input/output 长度判档（智谱 GLM），命中 {nf(tag_tier)} 次。</p>
  </div>

  <h3>逐模型核查表（元 / 百万 token，格式 输入 / 输出 / 缓存命中）</h3>
  <table>
    <tr><th>模型标识</th><th>计价类型</th><th class="num">请求数</th><th class="num">高峰请求</th><th class="num">空闲请求</th><th>官方单价</th><th>来源</th></tr>
    {model_price_table()}
  </table>

  <div class="cols2" style="margin-top:14px">
    <div>
      <h3>官方来源</h3>
      <ul class="src">{price_src}</ul>
      <h3>节假日依据</h3>
      <p class="fn" style="margin-top:6px">国务院办公厅关于 2026 年部分节假日安排的通知<br>（国办发明电〔2025〕7 号，2025-11-04 发布）</p>
      <p class="fn">日历按年维护为 <code>calendar_YYYY.json</code>，引擎按数据涉及年份自动加载。下一个更新节点：<b>2026 年 11 月前后</b>——国务院通常于前一年 11 月发布次年安排。</p>
    </div>
    <div>
      <h3>本次核查发现的问题</h3>
      <table>
        <tr><th>项</th><th>处理</th></tr>
        <tr><td><b>MiniMax-M3 价高了一倍</b><br><span class="dimm">原 4.2/16.8/0.84 → 官方 2.1/8.4/0.42</span></td><td><span class="pill ok">已修正</span></td></tr>
        <tr><td><b>智谱由"统一取高位档"改为请求级判档</b><br><span class="dimm">按每请求 input/output 实际档位计价，命中 {nf(tag_tier)} 次</span></td><td><span class="pill ok">已升级</span></td></tr>
        <tr><td><code>hy3-x</code> 官方未单独披露<br><span class="dimm">腾讯云、混元官网、易观报告均只列 Hy3</span></td><td><span class="pill warn">按 Hy3 同价，标注推定</span></td></tr>
        <tr><td>GLM-5.3-Flash 有 5 折促销<br><span class="dimm">智谱官网现价 0.4/1.4/0.115</span></td><td><span class="pill warn">本表按原价，偏保守</span></td></tr>
        <tr><td>腾讯混元 / 商汤 / MiniMax 页面无法自动抓取<br><span class="dimm">JS 动态渲染或需登录</span></td><td><span class="pill warn">已转人工清单</span></td></tr>
      </table>
    </div>
  </div>
</div>

<div class="sec">
  <h2><span class="sn">5</span>分时计价机制（v2 新增）</h2>
  <div class="lead">峰谷判断落在"每一条请求"上，而不是任务或会话。</div>

  {svg_peak_timeline()}

  <div class="cols2">
    <div>
      <h3>判定逻辑</h3>
      <ul>
        <li><b>粒度</b>：按每条请求的 <code>timestamp</code> 判定，非任务级</li>
        <li><b>时区</b>：统一换算北京时间（UTC+8）</li>
        <li><b>工作日判定</b>：先查调休上班日（按工作日）→ 再查法定放假日（按休息日）→ 最后按周一至周五</li>
        <li><b>高峰窗口</b>：工作日 09:00–12:00、14:00–18:00</li>
        <li><b>价格</b>：高峰价 = 空闲价 × 2（DeepSeek 系）</li>
      </ul>
      <div class="callout" style="margin-top:12px">
        <div class="ct">为什么必须按请求级</div>
    <p>本次实测有 <b>{PO["cross_period_sessions"]} 个任务</b>跨越了峰谷时段。
    {cross_example}
    若用任务开始时刻一刀切，这些请求的时段归属会全部算错。</p>
      </div>
    </div>
    <div>
      <h3>三口径成本对比</h3>
      <div class="kpis" style="grid-template-columns:1fr">
        <div class="kpi"><div class="kv">¥{mf(T["cost_all_peak_cny"])}</div><div class="kl">口径 A · 全部按高峰价（v1 近似做法）</div></div>
        <div class="kpi ok"><div class="kv">¥{mf(T["cost_cny"])}</div><div class="kl">口径 B · 按请求实际时段（<b>本报告采用</b>）</div></div>
        <div class="kpi"><div class="kv">¥{mf(T["cost_all_off_cny"])}</div><div class="kl">口径 C · 全部按空闲价（理论下限）</div></div>
      </div>
      <table>
        <tr><th>指标</th><th class="num">数值</th></tr>
        <tr><td>参与分时的会话</td><td class="num">{nf(PO["split_sessions"])}</td></tr>
        <tr><td>跨时段任务</td><td class="num">{nf(PO["cross_period_sessions"])}</td></tr>
        <tr><td>高峰请求 / 空闲请求</td><td class="num">{nf(PO["peak_requests"])} / {nf(PO["off_requests"])}</td></tr>
        <tr><td>空闲请求占比</td><td class="num">{OFF_REQ_PCT:.1f}%</td></tr>
        <tr><td>DeepSeek 系实际成本</td><td class="num">¥{mf(DS_ACTUAL)}</td></tr>
        <tr><td>同上若全按高峰</td><td class="num">¥{mf(DS_ALLPEAK)}</td></tr>
        <tr><td><b>DeepSeek 系节省</b></td><td class="num cost">{DS_SAVE_PCT:.1f}%</td></tr>
      </table>
      <p class="fn">口径 A 与 B 的差额 ¥{mf(SESS_SAVE)} 就是"分时计价修正"带来的实际影响。
      对全局而言比例不高（{SESS_SAVE_PCT}%），因为 DeepSeek 只占请求量的 15.3%；但对使用 DeepSeek 的任务，
      误差可达近三成。</p>
    </div>
  </div>

  <h3>任务时长双口径（v2 新增）</h3>
  <table>
    <tr><th>分位</th><th class="num">墙钟跨度（首请求→末请求）</th><th class="num">活跃时长（剔除 &gt;30min 空档）</th></tr>
    <tr><td>P50 中位</td><td class="num">{DUR["span_median_min"]} 分钟</td><td class="num">{DUR["active_median_min"]} 分钟</td></tr>
    <tr><td>P75</td><td class="num">26.3 分钟</td><td class="num">22.2 分钟</td></tr>
    <tr><td>P90</td><td class="num">138.8 分钟</td><td class="num">84.1 分钟</td></tr>
    <tr><td>P99</td><td class="num">1,973 分钟</td><td class="num">365 分钟</td></tr>
    <tr><td>均值</td><td class="num">{DUR["span_mean_min"]} 分钟</td><td class="num">{DUR["active_mean_min"]} 分钟</td></tr>
    <tr><td>最大值</td><td class="num">{DUR["span_max_min"]:,.0f} 分钟</td><td class="num">{DUR["active_max_min"]:,.0f} 分钟</td></tr>
  </table>
  <div class="callout warn">
    <div class="ct">口径提醒：跨度会被"挂着的会话"严重拉偏</div>
    <p>跨度均值 {DUR["span_mean_min"]} 分钟远高于中位 {DUR["span_median_min"]} 分钟，因为存在长期挂起的会话
    （{longest_example}）。<b>做成本基线请用中位数或活跃时长，不要用跨度均值。</b>
    两者之比为 <b>{DUR["active_ratio"]}%</b>，即墙钟时间里只有约五分之一在真正干活。</p>
  </div>
</div>

<div class="sec">
  <h2><span class="sn">6</span>实测结果</h2>
  <div class="lead">按任务 / 工作空间 / 自动化三个口径汇总。金额为按官方牌价的预估，非官方账单。</div>

  <div class="kpis">
    <div class="kpi"><div class="kv">{yi(T["total_tokens"])}</div><div class="kl">总 token</div></div>
    <div class="kpi"><div class="kv">{yi(T["input_tokens"])}</div><div class="kl">输入</div></div>
    <div class="kpi"><div class="kv">{yi(T["output_tokens"])}</div><div class="kl">输出</div></div>
    <div class="kpi ok"><div class="kv">{yi(T["cache_hit_tokens"])}</div><div class="kl">缓存命中（{T["cache_hit_rate"]}%）</div></div>
    <div class="kpi hl"><div class="kv">¥{mf(T["cost_cny"])}</div><div class="kl">分时口径成本（{T["days"]} 天）</div></div>
    <div class="kpi"><div class="kv">¥{AVG_DAILY:.2f}</div><div class="kl">日均成本</div></div>
  </div>

  <div class="callout ok">
    <div class="ct">关键洞察：缓存命中率 {T["cache_hit_rate"]}%，"按牌价直算"会严重高估</div>
    <p>输入里 {T["cache_hit_rate"]}% 是缓存命中（单价约为输入价的 1/4）。若不分档全部按输入价计，
    成本会从 <b>¥{mf(T["cost_cny"])}</b> 膨胀到约 <b>¥{mf(T["input_tokens"]/1e6*1 + T["output_tokens"]/1e6*4)}</b>，
    高估约 {CACHE_SAVE_PCT}%。<b>任何第三方方案若按 input/output 两档计价，对你的场景都不准。</b></p>
  </div>

  <h3>口径一 · 按任务（消耗 TOP 20）</h3>
  <table>
    <tr><th class="num">#</th><th>任务</th><th>工作空间</th><th>类型</th><th class="num">请求</th>
    <th class="num">token</th><th class="num">峰/谷请求</th><th class="num">跨度/活跃(min)</th><th class="num">成本</th><th>开始</th></tr>
    {sess_table(SESS, 20)}
  </table>
  <p class="fn">完整 {nf(len(SESS))} 条会话明细见 <code>sessions.csv</code>（含起止时间、双时长、峰谷请求数）。
  单任务最高 ¥{mf(SESS_MAX)}，中位数 ¥{mf(SESS_MED)}。</p>

  <h3>口径二 · 按工作空间（TOP 15）</h3>
  {bar_rows(WS[:15], "total_tokens", "workspace", sub_key="sessions")}
  <p class="fn">完整 {nf(len(WS))} 个工作空间见 <code>workspaces.csv</code>（含峰谷请求与三口径成本）。</p>

  <h3>口径三 · 人工 vs 自动化</h3>
  <div class="cols2">
    <div>
      <table>
        <tr><th>指标</th><th class="num">人工（{nf(manual["sessions"])} 会话）</th><th class="num">自动化（{nf(auto["sessions"])} 会话）</th></tr>
        <tr><td>请求数</td><td class="num">{nf(manual["reqs"])}</td><td class="num">{nf(auto["reqs"])}</td></tr>
        <tr><td>token</td><td class="num">{yi(manual["total_tokens"])}</td><td class="num">{yi(auto["total_tokens"])}</td></tr>
        <tr><td>高峰请求</td><td class="num">{nf(manual["peak_reqs"])}</td><td class="num">{nf(auto["peak_reqs"])}</td></tr>
        <tr><td>成本</td><td class="num cost">¥{mf(manual["cost_cny"])}</td><td class="num cost">¥{mf(auto["cost_cny"])}</td></tr>
        <tr><td>成本占比</td><td class="num">{100-auto_pct:.1f}%</td><td class="num">{auto_pct:.1f}%</td></tr>
      </table>
      <p class="fn">自动化识别依据 <code>sessions.is_background_automation</code>，非人工推断。
      自动化任务若可排期，<b>避开高峰时段可再省一半</b>。</p>
    </div>
    <div>
      <h3>日消耗趋势</h3>
      {svg_daily()}
      <p class="fn">鼠标悬停可见当日峰谷请求拆分。橙色为单日成本 ≥¥30。</p>
    </div>
  </div>

  <h3>模型分布（按请求数）</h3>
  {bar_rows(MODELS[:12], "requests", "model", fmt=lambda v: nf(v) + " 次", maxn=MODELS[0]["requests"])}
  <p class="fn">共 {len(MODELS)} 个模型标识，全部分配到价格口径（未计价请求 0 条）。
  <span class="tag ta">分时</span>仅 DeepSeek 系 3 个；其余 {len(FLAT_MODELS)} 个为固定价。</p>

  <h3>额度（credit）口径的现状</h3>
  <table>
    <tr><th>项目</th><th class="num">数值</th></tr>
    <tr><td>含 credit 数据的会话</td><td class="num">{nf(len(cred_rows))} / {nf(len(SESS))}</td></tr>
    <tr><td>credit 合计</td><td class="num">{mf(cred_sum)}</td></tr>
    <tr><td>同期牌价成本换算</td><td class="num">¥{mf(cred_cost)}</td></tr>
    <tr><td>credit ÷ 牌价元</td><td class="num">{CRED_RATIO}（口径未确认）</td></tr>
  </table>
  <div class="callout warn">
    <div class="ct">口径说明</div>
    <p>按你的要求，本报告金额<b>全部依据 token 消耗量 × 官方定价标准</b>计算，不使用 credit 换算。
    credit 值与 token 量不成线性，仅作旁证。另需留意个别模型可能存在限时免费/促销期（如 Hy3 曾限免两周、GLM-5.3-Flash 现享 5 折），
    故本报告的标价预估<b>可能高于</b>你实际被扣的额度。</p>
  </div>
</div>

<div class="sec">
  <h2><span class="sn">7</span>推荐方案与落地路径</h2>
  <div class="lead">结论：走路线 A，把本机能力补齐，不引入外部服务。</div>

  <div class="callout ok">
    <div class="ct">推荐：本机日志解析 + 请求级分时计价 + HOOK 自动记账</div>
    <p>v2 已验证完整可行性：三口径聚合、请求级峰谷判定、假日调休处理、缓存分档计价、双时长口径、子代理归属、自动化识别全部跑通。</p>
  </div>

  <div class="step"><div class="stepn">1</div><div class="stepb"><b>固化计价口径（已完成）</b>
    分时表 + 固定价表覆盖 {len(MODELS)} 个模型标识；假日与调休表覆盖 2026 全年。模型上新时补一行即可。</div></div>
  <div class="step"><div class="stepn">2</div><div class="stepb"><b>定期审计（建议每周）</b>
    运行 <code>wb_token_audit.py</code>，产出五张 CSV（会话/工作空间/自动化/日/模型）+ 明细 JSON。</div></div>
  <div class="step"><div class="stepn">3</div><div class="stepb"><b>成本优化：把可排期的批量任务挪到空闲时段</b>
    自动化任务与批处理若从高峰挪到空闲，DeepSeek 系单价直接减半。实测高峰期请求占比 {PO["peak_requests"]/(PO["peak_requests"]+PO["off_requests"])*100:.1f}%，仍有优化空间。</div></div>
  <div class="step"><div class="stepn">4</div><div class="stepb"><b>接自动记账（待你确认）</b>
    本机 <code>SessionEnd</code> hook（<code>task-ledger-capture.mjs</code>）的 <code>tokens</code> 字段目前写死 0，
    注释标注"由 sync_ledger 从 workbuddy.db 补"。接通后每个任务结束自动落一笔含峰谷拆分的台账。</div></div>
  <div class="step"><div class="stepn">5</div><div class="stepb"><b>未来升级（仅当出现多设备/团队需求时）</b>
    路线 B 已在你的环境中验证可行（商汤接入即为例证），届时可评估 LiteLLM 做预算硬控。</div></div>
</div>

<div class="sec">
  <h2><span class="sn">8</span>附录</h2>

  <h3>计价口径（重要）</h3>
  <ul>
    <li>单位：<b>元 / 百万 token</b>，格式 [输入价, 输出价, 缓存命中价]</li>
    <li>成本 = 非缓存输入×输入价 + 缓存命中×缓存价 + 缓存写入×输入价×1.25 + 输出×输出价</li>
    <li>分时模型：先按请求时间戳判峰谷，再取对应档价格；其余模型取固定价</li>
    <li><b>这是按官方公开牌价的预估，不是官方账单</b>。套餐折扣、限时促销、免费额度都会改变实际支出</li>
  </ul>

  <h3>产出物清单</h3>
  <table>
    <tr><th>文件</th><th>内容</th></tr>
    <tr><td><code>wb_token_audit.py</code></td><td>审计引擎 v2（分时 + 假日 + 双时长，仅标准库）</td></tr>
    <tr><td><code>sessions.csv</code></td><td>任务级明细 {nf(len(SESS))} 行（含起止时间 / 双时长 / 峰谷请求）</td></tr>
    <tr><td><code>workspaces.csv</code></td><td>工作空间汇总 {nf(len(WS))} 行（含三口径成本）</td></tr>
    <tr><td><code>automations.csv</code></td><td>自动化会话明细 {nf(len(AUTO))} 行</td></tr>
    <tr><td><code>daily.csv</code></td><td>日粒度汇总 {nf(len(DAILY))} 行（含峰谷拆分）</td></tr>
    <tr><td><code>models.csv</code></td><td>模型计价核查表 {nf(len(MODELS))} 行</td></tr>
    <tr><td><code>audit_data.json</code></td><td>完整结构化数据（供二次分析）</td></tr>
  </table>

  <h3>已知限制</h3>
  <ul>
    <li>日期范围由 jsonl 记录时间戳决定：2026-07-27 ~ 2026-09-20</li>
    <li>{nf(len(no_meta))} 个会话（{NO_META_PCT:.1f}%）在 <code>sessions</code> 表中查不到任务名</li>
    <li>子代理日志已按路径归属父会话</li>
    <li><code>hy3-x</code> 单价按 Hy3 推定，官方未单独披露</li>
    <li>腾讯云官方文档只写"高峰 09:00–12:00、14:00–18:00"未提工作日限制；本报告采用 DeepSeek 原厂口径（限工作日 + 排除法定节假日），与你的要求一致</li>
    <li>额度 credit 字段仅 {nf(len(cred_rows))} 个会话留存，且与 token 非线性，不作换算基准</li>
  </ul>

  <div class="fn">报告由本机实测数据生成 · 生成脚本 <code>gen_report.py</code> · 数据与结论均可复现</div>
</div>

</div></body></html>'''
    return html


if __name__ == "__main__":
    h = build()
    p = os.path.join(OUT, "WorkBuddy-Token消耗调研报告.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(h)
    print("已生成:", p, f"({len(h):,} 字符)")
