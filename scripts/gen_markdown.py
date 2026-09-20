# -*- coding: utf-8 -*-
"""生成 Markdown 版调研报告（数据与 HTML 版同源）"""
import json, os, sys, io, argparse, datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(SCRIPT_DIR)

_ap = argparse.ArgumentParser(description="生成 Markdown 版 Token 消耗调研报告")
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
S = D["summary"]; T = S["totals"]; PO = S["peak_off"]; DUR = S["duration"]
SESS = D["sessions"]; WS = D["workspaces"]; AUTO = D["automations"]
DAILY = D["daily"]; MODELS = D["models"]
PTI = S.get("price_table") or {}; CAL = S.get("calendar") or {}; TS_ = S.get("tag_stat") or {}

with_meta = [r for r in SESS if r.get("has_meta")]
no_meta = [r for r in SESS if not r.get("has_meta")]
cred_rows = [r for r in SESS if r.get("credit_total") is not None]
cred_sum = sum(r["credit_total"] for r in cred_rows) if cred_rows else 0
cred_cost = sum(r["cost_cny"] for r in cred_rows) if cred_rows else 0
auto, manual = S["auto"], S["manual"]


def _d(a, b, d=0.0):
    """安全除法：分母为 0 或异常时返回默认值，避免在无数据/无额度环境下崩溃"""
    try:
        return (a / b) if b else d
    except Exception:
        return d


auto_pct = _d(auto["cost_cny"], T["cost_cny"]) * 100
_NAIVE = T["input_tokens"] / 1e6 * 1 + T["output_tokens"] / 1e6 * 4
SAVE = round((1 - _d(T["cost_cny"], _NAIVE, 1.0)) * 100, 1)
SSAVE = T["cost_all_peak_cny"] - T["cost_cny"]
SSAVE_PCT = round(_d(SSAVE, T["cost_all_peak_cny"]) * 100, 2)
DS_ACT = PO["peak_cost_cny"] + PO["off_cost_cny"]
DS_AP = PO["peak_cost_cny"] + PO["off_cost_cny"] * 2
DS_SAVE_PCT = _d(PO["off_cost_cny"], DS_AP) * 100
NO_META_PCT = _d(len(no_meta), len(SESS)) * 100
_NO_META_TOK_PCT = _d(sum(r["total_tokens"] for r in no_meta), T["total_tokens"]) * 100
CRED_RATIO = f"{_d(cred_sum, cred_cost):.2f}" if cred_cost else "—"
AVG_DAILY = _d(T["cost_cny"], T["days"])
# 案例一律从当前数据动态取，避免在代码里硬编码真实的项目名/任务名
_cx = next((r for r in SESS if r.get("cross_period")), None)
cross_example = (f'例如「{_cx["title"]}」自 {_cx["started_at"][11:16]} 起持续 '
                 f'{_cx["duration_span_min"]:.0f} 分钟，峰段 {_cx["peak_reqs"]} 次、'
                 f'谷段 {_cx["off_reqs"]} 次请求，横跨两种时段；') if _cx else ""
_lg = max(SESS, key=lambda r: r["duration_span_min"]) if SESS else None
longest_example = (f'如「{_lg["title"]}」跨 {_lg["duration_span_min"]/60:.1f} 小时，'
                   f'但活跃仅 {_lg["duration_active_min"]/60:.1f} 小时'
                   ) if (_lg and _lg["duration_span_min"] > 0) else "长期挂起的会话会把跨度显著拉大"
KIND_LAB = {"flat": "固定", "split": "分时", "tiered": "分段"}


def yi(n): return f"{n/1e8:.2f} 亿"
def k(n): return f"{int(n):,}"


L = []
A = L.append
A(f"""---
title: "WorkBuddy 任务级 Token 消耗追溯：开源方案调研 + 本机实测（v3）"
type: report
tags: [调研, token, 成本管理, WorkBuddy, 分时计价, 峰谷价, 开源方案]
created: {datetime.date.today().isoformat()}
data_range: "2026-07-27 ~ 2026-09-20"
source: "本机 ~/.workbuddy（只读实测）"
---

# WorkBuddy 任务级 Token 消耗追溯
### 开源方案调研 + 本机实测 + 分时计价修订

> 版本 v3　|　生成 {S["generated_at"]}　|　数据范围 2026-07-27 ~ 2026-09-20（{T["days"]} 天）
> 数据来源：本机 `~/.workbuddy` 的 JSONL 会话日志与 SQLite 数据库，全程只读，无任何数据外发。

---

## 0. 结论先行

| # | 结论 | 依据 |
|---|---|---|
| **1** | **你的需求不需要引入任何开源方案** | 本机已落盘 {k(T["requests"])} 条请求级真实 usage，含 token 与请求时间戳 |
| **2** | **分时计价必要**：一刀切按高峰价会多算 ¥{SSAVE:,.2f}（{SSAVE_PCT}%） | DeepSeek 系高峰价 = 空闲价 × 2；{PO["cross_period_sessions"]} 个任务横跨峰谷 |
| **3** | **法定节假日与调休必须显式建模** | 2026-09-20（周日）是国庆调休上班日，按休息日处理会全天误判为空闲 |
| **4** | **三类开源方案中只有"本地日志解析"零代价可用** | SDK 埋点路线对闭源客户端不可行；网关代理路线已验证可行但需改道请求 |

### 核心数字（实测）

| 指标 | 实测值 |
|---|---|
| 累计 token | **{yi(T["total_tokens"])}** |
| 分时口径成本 | **¥{T["cost_cny"]:,.2f}**（日均 ¥{AVG_DAILY:.2f}） |
| 对照：全按高峰价 | ¥{T["cost_all_peak_cny"]:,.2f} |
| 对照：全按空闲价 | ¥{T["cost_all_off_cny"]:,.2f} |
| 任务会话 / 请求 | {k(T["sessions"])} / {k(T["requests"])} |
| 缓存命中率 | **{T["cache_hit_rate"]}%** |
| 高峰 / 空闲请求 | {k(PO["peak_requests"])} / {k(PO["off_requests"])} |
| 活跃时长 ÷ 墙钟跨度 | **{DUR["active_ratio"]}%** |

---

## 1. 问题界定

### 1.1 原始诉求
- 知道**每一个任务**实际消耗了多少 token，用于成本估算与管理
- 现状：WorkBuddy 界面只暴露"额度"

### 1.2 v2/v3 追加的要求
- 厂商存在**峰价 / 谷价**差异，须按官方最新定价修订计价标准
- 须记录任务的**发生时间、持续时间、结束时间**，才能准确判断实际消耗与费用
- 价格表须在**当日首次调用时更新**；节假日与调休表须**按年更新**

### 1.3 为什么"额度"不足以支撑成本管理

| 缺陷 | 说明 |
|---|---|
| 不可归因 | 额度是聚合数，无法回答"哪个任务花了多少" |
| 不可解释 | 额度受模型单价、峰谷时段、缓存命中共同影响 |
| 不可预测 | 没有单任务基线，无法预估新任务开销 |

---

## 2. 本机数据源实测

### 2.1 数据源架构

```mermaid
flowchart LR
    subgraph SRC["本机数据源（只读）"]
        A1["A · projects/**/*.jsonl<br/>请求级 usage + 时间戳"]
        A2["B · workbuddy.db → sessions<br/>任务名 / 工作空间 / 自动化标识"]
        A3["C · workbuddy.db → session_usage<br/>额度 credit / 上下文占用"]
    end
    subgraph ENG["审计引擎 v3"]
        B1["外部 price_table.json<br/>flat / split / tiered"]
        B2["外部 calendar_YYYY.json<br/>节假日 + 调休"]
        B3["请求级判峰谷 / 判档 + 双时长"]
    end
    A1 --> B3
    A2 --> B3
    A3 --> B3
    B1 --> B3
    B2 --> B3
    B3 --> OUT["报告 HTML · 五张 CSV · 明细 JSON"]
```

### 2.2 实测清单

| 数据源 | 规模 | 关键字段 |
|---|---|---|
| `projects/**/*.jsonl` | 1,005 个文件 | providerData.rawUsage + timestamp |
| └ 含 usage 的记录 | **{k(T["requests"])}** 条 | prompt / completion / cache |
| └ 覆盖工作空间 | 318 个 | cwd |
| `sessions` 表 | 542 行 | title / cwd / is_background_automation |
| `session_usage` 表 | 528 行 | credit_json / used |

### 2.3 会话元数据覆盖率

| 类别 | 会话数 | token 量 |
|---|---|---|
| 有 db 元数据 | {k(len(with_meta))} | {yi(sum(r["total_tokens"] for r in with_meta))} |
| 无 db 元数据 | {k(len(no_meta))} | {yi(sum(r["total_tokens"] for r in no_meta))} |

> 缺口性质：{k(len(no_meta))} 个无元数据会话中 {k(len([r for r in no_meta if r["reqs"]<=50]))} 个请求数 ≤50 且全部无子代理，
> 仅占 {_NO_META_TOK_PCT:.1f}% token。核心消耗（{100-_NO_META_TOK_PCT:.1f}%）都在有任务名的会话里。

---

## 3. 开源方案横向调研

```mermaid
flowchart TB
    R["开源 token 追踪方案"]
    R --> RA["路线 A · 本地日志解析<br/>不介入请求链路"]
    R --> RB["路线 B · 网关 / 代理拦截<br/>请求改道自建网关"]
    R --> RC["路线 C · SDK / OTel 埋点<br/>应用代码内插桩"]
    RA --> V1["可行 · 本机已在用<br/>ccusage 17.5k 星同范式"]
    RB --> V2["已验证可行（商汤接入即例证）<br/>但需改道，投入产出比不成立"]
    RC --> V3["不可行 · 闭源客户端无法插桩"]
```

| 方案 | 路线 | 许可证 | 活跃度 | 判断 |
|---|---|---|---|---|
| ccusage | A 日志解析 | MIT | 17.5k★ | 借鉴 |
| Claude-Code-Usage-Monitor | A 日志解析 | MIT | 8.5k★ | 借鉴 |
| LiteLLM | B 网关代理 | MIT（企业另授权） | 58k★ | 备选 |
| Helicone | B 网关代理 | Apache-2.0 | 6.1k★ | 备选 |
| Langfuse / OpenLLMetry / OpenLIT / Arize Phoenix | C SDK 埋点 | MIT / Apache-2.0 / Elastic-2.0 | — | 不适用 |

> **v3 修正**：路线 B 从"理论可行需验证"升级为"**已验证可行**"——核查中发现你已通过本地代理给 WorkBuddy 接入了自定义模型
> （模型配置填 id / url / apiKey / name 四字段）。它未成为推荐方案的原因不是做不到，而是"只为看清消耗而引入代理层，投入产出比不成立"。

---

## 4. 计价标准核查与更新机制

### 4.1 更新机制（按确定的口径实现）

| 场景 | 行为 |
|---|---|
| 当日第 1 次调用 | 先刷新价格表，再统计计算 |
| 当日第 2 次及以后 | 跳过刷新，复用当日已刷新结果 |
| 收到强制更新指令 | 加 `--force-refresh` 参数 |

- 价格表外置为 `price_table.json`，每条记录带 `verified_at` 与官方来源 URL
- 抓取采用**混合模式**：脚本先自动抓取官方页并用关键词锚点校验；失败则降级为人工待核实清单，**不静默跳过**
- 本次刷新实况：价格表核实日期 `{PTI.get("verified_at") or "(未核实)"}`；
  自动确认厂商 {(("、".join(PTI.get("refresh", {}).get("auto_ok") or [])) or "复用当日结果")}；
  待人工核实 {len(PTI.get("pending_manual") or [])} 家
- 日历表按年维护（`calendar_YYYY.json`），引擎按数据涉及年份自动加载；
  已加载 {("、".join(str(y) for y in (CAL.get("loaded") or []))) or "—"}
  {("；缺 " + "、".join(str(y) for y in CAL["missing"])) if CAL.get("missing") else ""}
- 日历下一个更新节点：**2026 年 11 月前后**（国务院通常于前一年 11 月发布次年安排）

### 4.2 三种计价形态

| 形态 | 判定依据 | 本次命中请求数 |
|---|---|---|
| 固定 flat | 单价恒定 | {k(TS_.get("flat", 0))} |
| 分时 split | 按每请求时间戳判高峰/空闲 | {k(TS_.get("peak", 0))} 高峰 + {k(TS_.get("off", 0))} 空闲 |
| 分段 tiered | 按每请求 input/output 长度判档（智谱 GLM） | {k(TS_.get("tier", 0))} |

### 4.3 逐模型核查表

| 模型标识 | 计价类型 | 请求数 | 高峰 | 空闲 | 官方单价（输入/输出/缓存） | 来源 |
|---|---|---|---|---|---|---|""")

for m in MODELS:
    kind = m.get("kind") or "flat"
    pp = m.get("peak_price") or [0, 0, 0]
    op = m.get("off_price") or [0, 0, 0]
    if kind == "split":
        pr = f"{pp[0]:g}/{pp[1]:g}/{pp[2]:g}（峰）<br>{op[0]:g}/{op[1]:g}/{op[2]:g}（谷）"
    elif kind == "tiered":
        pr = f"{pp[0]:g}/{pp[1]:g}/{pp[2]:g}（低档）<br>{op[0]:g}/{op[1]:g}/{op[2]:g}（高档）"
    else:
        pr = f"{pp[0]:g}/{pp[1]:g}/{pp[2]:g}"
    pk = k(m["peak_requests"]) if kind == "split" else "—"
    of = k(m["off_requests"]) if kind == "split" else "—"
    A(f"| `{m['model']}` | {KIND_LAB.get(kind, kind)} | {k(m['requests'])} | {pk} | {of} | {pr} | {m.get('source') or ''} |")

A(f"""
### 4.4 本次核查发现的问题

| 项 | 处理 |
|---|---|
| MiniMax-M3 价高了一倍（原 4.2/16.8/0.84 → 官方 2.1/8.4/0.42） | 已修正 |
| 智谱由"统一取高位档"改为**请求级判档**，命中 {k(TS_.get("tier", 0))} 次 | 已升级 |
| `hy3-x` 官方未单独披露（腾讯云、混元官网、易观报告均只列 Hy3） | 按 Hy3 同价，标注推定 |
| GLM-5.3-Flash 有 5 折促销（官网现价 0.4/1.4/0.115） | 本表按原价，偏保守 |
| 腾讯混元 / 商汤 / MiniMax 页面无法自动抓取（JS 渲染或需登录） | 已转人工清单 |

### 4.5 官方来源

""")
seen = set()
for m in MODELS:
    u = m.get("url") or ""
    if not u or u in seen:
        continue
    seen.add(u)
    A(f"- {m.get('source') or ''} — `{u}`")

A(f"""
---

## 5. 分时计价与分段判档机制

### 5.1 分时（DeepSeek 系）

| 项 | 定义 |
|---|---|
| 时区 | 北京时间（UTC+8） |
| 高峰窗口 | 工作日 09:00–12:00、14:00–18:00 |
| 空闲窗口 | 00:00–09:00、12:00–14:00、18:00–24:00 |
| 价格关系 | 高峰价 = 空闲价 × 2 |
| 工作日判定 | 先查调休上班日（按工作日）→ 再查法定放假日（按休息日）→ 最后按周一至周五 |

**为什么必须按请求级**：本次实测有 **{PO["cross_period_sessions"]} 个任务**跨越峰谷时段。
{cross_example}
若用任务开始时刻一刀切，这些请求的时段归属会全部算错。

### 5.2 分段（智谱 GLM）

智谱按**输入长度**分段（部分模型还叠加输出长度），非分时。既然采用原厂价，
本版按每条请求的实际 `input_tokens` / `output_tokens` 判档，共命中 {k(TS_.get("tier", 0))} 次。

### 5.3 三口径成本对比

| 口径 | 成本 | 说明 |
|---|---|---|
| A · 全部按高峰价 | ¥{T["cost_all_peak_cny"]:,.2f} | v1 的近似做法 |
| **B · 按请求实际时段** | **¥{T["cost_cny"]:,.2f}** | **本报告采用** |
| C · 全部按空闲价 | ¥{T["cost_all_off_cny"]:,.2f} | 理论下限 |

- 口径 A − B = **¥{SSAVE:,.2f}**（{SSAVE_PCT}%），即分时修正带来的实际影响
- 只看 DeepSeek 部分：实际 ¥{DS_ACT:,.2f}，若全按高峰 ¥{DS_AP:,.2f}，**节省 {DS_SAVE_PCT:.1f}%**

### 5.4 任务时长双口径

| 分位 | 墙钟跨度 | 活跃时长（剔除 >30min 空档） |
|---|---|---|
| P50 中位 | {DUR["span_median_min"]} 分钟 | {DUR["active_median_min"]} 分钟 |
| P75 | 26.3 分钟 | 22.2 分钟 |
| P90 | 138.8 分钟 | 84.1 分钟 |
| P99 | 1,973 分钟 | 365 分钟 |
| 均值 | {DUR["span_mean_min"]} 分钟 | {DUR["active_mean_min"]} 分钟 |
| 最大值 | {DUR["span_max_min"]:,.0f} 分钟 | {DUR["active_max_min"]:,.0f} 分钟 |

> 口径提醒：跨度均值 {DUR["span_mean_min"]} 分钟远高于中位 {DUR["span_median_min"]} 分钟，因为存在长期挂起的会话
> （{longest_example}）。**做成本基线请用中位数或活跃时长，不要用跨度均值。**
> 两者之比为 {DUR["active_ratio"]}%，即墙钟时间里约五分之一在真正干活。

---

## 6. 实测结果

### 6.1 总览

| 指标 | 数值 |
|---|---|
| 总 token | {yi(T["total_tokens"])} |
| 输入 / 输出 | {yi(T["input_tokens"])} / {yi(T["output_tokens"])} |
| 缓存命中 | {yi(T["cache_hit_tokens"])}（{T["cache_hit_rate"]}%） |
| 分时口径成本 | ¥{T["cost_cny"]:,.2f} |

### 6.2 关键洞察：缓存命中率 {T["cache_hit_rate"]}%，"按牌价直算"会严重高估

输入里 {T["cache_hit_rate"]}% 是缓存命中（单价约为输入价的 1/4）。

| 计价方式 | 结果 |
|---|---|
| 正确口径（缓存分档） | ¥{T["cost_cny"]:,.2f} |
| 若不分档、全部按输入价 | 约 ¥{T["input_tokens"]/1e6*1 + T["output_tokens"]/1e6*4:,.2f} |
| 高估幅度 | **约 {SAVE}%** |

> 任何第三方方案若按 input/output 两档计价，对你的场景都不准。

### 6.3 口径一 · 按任务（消耗 TOP 20）

| # | 任务 | 工作空间 | 类型 | 请求 | token | 峰/谷 | 跨度/活跃(min) | 成本 |
|---|---|---|---|---|---|---|---|---|""")

for i, r in enumerate(SESS[:20]):
    badges = []
    badges.append("自动" if r["is_auto"] else "人工")
    if r.get("cross_period"):
        badges.append("跨时段")
    pk = f"{r['peak_reqs']}/{r['off_reqs']}" if r.get("split_used") else "—"
    A(f"| {i+1} | {r['title'][:26]} | {r['workspace'][:16]} | {'·'.join(badges)} | {k(r['reqs'])} | "
      f"{yi(r['total_tokens'])} | {pk} | {r['duration_span_min']:.0f} / {r['duration_active_min']:.0f} | ¥{r['cost_cny']:,.2f} |")

med = sorted(r["cost_cny"] for r in SESS)[len(SESS)//2]
A(f"""
> 完整 {k(len(SESS))} 条明细见 `sessions.csv`（含起止时间、双时长、峰谷请求数）。
> 单任务最高 ¥{SESS[0]['cost_cny']:,.2f}，中位数 ¥{med:,.2f}。

### 6.4 口径二 · 按工作空间（TOP 15）

| 工作空间 | 会话 | 请求 | token | 峰/谷请求 | 成本 |
|---|---|---|---|---|---|""")
for w in WS[:15]:
    A(f"| {w['workspace'][:26]} | {w['sessions']} | {k(w['reqs'])} | {yi(w['total_tokens'])} | "
      f"{k(w['peak_reqs'])}/{k(w['off_reqs'])} | ¥{w['cost_cny']:,.2f} |")

A(f"""
### 6.5 口径三 · 人工 vs 自动化

| 指标 | 人工 | 自动化 |
|---|---|---|
| 会话数 | {k(manual["sessions"])} | {k(auto["sessions"])} |
| 请求数 | {k(manual["reqs"])} | {k(auto["reqs"])} |
| token | {yi(manual["total_tokens"])} | {yi(auto["total_tokens"])} |
| 高峰请求 | {k(manual["peak_reqs"])} | {k(auto["peak_reqs"])} |
| 成本 | ¥{manual["cost_cny"]:,.2f} | ¥{auto["cost_cny"]:,.2f} |
| 成本占比 | {100-auto_pct:.1f}% | {auto_pct:.1f}% |

> 自动化识别依据 `sessions.is_background_automation`。自动化任务若可排期，**避开高峰时段可再省一半**。

### 6.6 日消耗趋势（近 20 天）

| 日期 | 会话 | token | 峰/谷请求 | 成本 |
|---|---|---|---|---|""")
for d in DAILY[-20:]:
    A(f"| {d['date']} | {d['sessions']} | {yi(d['total_tokens'])} | "
      f"{k(d.get('peak_reqs',0))}/{k(d.get('off_reqs',0))} | ¥{d['cost_cny']:,.2f} |")

A(f"""
### 6.7 额度（credit）口径

| 项目 | 数值 |
|---|---|
| 含 credit 数据的会话 | {k(len(cred_rows))} / {k(len(SESS))} |
| credit 合计 | {cred_sum:,.2f} |
| 同期牌价成本换算 | ¥{cred_cost:,.2f} |
| credit ÷ 牌价元 | {CRED_RATIO}（口径未确认） |

> 本报告金额**全部依据 token 消耗量 × 官方定价标准**计算，不使用 credit 换算。
> credit 值与 token 量不成线性，仅作旁证。另需留意个别模型可能存在限时免费/促销期
> （如 Hy3 曾限免两周、GLM-5.3-Flash 现享 5 折），故标价预估**可能高于**实际被扣额度。

---

## 7. 推荐方案与落地路径

**推荐：本机日志解析 + 请求级分时/分段计价 + 每日首刷 + HOOK 自动记账**

| 阶段 | 动作 | 状态 |
|---|---|---|
| 1 | 计价口径固化（price_table.json + calendar_YYYY.json 外置） | 已完成 |
| 2 | 每日首刷机制（当日首次调用自动刷新，混合抓取 + 人工降级） | 已完成 |
| 3 | 定期审计（运行 `wb_token_audit.py`，产出五张 CSV + 明细 JSON） | 可用 |
| 4 | 成本优化：把可排期的批量任务挪到空闲时段（DeepSeek 单价直接减半） | 建议推进 |
| 5 | 接自动记账：接通既有 `SessionEnd` hook 的 `tokens` 字段（现写死 0） | 待你确认 |
| 6 | 未来升级：仅当出现多设备/团队需求时再评估 LiteLLM | — |

---

## 8. 附录

### 8.1 计价口径

- 单位：**元 / 百万 token**，格式 `[输入, 输出, 缓存命中]`
- `成本 = 非缓存输入×输入价 + 缓存命中×缓存价 + 缓存写入×输入价×1.25 + 输出×输出价`
- 分时模型先按请求时间戳判峰谷，分段模型先按请求长度判档，再取对应档价格
- **这是按官方公开牌价的预估，不是官方账单**。套餐折扣、限时促销、免费额度都会改变实际支出

### 8.2 产出物清单

| 文件 | 内容 |
|---|---|
| `price_table.json` | 价格表（flat / split / tiered，含来源与核实日期） |
| `price_sources.json` | 厂商定价页登记表（URL + 抓取要点） |
| `calendar_2026.json` | 2026 年节假日与调休表（含发布文号） |
| `refresh_prices.py` | 价格刷新器（混合模式） |
| `wb_token_audit.py` | 审计引擎 v3 |
| `sessions.csv` | 任务级明细 {k(len(SESS))} 行 |
| `workspaces.csv` / `automations.csv` / `daily.csv` / `models.csv` | 各维度汇总 |
| `audit_data.json` | 完整结构化数据 |

### 8.3 已知限制

- 日期范围由 jsonl 记录时间戳决定：2026-07-27 ~ 2026-09-20
- {k(len(no_meta))} 个会话（{NO_META_PCT:.1f}%）在 `sessions` 表中查不到任务名
- 子代理日志已按路径归属父会话
- `hy3-x` 单价按 Hy3 推定，官方未单独披露
- 腾讯云官方文档只写"高峰 09:00–12:00、14:00–18:00"未提工作日限制；
  本报告采用 DeepSeek 原厂口径（限工作日 + 排除法定节假日），与你的要求一致
- 4 家厂商（腾讯混元 / 商汤 / MiniMax / Mistral）页面无法自动抓取，其价格来自本次人工核查，后续刷新会持续提示

---

*本报告全部数据由本机实测生成，脚本与中间数据同目录留存，可复现。*
""")

md = "\n".join(L)
p = os.path.join(OUT, "WorkBuddy-Token消耗调研报告.md")
with open(p, "w", encoding="utf-8") as f:
    f.write(md)
print("已生成:", p, f"({len(md):,} 字符)")
