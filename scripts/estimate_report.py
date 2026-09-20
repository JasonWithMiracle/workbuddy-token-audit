#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report_generator.py — 生成「随任务进度变化」的 token 与额度消耗报告。

输入：<workdir>/consumption_log.json + price_table.json
输出：HTML 报告（含 SVG 图表 + 文字分析），默认 <workdir>/token_consumption_report.html

覆盖需求
--------
* 需求 1：折扣前/后 token 与额度均展示（计费口径对照）。
* 需求 2：按模型分别统计（per-model 表 + 柱状图）。
* 需求 4：图表（SVG 折线/柱状）+ 文字（摘要、折扣分析、规划建议）共同呈现。
* 报告中的折线图以「累计额度」随环节推进展开，直观体现消耗随任务进度变化。

仅使用标准库；SVG 图表内联、无外部依赖，可离线打开。
"""

import argparse
import datetime
import html
import json
import os
import sys

LOG_FILE = "consumption_log.json"
PRICE_FILE = "price_table.json"


def _default_workdir():
    return os.path.join(os.getcwd(), ".workbuddy", "token-tracker")


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fmt(x, digits=4):
    try:
        return f"{float(x):,.{digits}f}"
    except (TypeError, ValueError):
        return str(x)


def aggregate(log, table):
    phases = log.get("phases", [])
    currency = log.get("currency", "CNY")
    # 累计（按环节顺序）
    cum_pre, cum_post = 0.0, 0.0
    timeline = []
    for p in phases:
        cum_pre += p.get("quota_pre", 0.0)
        cum_post += p.get("quota_post", 0.0)
        timeline.append({
            "label": p.get("phase", ""),
            "pre": cum_pre,
            "post": cum_post,
            "model": p.get("model", ""),
            "state": p.get("discount_state", "none"),
        })
    # 按模型聚合
    models = {}
    for p in phases:
        m = p.get("model", "unknown")
        d = models.setdefault(m, {
            "model": m,
            "phases": 0,
            "physical_tokens": 0,
            "billing_pre": 0.0,
            "billing_post": 0.0,
            "quota_pre": 0.0,
            "quota_post": 0.0,
            "states": set(),
        })
        d["phases"] += 1
        d["physical_tokens"] += p.get("physical_tokens", 0)
        d["billing_pre"] += p.get("billing_input_pre", 0) + p.get("billing_output_pre", 0)
        d["billing_post"] += p.get("billing_input_post", 0) + p.get("billing_output_post", 0)
        d["quota_pre"] += p.get("quota_pre", 0.0)
        d["quota_post"] += p.get("quota_post", 0.0)
        d["states"].add(p.get("discount_state", "none"))
    for d in models.values():
        d["states"] = sorted(d["states"])

    total_pre = sum(p.get("quota_pre", 0) for p in phases)
    total_post = sum(p.get("quota_post", 0) for p in phases)
    total_physical = sum(p.get("physical_tokens", 0) for p in phases)
    savings = total_pre - total_post
    savings_pct = (savings / total_pre * 100.0) if total_pre > 0 else 0.0

    return {
        "currency": currency,
        "timeline": timeline,
        "models": list(models.values()),
        "total_pre": total_pre,
        "total_post": total_post,
        "total_physical": total_physical,
        "savings": savings,
        "savings_pct": savings_pct,
        "n_phases": len(phases),
    }


# ---------------------------------------------------------------------------
# SVG 图表（纯标准库生成，无依赖）
# ---------------------------------------------------------------------------

def svg_line_chart(timeline, currency, width=780, height=360):
    if not timeline:
        return "<p>暂无数据</p>"
    left, right, top, bottom = 64, 24, 28, 70
    plot_w = width - left - right
    plot_h = height - top - bottom
    n = len(timeline)
    pre_vals = [t["pre"] for t in timeline]
    post_vals = [t["post"] for t in timeline]
    ymax = max(pre_vals) if max(pre_vals) > 0 else 1.0
    ymax *= 1.15

    def xpos(i):
        return left + (plot_w * i / (n - 1)) if n > 1 else left + plot_w / 2

    def ypos(v):
        return top + plot_h * (1 - v / ymax)

    # 网格 + y 轴标签
    grid = []
    yticks = 5
    for k in range(yticks + 1):
        v = ymax * k / yticks
        y = ypos(v)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" stroke="#e5e7eb" stroke-width="1"/>')
        grid.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" fill="#6b7280">{v:,.2f}</text>')
    # x 轴标签（P1..Pn）+ 旋转
    xlabels = []
    for i, t in enumerate(timeline):
        x = xpos(i)
        xlabels.append(f'<text x="{x:.1f}" y="{top+plot_h+18:.1f}" text-anchor="end" font-size="11" fill="#374151" transform="rotate(-40 {x:.1f} {top+plot_h+18:.1f})">P{i+1}</text>')

    def poly(vals, color, dash):
        pts = " ".join(f"{xpos(i):.1f},{ypos(v):.1f}" for i, v in enumerate(vals))
        d = f' stroke-dasharray="{dash}"' if dash else ""
        return (f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.5"{d}/>'
                + "".join(f'<circle cx="{xpos(i):.1f}" cy="{ypos(v):.1f}" r="3" fill="{color}"/>' for i, v in enumerate(vals)))

    legend = (
        f'<rect x="{left}" y="6" width="14" height="3" fill="#2563eb"/>'
        f'<text x="{left+20}" y="11" font-size="11" fill="#374151">折扣前累计额度</text>'
        f'<rect x="{left+140}" y="6" width="14" height="3" fill="#16a34a" stroke="#16a34a" stroke-dasharray="4"/>'
        f'<text x="{left+160}" y="11" font-size="11" fill="#374151">折扣后累计额度</text>'
    )
    svg = (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">'
        f'{legend}{"".join(grid)}'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="#9ca3af" stroke-width="1.5"/>'
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#9ca3af" stroke-width="1.5"/>'
        f'{poly(pre_vals, "#2563eb", "")}'
        f'{poly(post_vals, "#16a34a", "5,4")}'
        f'{"".join(xlabels)}'
        f'<text x="{left+plot_w/2:.1f}" y="{height-6}" text-anchor="middle" font-size="12" fill="#374151">任务环节（P1→Pn，按时间顺序）</text>'
        f'<text x="16" y="{top+plot_h/2:.1f}" text-anchor="middle" font-size="12" fill="#374151" transform="rotate(-90 16 {top+plot_h/2:.1f})">累计额度（{currency}）</text>'
        f'</svg>'
    )
    return svg


def svg_bar_chart(models, currency, width=780, height=360):
    if not models:
        return "<p>暂无数据</p>"
    left, right, top, bottom = 64, 24, 28, 90
    plot_w = width - left - right
    plot_h = height - top - bottom
    items = sorted(models, key=lambda d: d["quota_post"], reverse=True)
    vmax = max(d["quota_post"] for d in items) if max(d["quota_post"] for d in items) > 0 else 1.0
    vmax *= 1.18
    n = len(items)
    bw = plot_w / n * 0.55
    gap = plot_w / n

    def ypos(v):
        return top + plot_h * (1 - v / vmax)

    bars = []
    for i, d in enumerate(items):
        x = left + gap * i + (gap - bw) / 2
        y = ypos(d["quota_post"])
        h = top + plot_h - y
        label = d["model"]
        short = label if len(label) <= 14 else label[:13] + "…"
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" fill="#2563eb" rx="3"/>'
            f'<text x="{x+bw/2:.1f}" y="{y-6:.1f}" text-anchor="middle" font-size="11" fill="#111827">{d["quota_post"]:,.2f}</text>'
            f'<text x="{x+bw/2:.1f}" y="{top+plot_h+16:.1f}" text-anchor="end" font-size="10.5" fill="#374151" transform="rotate(-35 {x+bw/2:.1f} {top+plot_h+16:.1f})">{html.escape(short)}</text>'
        )
    grid = []
    for k in range(6):
        v = vmax * k / 5
        y = ypos(v)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        grid.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" fill="#6b7280">{v:,.1f}</text>')
    svg = (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">'
        f'{"".join(grid)}'
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#9ca3af" stroke-width="1.5"/>'
        f'{"".join(bars)}'
        f'<text x="{left+plot_w/2:.1f}" y="{height-8}" text-anchor="middle" font-size="12" fill="#374151">模型</text>'
        f'<text x="16" y="{top+plot_h/2:.1f}" text-anchor="middle" font-size="12" fill="#374151" transform="rotate(-90 16 {top+plot_h/2:.1f})">折扣后额度（{currency}）</text>'
        f'</svg>'
    )
    return svg


# ---------------------------------------------------------------------------
# HTML 报告
# ---------------------------------------------------------------------------

CSS = """
<style>
  :root{--blue:#2563eb;--green:#16a34a;--ink:#111827;--muted:#6b7280;--line:#e5e7eb;--bg:#f8fafc;}
  *{box-sizing:border-box;}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6;}
  .wrap{max-width:960px;margin:0 auto;padding:32px 24px 64px;}
  header{border-bottom:3px solid var(--blue);padding-bottom:14px;margin-bottom:24px;}
  h1{font-size:26px;margin:0 0 6px;}
  h2{font-size:19px;margin:34px 0 12px;border-left:4px solid var(--blue);padding-left:10px;}
  .sub{color:var(--muted);font-size:14px;}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:18px 0;}
  .card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px;}
  .card .k{font-size:13px;color:var(--muted);}
  .card .v{font-size:22px;font-weight:700;margin-top:4px;}
  .card .v.green{color:var(--green);}
  .card .v.blue{color:var(--blue);}
  table{width:100%;border-collapse:collapse;background:#fff;font-size:13.5px;margin:10px 0;}
  th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;}
  th{background:#eef2ff;color:#1e3a8a;}
  tr:nth-child(even) td{background:#fafbff;}
  .chart{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0;}
  .note{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:12px 14px;font-size:13.5px;color:#92400e;}
  .rec{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px;padding:12px 16px;}
  .rec li{margin:6px 0;}
  .tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;background:#e0e7ff;color:#3730a3;margin-right:4px;}
  .tag.free{background:#dcfce7;color:#166534;}
  .tag.promo{background:#fef3c7;color:#92400e;}
  footer{margin-top:40px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:12px;}
  code{background:#eef2ff;padding:1px 5px;border-radius:4px;font-size:12.5px;}
</style>
"""


def render_html(agg, log, table):
    currency = agg["currency"]
    timeline = agg["timeline"]
    models = agg["models"]
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # 摘要卡片
    cards = f"""
    <div class="cards">
      <div class="card"><div class="k">总物理 token</div><div class="v">{fmt(agg['total_physical'],0)}</div></div>
      <div class="card"><div class="k">额度（折扣前）</div><div class="v blue">{fmt(agg['total_pre'],4)} {currency}</div></div>
      <div class="card"><div class="k">额度（折扣后）</div><div class="v green">{fmt(agg['total_post'],4)} {currency}</div></div>
      <div class="card"><div class="k">折扣节省</div><div class="v green">{fmt(agg['savings'],4)} {currency}（{fmt(agg['savings_pct'],1)}%）</div></div>
      <div class="card"><div class="k">涉及模型 / 环节</div><div class="v">{len(models)} / {agg['n_phases']}</div></div>
    </div>"""

    # 环节明细表
    rows = []
    cum_pre = cum_post = 0.0
    for i, p in enumerate(log.get("phases", []), 1):
        cum_pre += p.get("quota_pre", 0)
        cum_post += p.get("quota_post", 0)
        st = p.get("discount_state", "none")
        tagcls = "free" if st == "limited_free" else ("promo" if st in ("promo", "active") else "")
        rows.append(
            f"<tr><td>{i}</td><td>{html.escape(p.get('phase',''))}</td><td>{html.escape(p.get('model',''))}</td>"
            f"<td>{p.get('physical_tokens',0)}</td>"
            f"<td><span class='tag {tagcls}'>{st}</span>{p.get('discount_rate',1)}</td>"
            f"<td>{fmt(p.get('quota_pre',0),4)}</td><td>{fmt(p.get('quota_post',0),4)}</td>"
            f"<td>{fmt(cum_pre,4)}</td><td>{fmt(cum_post,4)}</td>"
            f"<td>{html.escape(p.get('note',''))}</td></tr>"
        )
    phase_table = (
        "<table><thead><tr><th>#</th><th>环节</th><th>模型</th><th>物理token</th>"
        "<th>折扣状态</th><th>额度(前)</th><th>额度(后)</th><th>累计(前)</th><th>累计(后)</th><th>备注</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )

    # 按模型表
    mrows = []
    for d in sorted(models, key=lambda x: x["quota_post"], reverse=True):
        st_tags = " ".join(f"<span class='tag'>{s}</span>" for s in d["states"])
        mrows.append(
            f"<tr><td>{html.escape(d['model'])}</td><td>{d['phases']}</td>"
            f"<td>{d['physical_tokens']}</td>"
            f"<td>{fmt(d['billing_pre'],2)}</td><td>{fmt(d['billing_post'],2)}</td>"
            f"<td>{fmt(d['quota_pre'],4)}</td><td>{fmt(d['quota_post'],4)}</td>"
            f"<td>{st_tags}</td></tr>"
        )
    model_table = (
        "<table><thead><tr><th>模型</th><th>环节数</th><th>物理token</th>"
        "<th>计费token(前)</th><th>计费token(后)</th><th>额度(前)</th><th>额度(后)</th><th>折扣状态</th></tr></thead>"
        f"<tbody>{''.join(mrows)}</tbody></table>"
    )

    # 折扣分析
    discounted = [p for p in log.get("phases", []) if p.get("discount_state", "none") != "none"]
    if discounted:
        dlist = "".join(
            f"<li><b>{html.escape(p.get('phase',''))}</b>（{p.get('model','')}）："
            f"{p.get('discount_state','')} ×{p.get('discount_rate',1)}，"
            f"节省 {fmt(p.get('quota_pre',0)-p.get('quota_post',0),4)} {currency}</li>"
            for p in discounted
        )
        discount_section = f"""
        <h2>折扣影响分析</h2>
        <div class="note">本报告对处于 <b>活动 / 促销 / 限时免费</b> 状态的环节，分别记录折扣前与折扣后的计费 token 与额度，
        以支持阶段性额度评估。当前共 {len(discounted)} 个环节享受折扣。</div>
        <ul>{dlist}</ul>
        <p>整体因折扣节省 <b>{fmt(agg['savings'],4)} {currency}</b>（占折扣前 {fmt(agg['savings_pct'],1)}%）。</p>"""
    else:
        discount_section = """
        <h2>折扣影响分析</h2>
        <div class="note">本次任务未出现折扣状态（活动/促销/限时免费）。若后续模型进入折扣期，
        记录时传入 <code>--discount-state</code> 与 <code>--discount-rate</code> 即可自动区分前后口径。</div>"""

    # 规划建议（数据驱动）
    top_model = max(models, key=lambda d: d["quota_post"]) if models else None
    recs = []
    if top_model:
        share = (top_model["quota_post"] / agg["total_post"] * 100) if agg["total_post"] > 0 else 0
        recs.append(f"成本集中度：模型 <b>{html.escape(top_model['model'])}</b> 占总折扣后额度的 {fmt(share,1)}%，"
                    f"是优化重点；可评估是否将部分环节改用更便宜的模型（如轻量版/Flash 类）。")
    if agg["savings_pct"] > 0:
        recs.append(f"折扣红利：当前折扣已节省 {fmt(agg['savings_pct'],1)}% 额度，"
                    f"建议把高消耗环节尽量安排在折扣窗口内执行。")
    if agg["n_phases"]:
        avg = agg["total_post"] / agg["n_phases"]
        recs.append(f"单位环节成本：平均每个环节折扣后额度约 {fmt(avg,4)} {currency}，"
                    f"可作为后续同类任务的预算基线。")
    recs.append("建议在每个环节结束后立即记录（<code>consumption_logger.py log</code>），"
                "避免任务收尾时凭记忆补录导致统计偏差。")
    recs.append("若同一任务跨多模型，优先把检索/清洗等高频低价值环节分配给低成本模型，"
                "把需要推理/生成的环节留给高性能模型。")
    rec_section = f"""<h2>任务规划建议</h2><div class="rec"><ul>{"".join(f"<li>{r}</li>" for r in recs)}</ul></div>"""

    price_src = (table or {}).get("source", "未知")
    price_upd = (table or {}).get("updated_at", "未知")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Token 消耗报告 · {html.escape(log.get('task_name',''))}</title>{CSS}</head>
<body><div class="wrap">
<header>
  <h1>Token 与额度消耗报告</h1>
  <div class="sub">任务：<b>{html.escape(log.get('task_name','未命名'))}</b> ｜ 生成时间：{now} ｜ 货币：{currency}<br>
  价格表来源：{html.escape(str(price_src))} ｜ 价格更新：{html.escape(str(price_upd))} ｜ Skill 版本：1.0.0</div>
</header>

<h2>一、关键指标</h2>
{cards}

<h2>二、消耗随任务进度变化（累计额度）</h2>
<div class="chart">{svg_line_chart(timeline, currency)}</div>
<p class="sub">蓝线为「折扣前」累计额度，绿线为「折扣后」累计额度。两线间距即折扣带来的节省，
随环节推进逐步放大，可用于阶段性额度评估与预算预警。</p>

<h2>三、按模型分布（折扣后额度）</h2>
<div class="chart">{svg_bar_chart(models, currency)}</div>

<h2>四、环节明细</h2>
{phase_table}

<h2>五、按模型汇总</h2>
{model_table}

{discount_section}

{rec_section}

<footer>
本报告由 <b>workbuddy-token-audit · plan 模式</b> 自动生成。token 数值若来自 agent 估算会在备注标注；
如需精确值，请从平台导出实际用量后通过 <code>--input-tokens/--output-tokens</code> 录入。
额度 = 计费 token ÷ 1000 × 单价（取自 price_table.json）。
</footer>
</div></body></html>"""


def main(argv=None):
    p = argparse.ArgumentParser(description="生成 token 消耗报告")
    p.add_argument("--workdir", default=_default_workdir())
    p.add_argument("--out", default=None, help="输出 HTML 路径（默认 <workdir>/token_consumption_report.html）")
    p.add_argument("--title", default=None)
    args = p.parse_args(argv)

    log = load_json(os.path.join(args.workdir, LOG_FILE))
    if not log:
        print("[report] 未找到 consumption_log.json，请先记录环节。")
        return 1
    table = load_json(os.path.join(args.workdir, PRICE_FILE))
    agg = aggregate(log, table)
    html_out = render_html(agg, log, table)
    out = args.out or os.path.join(args.workdir, "token_consumption_report.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"[report] 已生成报告：{out}")
    print(f"[report] 总物理 token={agg['total_physical']} 折扣前={agg['total_pre']:.4f} "
          f"折扣后={agg['total_post']:.4f} {agg['currency']} 节省={agg['savings_pct']:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
