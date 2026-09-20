# 数据源与字段说明

本工具全部数据来自**本机只读**文件，不发起任何上传。

## 一、数据源总览

| 编号 | 位置 | 提供什么 | 覆盖率 |
|---|---|---|---|
| A | `~/.workbuddy/projects/**/*.jsonl` | 请求级真实用量 + 请求时间戳 | 每条 API 调用一条记录 |
| B | `~/.workbuddy/workbuddy.db` → `sessions` | 任务名 / 工作空间 / 是否自动化 | 542 行（本机实测） |
| C | `~/.workbuddy/workbuddy.db` → `session_usage` | 额度明细 / 上下文占用 | 528 行（本机实测） |

## 二、数据源 A：请求级用量（主数据）

### 路径结构

```
~/.workbuddy/projects/
├── <workspace-slug>/                    e.g. c-Users-foo-WorkBuddy-2026-08-01-10-00-00
│   ├── <session-uuid>.jsonl             一个会话一个文件
│   └── <session-uuid>/
│       └── subagents/
│           └── agent-<hash>.jsonl       子代理日志，归属父会话
```

**子代理归属规则**：路径中出现 `subagents` 时，其上一级目录名即父会话 ID。

### 关键字段

每行一个 JSON 对象。取用量时定位 `providerData`：

```json
{
  "timestamp": 1789660845089,
  "sessionId": "...",
  "cwd": "<工作目录>\\WorkBuddy\\2026-08-25-12-11-37",
  "role": "user",
  "providerData": {
    "model": "hy3-x",
    "rawUsage": {
      "prompt_tokens": 52902,
      "completion_tokens": 212,
      "total_tokens": 53114,
      "prompt_cache_hit_tokens": 0,
      "prompt_tokens_details": { "cached_tokens": 0 },
      "completion_tokens_details": { "reasoning_tokens": 130 }
    }
  }
}
```

| 字段 | 含义 |
|---|---|
| `timestamp` | 毫秒级时间戳 —— **分时判定的依据** |
| `providerData.model` | 模型标识（决定用哪套价） |
| `rawUsage.prompt_tokens` | 输入 token（**含**缓存命中部分） |
| `rawUsage.completion_tokens` | 输出 token |
| `rawUsage.prompt_cache_hit_tokens` | 缓存命中 token（DeepSeek 风格顶层字段） |
| `prompt_tokens_details.cached_tokens` | 缓存命中（OpenAI 风格嵌套字段，作兜底） |
| `completion_tokens_details.reasoning_tokens` | 思考 token（已计入 completion） |

> **兼容性处理**：不同厂商字段风格不同（DeepSeek 顶层 vs OpenAI 嵌套），
> 解析时先取 `prompt_cache_hit_tokens`，为空再取 `prompt_tokens_details.cached_tokens`。

### 会话标题提取

取该 JSONL 中**第一条非内部标签的用户消息**前 42 字作为任务标题。
以 `<` 开头的消息（如 `<system-reminder>`）视为内部注入，跳过。

## 三、数据源 B：任务元数据

表 `sessions` 的关键列：

| 列 | 说明 |
|---|---|
| `id` | 会话 ID，与 JSONL 的 `sessionId` 关联 |
| `title` / `custom_title` | 任务名；`custom_title` 优先 |
| `cwd` | 工作空间路径，决定归属哪个工作空间 |
| `model` | 会话默认模型 |
| **`is_background_automation`** | **直接区分人工 / 自动化，非推断** |
| `status` | 会话状态 |

## 四、数据源 C：额度与上下文

表 `session_usage` 的关键列：

| 列 | 说明 |
|---|---|
| `used` / `size` | 上下文窗口占用 / 上限 |
| `credit_json` | 额度消耗明细（key 为哈希） |

> **重要提醒**：`credit` 值与 token 量**不成线性关系**（实测 3.28 亿 token 对应 884 credit，
> 而 2.85 亿 token 只对应 259 credit）。因此本工具**不使用 credit 换算金额**，
> 仅作为旁证输出；金额一律按 token × 官方定价计算。

## 五、读取注意事项（踩过的坑）

1. **必须连同 WAL 一起复制**
   `workbuddy.db` 有 `-wal`、`-shm` 伴生文件。只读直连会**漏掉未 checkpoint 的数据**。
   正确做法：把三个文件一起复制到临时目录，再连接副本。

2. **不要用 mtime 判断新鲜度**
   会话目录可能被归档/移动，mtime 会失真。内容比对一律用 hash。

3. **中文路径 + 空格**
   Windows 下 `C:\Users\<含空格与单引号的用户名>\...` 需要全程加引号；
   脚本内部一律用 `os.path` / `pathlib` 拼接，不用字符串相加。

4. **控制台编码**
   Windows 控制台默认 GBK，输出中文可能报错。脚本已内置 UTF-8 输出保护。

5. **不要用 shell 遍历文件树**
   日志目录可能含特殊字符文件名，一律用 Python 的 `os.walk` / `glob`，不用 `for f in $(find ...)`。

## 六、覆盖率与已知缺口

两个数据源互补：

- JSONL 有 token 但**没有任务名**
- `sessions` 表有任务名但**没有 token**

实测约有一半会话在 `sessions` 表中查不到元数据。但这些缺口会话**绝大多数是短会话**
（请求数 ≤ 50 且不含子代理），token 占比仅约 10%。
核心消耗集中在有任务名的会话里。

## 七、隐私

- 报告与 CSV **包含真实任务名、工作空间名、时间戳** —— 这些是敏感信息
- `.gitignore` 已排除全部产出目录
- 公开分享报告前请自行脱敏，或仅分享聚合数字
