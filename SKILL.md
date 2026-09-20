---
name: workbuddy-token-audit
version: "1.0.0"
description: 统计 WorkBuddy 的任务级 Token 消耗与成本。三种模式——audit（审计实测消耗，出 HTML/Markdown 报告与 CSV）、dashboard（交互式单文件看板）、plan（任务内环节消耗预估）。支持分时计价（峰谷价）、分段计价（智谱 GLM）与缓存分档，价格表按调用当日自动刷新，节假日与调休按年维护。当用户问「我的 token 消耗」「花了多少钱」「成本审计」「token 用量看板」「这个任务大概花多少」「用量统计」时使用。
---

# WorkBuddy Token 消耗审计

解析本机 `~/.workbuddy` 的**请求级真实 usage**，结合官方定价与节假日日历，给出可归因、可解释、可预测的成本数据。

## 为什么需要它

WorkBuddy 界面只暴露「额度」这一聚合指标，无法回答「哪个任务花了多少」。而本机日志里其实有完整账本：

| 数据源 | 位置 | 内容 |
|---|---|---|
| 请求级用量 | `~/.workbuddy/projects/**/*.jsonl` | `providerData.rawUsage`（含请求时间戳） |
| 任务元数据 | `~/.workbuddy/workbuddy.db` → `sessions` | 任务名 / 工作空间 / `is_background_automation` |
| 额度明细 | `~/.workbuddy/workbuddy.db` → `session_usage` | `credit_json` / 上下文占用 |

> 读 `workbuddy.db` 必须先连 `-wal`、`-shm` 一起复制到临时目录，只读直连会漏 WAL 数据。

## 三种模式

| 模式 | 回答的问题 | 数据来源 | 主脚本 |
|---|---|---|---|
| **audit** | 已经花了多少、花在哪 | 日志实测 | `wb_token_audit.py` → `gen_report.py` / `gen_markdown.py` |
| **dashboard** | 想看交互式明细与分布 | 日志实测 | `gen_dashboard.py` |
| **plan** | 这个任务大概要花多少 | Agent 估算 | `consumption_logger.py` → `estimate_report.py` |

三种模式**共享同一份价格表** `assets/price_table.json`，不会出现两套价目。

## 执行步骤

### 前置：价格表当日首刷（audit / dashboard 会自动触发）

- **当日第 1 次调用** → 自动刷新价格表，再统计
- **当日第 2 次及以后** → 跳过刷新，复用当日结果
- **强制刷新** → 加 `--force-refresh`
- **离线** → 加 `--no-refresh`

刷新采用**混合模式**：脚本自动抓取官方定价页 + 关键词锚点校验；失败则写入 `pending_manual` 转人工，**不静默跳过**。

### 模式一：audit（最常用）

```bash
# 1) 审计：扫描 → 逐请求判价 → 三口径聚合 → 输出 CSV/JSON
python <skill>/scripts/wb_token_audit.py --out ./token-audit-output

# 2) 报告（两步必须按顺序，第二步读第一步的 audit_data.json）
python <skill>/scripts/gen_report.py   --data ./token-audit-output/audit_data.json
python <skill>/scripts/gen_markdown.py --data ./token-audit-output/audit_data.json
```

产出：报告 HTML + Markdown、`sessions.csv`、`workspaces.csv`、`automations.csv`、`daily.csv`、`models.csv`、`audit_data.json`。

常用参数：`--projects`（自定义日志目录）、`--db`（自定义数据库路径）、`--out`（产出目录，默认 `<cwd>/token-audit-output`）。

### 模式二：dashboard

```bash
python <skill>/scripts/gen_dashboard.py --out ./dashboard.html
```

生成单文件自包含看板（KPI / 日活热力图 / 0–24 时模型分布 / 每日模型占比 / 工作空间-会话-请求三级下钻 / 深浅色）。

### 模式三：plan（任务内环节预估）

```bash
python <skill>/scripts/consumption_logger.py init --task-name "任务名" --workdir <dir>
python <skill>/scripts/consumption_logger.py log --phase "1.初始化" --model hy3 \
       --input-tokens 1200 --output-tokens 800 --workdir <dir>
python <skill>/scripts/consumption_logger.py list --workdir <dir>
python <skill>/scripts/estimate_report.py --workdir <dir>     # 出报告
```

> plan 模式的 token 数由 Agent **估算**（约 1 token ≈ 4 英文字符 / 1.5 中文字），
> 报告页脚会统一提示。**要精确值请用 audit 模式。**

## 计价口径（三条，都会显著影响结果）

1. **分时（峰谷）**：DeepSeek 系高峰价 = 空闲价 × 2。高峰为北京时间**工作日** 09:00–12:00、14:00–18:00；
   判定**按每条请求的时间戳**，而非任务开始时刻 —— 实测常有任务横跨峰谷。
2. **分段**：智谱 GLM 按**输入长度**分段（部分模型还叠加输出长度档），按每条请求实际长度判档。
3. **缓存分档**：缓存命中价通常只有输入价的 1/4 甚至 1/20。若不区分缓存、全部按输入价计，
   成本会被高估（本机实测高估约 70%）。

节假日与调休表按年维护（`assets/calendar_YYYY.json`），**调休上班日按工作日处理**。
更新节点为国务院发布日（通常前一年 11 月）。

## 自定义价格

- 改价格优先编辑 `assets/price_sources.json`（登记各厂商官方定价页），再运行 `refresh_prices.py --force`
- 也可直接改 `assets/price_table.template.json` 并提交
- 自己用：改 `assets/price_table.json`（该文件是实例，不入库）

## 关于本项目（Vibe Coding 声明）

**本项目是 Vibe Coding 的产物** —— 代码主要由 AI 助手生成，人工负责需求定义、计价口径决策、
方案拍板与结果验收，**未做逐行代码审查**。

已有质量保障：46 个单元测试、独立实现复算校验（`verify_cost.py`）、三平台 CI、提交前敏感扫描。
但这些不等于「无缺陷」：**异常处理、边界条件与跨平台细节请自行评估**，
用于关键决策前建议先读 `scripts/pricing_core.py`（核心计价逻辑，约 120 行）。

本项目按 MIT 许可证「按原样」提供，**不附带任何担保**。完整声明见仓库 README「关于本项目」章节。

## 注意事项

- 仅解析**本机自有数据**，不发起任何上传
- 报告与 CSV 含真实任务名与工作空间名，**公开分享前请先脱敏**
- 详细口径见 `references/PRICING.md`，数据源与字段见 `references/DATA_SOURCES.md`

## 边界与检查点

- 若日志目录不存在（本机未用过 WorkBuddy），脚本会明确报错退出，不静默产出空报告
- 某厂商定价页抓取失败时，会输出待人工核实清单，不假装成功
- 缺某年 `calendar_YYYY.json` 时，该年的调休与法定假日无法识别，会显式告警
- 外部写操作（覆盖报告、写入价格表）均在用户指定目录内，不触碰其他路径
