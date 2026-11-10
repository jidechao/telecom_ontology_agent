# -*- coding: utf-8 -*-
"""
无 LLM 的确定性演示：规则引擎复核六组验证样本
==============================================

不调用大模型，直接走「本体 + 规则引擎」的核查路径，
验证文章 STEP 06 的六组测试样本是否都得到正确结论。

运行（项目根目录）：
    python demo_scenario.py
"""
from __future__ import annotations

from systems.seed import seed_all
from ontology.rules import evaluate_bill_payments
from tools.query_tools import collect_bill_evidence

# (客户, 期望核查的账单, 期望结论码, 场景说明)
SCENARIOS = [
    ("C-1001", "张伟", ["B-3105", "B-2980"], "NOT_DUPLICATE",
     "S1 两笔同金额交易分属本月/上月不同账单"),
    ("C-1002", "李娜", ["B-3200"], "SUSPECTED_DUPLICATE",
     "S2 两笔成功交易关联同一账单且无冲正/退款"),
    ("C-1003", "王强", ["B-3301"], "NOT_DUPLICATE",
     "S3 两笔交易关联同一账单，但一笔已被 COMPLETED 冲正"),
    ("C-1004", "赵敏", ["B-3401"], "SUSPECTED_DUPLICATE",
     "S4 两笔成功交易关联同一账单，一笔退款 REQUESTED 未到账"),
    ("C-1005", "陈晨", ["B-3501", "B-3502"], "NOT_DUPLICATE",
     "S5 一人多账户，同金额扣款分属移动/宽带不同账单"),
    ("C-1006", "刘洋", ["B-3601"], "UNKNOWN",
     "S6 一笔正常结算 + 一笔关联缺失交易（结论待定，须带未知项）"),
]


def check_bill(bill_id: str) -> dict:
    bill, txs, reversals, refunds, account_txs = collect_bill_evidence(bill_id)
    return evaluate_bill_payments(
        bill, txs, reversals, refunds, account_transactions=account_txs
    ).to_dict()


def main() -> None:
    seed_all()
    all_pass = True
    for cid, name, bill_ids, expected, desc in SCENARIOS:
        print("=" * 78)
        print(f"客户 {name}（{cid}）  场景：{desc}")
        print("=" * 78)
        for bid in bill_ids:
            v = check_bill(bid)
            status = "PASS" if v["verdict"] == expected else "FAIL"
            if v["verdict"] != expected:
                all_pass = False
            print(f"  账单 {bid}: verdict={v['verdict']}  (期望 {expected})  [{status}]")
            print(f"  结论: {v['summary']}")
            for e in v["evidence"]:
                print(f"    [{e['grade']}] ({e['system']}) {e['object']}: {e['fact']}")
            for u in v["unknowns"]:
                print(f"    [未知项] {u}")
            for a in v["next_actions"]:
                print(f"    [后续动作] {a}")
        print()

    # 补充断言：S4 必须带未知项（退款处理中），S6 必须带未知项（关联缺失）
    s4 = check_bill("B-3401")
    s6 = check_bill("B-3601")
    assert s4["unknowns"], "S4 应包含退款处理中的未知项"
    assert any("关联" in u for u in s6["unknowns"]), "S6 应包含关联缺失的未知项"
    print("补充断言通过：S4 含退款处理中未知项，S6 含关联缺失未知项。")
    print("总体结果:", "全部符合预期" if all_pass else "存在不符合预期的判定！")


if __name__ == "__main__":
    main()
