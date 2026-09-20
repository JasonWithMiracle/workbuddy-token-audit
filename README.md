# workbuddy-token-audit

**Per-task token & cost auditing for WorkBuddy** · WorkBuddy 任务级 Token 消耗审计

`v1.0.0` · MIT · 纯 Python 标准库，零依赖

WorkBuddy's UI only surfaces a single aggregate "credit" number — it can't tell you which task cost what.
This tool reads WorkBuddy's **local request-level usage logs** (real API-reported values, not estimates),
applies official vendor pricing **with peak/off-peak and tiered rates plus cache-tier accounting**,
and produces per-task / per-workspace / per-automation cost breakdowns as HTML + Markdown reports and CSV.

Pure Python standard library. Zero dependencies. Nothing leaves your machine.

---

## 为什么需要它

WorkBuddy 界面只暴露「额度」这一聚合指标。它无法回答：

- **不可归因** —— 哪个任务花了多少？
- **不可解释** —— 额度受模型单价、峰谷时段、缓存命中共同影响，与 token 量非线性
- **不可预测** —— 没有单任务基线，无法预估新任务开销

但本机日志里其实有完整账本。这个工具把它读出来、算清楚。

## 核心能力

| 能力 | 说明 |
|---|---|
| **请求级真实用量** | 读 `providerData.rawUsage`，非估算；含 prompt / completion / cache_hit / reasoning |
| **分时计价** | DeepSeek 系高峰价 = 空闲价 × 2；按**每条请求的时间戳**判峰谷，支持横跨时段的任务 |
| **分段计价** | 智谱 GLM 按输入长度分段（部分模型叠加输出长度档），按每条请求实际长度判档 |
| **缓存分档** | 缓存命中价常为输入价的 1/4 乃至 1/20；不分档会把成本高估约 70% |
| **节假日与调休** | 按年维护，**调休上班日按工作日**处理（如 2026-09-20 这个周日） |
| **三口径聚合** | 按任务 / 工作空间 / 自动化（人工 vs 定时任务） |
| **双时长口径** | 墙钟跨度 + 活跃时长（剔除长空档） |
| **价格表当日首刷** | 当日首次调用自动刷新，后续复用；混合抓取（自动 + 失败降级人工） |

## 快速开始

```bash
git clone <this-repo> ~/.workbuddy/skills/workbuddy-token-audit
cd ~/.workbuddy/skills/workbuddy-token-audit

# 1) 审计：扫描日志 → 逐请求判价 → 聚合 → 输出数据表
python scripts/wb_token_audit.py --out ./out

# 2) 出报告（须在审计之后运行）
python scripts/gen_report.py   --data ./out/audit_data.json
python scripts/gen_markdown.py --data ./out/audit_data.json
```

产出：

```
out/
├── WorkBuddy-Token消耗调研报告.html   单文件离线报告（深浅色可切换）
├── WorkBuddy-Token消耗调研报告.md     同内容 Markdown（含 Mermaid）
├── sessions.csv                       任务级明细（含起止时间 / 双时长 / 峰谷请求数）
├── workspaces.csv                     工作空间汇总（含三口径成本）
├── automations.csv                    自动化会话明细
├── daily.csv                          日粒度汇总（含峰谷拆分）
├── models.csv                         模型计价核查表
└── audit_data.json                    完整结构化数据（供二次分析）
```

### 交互式看板

```bash
python scripts/gen_dashboard.py --out ./dashboard.html
```

单文件自包含看板：KPI / 日活热力图 / 0–24 时模型分布 / 每日模型占比 / 工作空间-会话-请求三级下钻。

### 任务内环节预估（plan 模式）

```bash
python scripts/consumption_logger.py init --task-name "任务名" --workdir ./plan
python scripts/consumption_logger.py log --phase "1.初始化" --model hy3 \
       --input-tokens 1200 --output-tokens 800 --workdir ./plan
python scripts/estimate_report.py --workdir ./plan
```

> 该模式的 token 数由 Agent **估算**，用于事前规划；要精确值请用 audit 模式。

## 常用参数

```bash
--out <dir>        产出目录（默认 <cwd>/token-audit-output）
--projects <dir>   WorkBuddy 日志目录（默认 ~/.workbuddy/projects）
--db <path>        workbuddy.db 路径（默认 ~/.workbuddy/workbuddy.db）
--force-refresh    强制刷新价格表
--no-refresh       跳过价格表新鲜度检查（离线）
--anonymize        报告脱敏：任务名与工作空间名哈希化，便于公开分享
```

> 看板模式需先用 `--requests` 指向审计产出的 `requests.jsonl`（与 audit 共用同一份数据，不重复解析日志）。

## 开发与测试

```bash
python -m unittest discover -s tests -v     # 46 个单元测试
python scripts/check_privacy.py             # 提交前敏感信息扫描
python scripts/verify_cost.py --data <产出目录>   # 独立实现复算，交叉验证计价
python examples/make_sample.py              # 重新生成脱敏示例
```

三层质量保障：

1. **单元测试**覆盖价格匹配、峰谷判定（含调休日）、分段判档、缓存分档、数据契约
2. **独立复算校验器**用与引擎不同的实现重算全部请求，两者必须一致
3. **敏感扫描**防止把本机路径或产出数据带进版本库

CI 在 Ubuntu / Windows / macOS × Python 3.8 / 3.11 / 3.13 上跑上述检查。

## 计价口径

单位：**元 / 百万 token**，格式 `[输入, 输出, 缓存命中]`。

```
成本 = 非缓存输入×输入价 + 缓存命中×缓存价 + 缓存写入×输入价×1.25 + 输出×输出价
```

- **分时**：DeepSeek 系，高峰 = 空闲 × 2；高峰窗口为北京时间**工作日** 09:00–12:00、14:00–18:00
- **分段**：智谱 GLM，按输入长度（部分叠加输出长度）判档
- **日历**：法定放假日全天不计高峰；**调休上班日按工作日**处理

详见 [`references/PRICING.md`](references/PRICING.md) 与 [`references/DATA_SOURCES.md`](references/DATA_SOURCES.md)。

### 自定义价格

价格表是**外部数据**，不是硬编码：

1. 编辑 `assets/price_sources.json`（各厂商官方定价页登记表），再 `python scripts/refresh_prices.py --force`
2. 或直接改 `assets/price_table.template.json` 并提交

`assets/price_table.json` 是运行时实例（不入库）。缺某年日历会显式告警，补 `assets/calendar_YYYY.json` 即可。

## 数据与隐私

- **只读**本机 `~/.workbuddy`，**不发起任何上传**
- 报告与 CSV **包含真实任务名与工作空间名** —— 公开分享前请先脱敏
- `.gitignore` 已排除所有产出目录、`price_table.json`、`price_refresh_log.json`

## 免责声明

- 本工具为**非官方工具**，与腾讯 / WorkBuddy **无任何关联**，未获其授权或背书
- 它仅解析**用户本机自有**的客户端数据文件；数据格式非公开，若官方调整格式，本工具可能失效
- 成本数字为**按官方公开牌价的预估**，不是官方账单；套餐折扣、限时促销、免费额度都会造成偏差
- 若官方对本工具提出异议，我们将配合调整或下架

## 环境要求

- Python 3.8+（仅标准库）
- Windows / macOS / Linux
- 本机需使用过 WorkBuddy（存在 `~/.workbuddy/projects`）

## 许可

[MIT](LICENSE)
