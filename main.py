# -*- coding: utf-8 -*-
"""
CLI 入口：复现「我的话费是不是被重复扣了？」
============================================

用法（项目根目录，venv 激活后）：

    # 默认：李娜（文章「情形 B」，同账单两笔成功扣款）
    python main.py

    # 指定客户与问题（客户即模拟的登录身份）
    python main.py --customer 张伟 --question "我昨天交的话费，好像又被扣了一次"
    python main.py --customer 王强
    python main.py --customer 赵敏
    python main.py --customer 陈晨
    python main.py --customer 刘洋

可选客户（对应文章 STEP 06 的六组验证样本）：
    张伟 C-1001  两笔同金额分属不同账单（本月+上月结欠） -> 非重复
    李娜 C-1002  同一账单两笔成功扣款，无冲正/退款      -> 疑似重复
    王强 C-1003  同一账单两笔扣款，一笔已冲正           -> 非重复
    赵敏 C-1004  同一账单两笔扣款，一笔退款处理中        -> 疑似但待核实
    陈晨 C-1005  一人多账户，扣款分属移动/宽带          -> 非重复
    刘洋 C-1006  存在关联缺失的交易                    -> 结论含未知项
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from systems import db
from systems.seed import seed_all
from tools.query_tools import set_session_customer
from agent import run_query

DEFAULT_QUESTION = "我这个月的话费好像被扣了两次，能帮我查一下吗？我是不是被重复扣费了？"


def resolve_customer(name_or_id: str) -> str:
    """把用户指定的姓名/编号解析为 CRM 客户编号。"""
    if name_or_id.startswith("C-"):
        cust = db.crm_get_customer(name_or_id)
        if not cust:
            raise SystemExit(f"客户 {name_or_id} 不存在，请先检查播种数据。")
        return cust.customer_id
    matches = db.crm_find_customers_by_name(name_or_id)
    if not matches:
        raise SystemExit(f"CRM 中找不到客户「{name_or_id}」。")
    return matches[0].customer_id


def main() -> None:
    parser = argparse.ArgumentParser(description="话费重复扣费核查 Agent（本体 + OpenAI Agents SDK）")
    parser.add_argument("--customer", default="李娜", help="客户姓名或 CRM 编号（模拟登录身份），默认：李娜")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="用户问题")
    parser.add_argument("--env-file", default=None, help=".env 路径（默认自动查找）")
    parser.add_argument("--reseed", action="store_true", help="重新播种测试数据")
    args = parser.parse_args()

    if args.reseed or not (db.DATA_DIR / "crm.db").exists():
        seed_all()

    customer_id = resolve_customer(args.customer)
    set_session_customer(customer_id)  # 模拟认证系统下发的会话身份
    print(f"[会话] 已授权登录客户：{args.customer}（{customer_id}）")
    print(f"[用户问题] {args.question}")
    print("-" * 78)

    answer = asyncio.run(run_query(args.question, args.env_file))
    print(answer)


if __name__ == "__main__":
    sys.exit(main())
