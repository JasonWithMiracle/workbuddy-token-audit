#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
consumption_logger.py — 记录「当前任务」每个环节的 token 与额度消耗。

设计要点（对应需求 1、2）
------------------------
* 多模型：每条记录携带 model 字段，报告按模型分别汇总（需求 2）。
* 折扣状态：每条记录携带 discount_state 与 discount_rate，分别计算
  「折扣前」与「折扣后」的计费 token 与额度消耗，便于阶段性额度评估（需求 1）。
    - none         无折扣，rate=1.0
    - active       平台活动折扣，rate∈(0,1)（如 0.8 = 八折计费）
    - promo        促销折扣，rate∈(0,1)
    - limited_free 限时免费，rate=0（额度免费；物理 token 仍记录但计费口径为 0）
* token 口径：
    - 物理 token（physical_*）：真实发生的 token 数，任何情况下都记录。
    - 计费 token（billing_*）：参与额度折算的 token，= 物理 × discount_rate。
      这样「折扣前」(rate=1) 与「折扣后」(rate 实际值) 在 token 与额度两个维度
      都有可比的前后对照。
* 额度（quota）：= 计费 token / 1000 × 对应单价（取价格表）。

用法
----
  python consumption_logger.py init --task-name "..." [--workdir DIR] [--currency CNY]
  python consumption_logger.py log \
      --phase "1. 初始化" --model claude-sonnet-4 \
      --input-tokens 1200 --output-tokens 800 \
      [--discount-state promo] [--discount-rate 0.8] \
      [--task-name "..."] [--note "..."] [--workdir DIR]
  python consumption_logger.py list [--workdir DIR]

说明
----
* token 数值可由 agent 估算（约 1 token/4 英文字符、1.5 token/中文字）或从平台导出
  精确值后传入；报告会标注「估算/实测」来源（--note 中注明）。
* 价格来自同目录 price_table.json（由 price_updater.py 维护）。
"""

import argparse
import datetime
import json
import os
import sys

LOG_FILE = "consumption_log.json"
PRICE_FILE = "price_table.json"

VALID_DISCOUNT = {"none", "active", "promo", "limited_free"}


def _default_workdir():
    return os.path.join(os.getcwd(), ".workbuddy", "token-tracker")


def _shared_price_file():
    """价格表统一取 skill 的 assets/price_table.json（与审计引擎共享同一份，避免两套价目）"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    shared = os.path.join(root, "assets", "price_table.json")
    if os.path.exists(shared):
        return shared
    tpl = os.path.join(root, "assets", "price_table.template.json")
    return tpl if os.path.exists(tpl) else shared


def _paths(workdir):
    """日志留在 workdir（任务级产物）；价格表统一指向 skill 共享表"""
    shared = _shared_price_file()
    price = shared if os.path.exists(shared) else os.path.join(workdir, PRICE_FILE)
    return os.path.join(workdir, LOG_FILE), price


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _price_for(table, model):
    """兼容两种价格表格式：
       A) 原 tracker 格式：{"models": {name: {"input_per_1k":.., "output_per_1k":..}}}
       B) 共享格式（assets/price_table.json）：元/百万 token，{"models": {key: {"kind":..,"price":[in,out,cache]}}}
    共享表采用前缀匹配（审计引擎口径一致），确保两个模式用同一套价目。
    """
    models = (table or {}).get("models", {})
    info = models.get(model)
    if not info and model:
        ml = model.lower()
        for k in sorted(models.keys(), key=len, reverse=True):
            if ml.startswith(k.lower()) or k.lower() in ml:
                info = models[k]
                break
    if not info:
        return None
    if "input_per_1k" in info:
        return float(info.get("input_per_1k", 0.0)), float(info.get("output_per_1k", 0.0))
    p = info.get("price") or info.get("peak") or [0.0, 0.0]
    return float(p[0]) / 1000.0, float(p[1]) / 1000.0


def cmd_init(workdir, task_name, currency):
    log_path, _ = _paths(workdir)
    if os.path.exists(log_path):
        print(f"[init] 日志已存在，跳过：{log_path}")
        return 0
    data = {
        "schema_version": 1,
        "task_name": task_name or "未命名任务",
        "currency": currency or "CNY",
        "created_at": _now(),
        "phases": [],
    }
    save_json(log_path, data)
    print(f"[init] 已初始化任务日志：{log_path}")
    return 0


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_log(workdir, args):
    log_path, price_path = _paths(workdir)
    log = load_json(log_path)
    if not log:
        print("[log] 日志不存在，先用 init 创建。")
        return 1
    table = load_json(price_path)
    price = _price_for(table, args.model)
    if price is None:
        print(f"[log] 警告：价格表中无模型 {args.model}，额度按 0 计；"
              f"请先运行 price_updater.py init/set。")
        in_p, out_p = 0.0, 0.0
    else:
        in_p, out_p = price

    state = (args.discount_state or "none").lower()
    if state not in VALID_DISCOUNT:
        print(f"[log] 无效 discount_state：{state}，应为 {sorted(VALID_DISCOUNT)}")
        return 2
    rate = float(args.discount_rate if args.discount_rate is not None else (0.0 if state == "limited_free" else 1.0))

    i_tok = int(args.input_tokens)
    o_tok = int(args.output_tokens)

    # 计费 token（折扣后）= 物理 × rate；折扣前 rate=1
    bill_in_pre = i_tok
    bill_out_pre = o_tok
    bill_in_post = i_tok * rate
    bill_out_post = o_tok * rate

    q_in_pre = bill_in_pre / 1000.0 * in_p
    q_out_pre = bill_out_pre / 1000.0 * out_p
    q_in_post = bill_in_post / 1000.0 * in_p
    q_out_post = bill_out_post / 1000.0 * out_p

    entry = {
        "phase": args.phase or f"环节{len(log['phases'])+1}",
        "model": args.model,
        "input_tokens": i_tok,
        "output_tokens": o_tok,
        "physical_tokens": i_tok + o_tok,
        "discount_state": state,
        "discount_rate": rate,
        "billing_input_pre": round(bill_in_pre, 4),
        "billing_output_pre": round(bill_out_pre, 4),
        "billing_input_post": round(bill_in_post, 4),
        "billing_output_post": round(bill_out_post, 4),
        "quota_input_pre": round(q_in_pre, 6),
        "quota_output_pre": round(q_out_pre, 6),
        "quota_input_post": round(q_in_post, 6),
        "quota_output_post": round(q_out_post, 6),
        "quota_pre": round(q_in_pre + q_out_pre, 6),
        "quota_post": round(q_in_post + q_out_post, 6),
        "price_input_per_1k": in_p,
        "price_output_per_1k": out_p,
        "note": args.note or "",
        "ts": _now(),
    }
    log["phases"].append(entry)
    save_json(log_path, log)
    print(f"[log] 已记录「{entry['phase']}」 model={args.model} "
          f"物理tok={entry['physical_tokens']} 折扣={state}(rate={rate}) "
          f"额度 前={entry['quota_pre']:.4f} 后={entry['quota_post']:.4f} {log['currency']}")
    return 0


def cmd_list(workdir):
    log_path, _ = _paths(workdir)
    log = load_json(log_path)
    if not log:
        print("[list] 日志不存在。")
        return 1
    print(f"任务: {log.get('task_name')} | 货币: {log.get('currency')} | 环节数: {len(log.get('phases', []))}")
    for i, e in enumerate(log.get("phases", []), 1):
        print(f"  {i:>2}. {e['phase']:<14} model={e['model']:<18} "
              f"tok={e['physical_tokens']:<7} {e['discount_state']:<12} "
              f"额度前={e['quota_pre']:.4f} 后={e['quota_post']:.4f}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="workbuddy-token-audit · plan 模式：任务内环节消耗记录")
    p.add_argument("command", choices=["init", "log", "list"])
    p.add_argument("--workdir", default=_default_workdir())
    p.add_argument("--task-name", default=None)
    p.add_argument("--currency", default="CNY")
    p.add_argument("--phase", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--input-tokens", dest="input_tokens", default=0)
    p.add_argument("--output-tokens", dest="output_tokens", default=0)
    p.add_argument("--discount-state", dest="discount_state", default="none")
    p.add_argument("--discount-rate", dest="discount_rate", default=None)
    p.add_argument("--note", default="")
    args = p.parse_args(argv)

    if args.command == "init":
        return cmd_init(args.workdir, args.task_name, args.currency)
    if args.command == "log":
        if not args.model:
            print("[log] 需提供 --model")
            return 2
        return cmd_log(workdir=args.workdir, args=args)
    if args.command == "list":
        return cmd_list(args.workdir)
    return 2


if __name__ == "__main__":
    sys.exit(main())
