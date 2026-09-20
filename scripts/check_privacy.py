# -*- coding: utf-8 -*-
"""
提交前敏感扫描（Privacy / Leak Check）
=========================================================
开源前跑一遍，避免把本机私密内容带进版本库。

检测项：
  1. 本机绝对路径泄露（用户名、盘符、临时目录）
  2. 产出数据误入库（audit_data.json / *.csv / requests.jsonl / *_report.html）
  3. 价格表实例与刷新日志（price_table.json / price_refresh_log.json）
  4. 疑似真实任务名/项目代号（可自定义词表）
  5. .gitignore 是否覆盖上述产物
  6. 大文件告警（> 1MB）

用法：
    python scripts/check_privacy.py                 # 扫描 skill 根目录
    python scripts/check_privacy.py --root <目录>
    python scripts/check_privacy.py --extra-words 词1,词2
退出码：0=未发现问题；1=发现问题
"""
import os, sys, io, re, argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(SCRIPT_DIR)

_ap = argparse.ArgumentParser(description="提交前敏感扫描")
_ap.add_argument("--root", default=DEFAULT_ROOT, help="扫描根目录（默认 skill 根）")
_ap.add_argument("--extra-words", default="", help="额外敏感词，逗号分隔")
_ap.add_argument("--max-mb", type=float, default=1.0, help="大文件阈值（MB）")
_args = _ap.parse_args()

ROOT = os.path.abspath(_args.root)
SCAN_EXT = {".py", ".md", ".json", ".jsonl", ".csv", ".html", ".htm", ".txt", ".yml", ".yaml", ".cfg", ".ini", ".sh", ".ps1", ".bat", ".toml"}
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", "dist", "build"}

# 必须入库的例外（模板、登记表、脱敏示例）
ALLOW_FILES = {"price_table.template.json", "price_sources.json"}
ALLOW_PATTERNS = (r"^calendar_\d{4}\.json$",)
ALLOW_PREFIXES = ("examples/sample_report/", "examples\\sample_report\\")

# 负向断言 (?<![A-Za-z0-9]) 用于排除 https:// 这类协议前缀（否则 "ps://" 会被当成盘符）
PATH_PATTERNS = [
    (r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]Users[\\/][^\\/\s\"']+", "Windows 用户目录绝对路径"),
    (r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]{1,2}(?!Users)[^\\/\s\"'<>]{3,}", "疑似本机盘符路径"),
    (r"(?<![A-Za-z0-9])/Users/[A-Za-z0-9._-]+/", "macOS 用户目录绝对路径"),
    (r"(?<![A-Za-z0-9])/home/[A-Za-z0-9._-]+/", "Linux 用户目录绝对路径"),
]

DATA_PATTERNS = [
    ("audit_data.json", "审计明细数据"),
    ("requests.jsonl", "逐请求明细"),
    ("sessions.csv", "任务级明细（含任务名）"),
    ("workspaces.csv", "工作空间明细"),
    ("summary.json", "审计汇总"),
    ("price_refresh_log.json", "价格刷新日志（含抓取记录）"),
    ("report.html", "报告产物"),
]

words = [w.strip() for w in (_args.extra_words or "").split(",") if w.strip()]

issues = []
warns = []


def is_allowed(name):
    if name in ALLOW_FILES or name in ("price_table.json",):
        return name in ALLOW_FILES
    for p in ALLOW_PATTERNS:
        if re.match(p, name):
            return True
    return False


print("=" * 62)
print("提交前敏感扫描")
print("=" * 62)
print("扫描根目录: %s" % ROOT)
print()

scanned = 0
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for fn in filenames:
        fp = os.path.join(dirpath, fn)
        rel = os.path.relpath(fp, ROOT).replace("\\", "/")

        # 脱敏示例是**故意入库**的：跳过（其内容已由 make_sample.py 保证为虚构数据）
        if rel.startswith("examples/sample_report/"):
            continue
        # 模板与登记表是应当入库的
        if is_allowed(fn):
            continue

        ext = os.path.splitext(fn)[1].lower()

        # 大文件
        try:
            size = os.path.getsize(fp)
        except Exception:
            continue
        if size > _args.max_mb * 1024 * 1024:
            warns.append("大文件 %.2fMB: %s" % (size / 1024 / 1024, rel))

        # 产出数据误入库
        for pat, label in DATA_PATTERNS:
            if fn.endswith(pat) or rel.endswith(pat):
                if not is_allowed(fn):
                    issues.append("产出数据疑似入库：%s（%s）" % (rel, label))

        if ext not in SCAN_EXT:
            continue
        scanned += 1
        try:
            with open(fp, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except Exception:
            continue

        # 绝对路径
        for pat, label in PATH_PATTERNS:
            for m in re.finditer(pat, text):
                frag = m.group(0)
                # 允许文档中的占位写法（如 ~/.workbuddy 或 <用户>）
                if "<" in frag or frag.startswith("~"):
                    continue
                issues.append("疑似本机路径（%s）：%s  →  %s" % (label, rel, frag[:70]))

        # 自定义敏感词
        for w in words:
            if w and w in text:
                issues.append("命中敏感词「%s」：%s" % (w, rel))

# .gitignore 覆盖检查
gi = os.path.join(ROOT, ".gitignore")
if os.path.exists(gi):
    with open(gi, encoding="utf-8", errors="replace") as fh:
        gi_text = fh.read()
    need = ["token-audit-output", "price_table.json", "price_refresh_log.json", "__pycache__"]
    for n in need:
        if n not in gi_text:
            warns.append(".gitignore 未覆盖：%s" % n)
    print("[OK] 检测到 .gitignore")
else:
    issues.append("缺少 .gitignore")

print("已扫描文本文件: %s 个" % f"{scanned:,}")
print()

if issues:
    print("-" * 62)
    print("发现问题（%d）" % len(issues))
    print("-" * 62)
    seen = set()
    for it in issues:
        if it in seen:
            continue
        seen.add(it)
        print("  [X] " + it)
    print()

if warns:
    print("-" * 62)
    print("提示（%d）" % len(warns))
    print("-" * 62)
    for w in warns:
        print("  [!] " + w)
    print()

print("=" * 62)
if issues:
    print("结论：存在 %d 个问题，请先处理再提交" % len(set(issues)))
    sys.exit(1)
print("结论：未发现敏感信息泄露风险" + ("（有 %d 条提示）" % len(warns) if warns else ""))
sys.exit(0)
