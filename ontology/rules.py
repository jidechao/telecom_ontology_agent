# -*- coding: utf-8 -*-
"""
本体 - 业务规则引擎：重复扣费判定
==================================

对应文章第 04 节「验证规则：哪些条件成立时，可以得出什么结论」
以及第 05 节 STEP 04「比较不同的业务情形」。

核心规则（全部直接来自文章的论述）：

R1  金额相同不是证据。
    判断重复扣费必须基于 settlesBill 业务关联，而不是金额/时间相似。
    「金额相同，不等于重复扣费；客户相同，也不等于交易属于同一笔业务。」

R2  交易是否有效，由状态维度决定。
    有效扣款 = 交易状态 SUCCESS 且 无 COMPLETED 冲正 且 无 COMPLETED 退款。
    存在 REQUESTED 状态的冲正/退款时，资金事实处于变化中，结论须标注待核实。

R3  情形判定。
    - 情形 A：多笔交易关联不同账单（即使是同一客户、同一金额、时间接近）
      => NOT_DUPLICATE，不得认定重复扣费。
    - 情形 B：两笔及以上有效交易关联同一张账单
      => SUSPECTED_DUPLICATE（疑似重复扣费，需进一步核实）。
      文章明确指出：即使如此也「不能仅凭这些信息直接确认重复扣费」，
      需核实计费规则、最终状态、有效冲正/退款、是否允许多次支付等。
    - 只有一笔有效交易 => NOT_DUPLICATE。

R4  证据不足时必须返回 UNKNOWN。
    关联缺失、查询范围不完整、数据同步延迟未排除时，
    明确返回「待核实/无法确认」，不得让模型自行补全。

R5  结论分级：CONFIRMED_FACT / SUSPECTED / UNKNOWN。
    Agent 的输出必须区分已确认事实、异常线索和未知信息。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .classes import (
    Bill,
    PaymentStatus,
    PaymentTransaction,
    RefundStatus,
    RefundTransaction,
    ReversalStatus,
    ReversalTransaction,
)


class VerdictCode(str, Enum):
    NOT_DUPLICATE = "NOT_DUPLICATE"                # 未发现重复扣费证据
    SUSPECTED_DUPLICATE = "SUSPECTED_DUPLICATE"    # 疑似重复扣费，需人工进一步核实
    UNKNOWN = "UNKNOWN"                            # 证据不足，无法确认


class EvidenceGrade(str, Enum):
    CONFIRMED_FACT = "已确认事实"
    SUSPECTED = "异常线索"
    UNKNOWN = "未知信息"


@dataclass
class EvidenceItem:
    """一条证据：必须带来源系统与对象标识（可追溯）。"""
    system: str
    object_type: str
    object_id: str
    fact: str
    grade: EvidenceGrade


@dataclass
class Verdict:
    """规则引擎结论：判定码 + 推理步骤 + 证据清单 + 未知项。"""
    code: VerdictCode
    summary: str
    reasoning: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.code.value,
            "summary": self.summary,
            "reasoning": self.reasoning,
            "evidence": [
                {
                    "system": e.system,
                    "object": f"{e.object_type}/{e.object_id}",
                    "fact": e.fact,
                    "grade": e.grade.value,
                }
                for e in self.evidence
            ],
            "unknowns": self.unknowns,
            "next_actions": self.next_actions,
        }


# 哪些状态的交易可视为「有效扣款」的候选
_SUCCESS = PaymentStatus.SUCCESS


def _is_effectively_reversed(tx_id: str, reversals: list[ReversalTransaction]) -> bool:
    """R2：只有 COMPLETED 状态的冲正才使原交易失效。"""
    return any(
        r.original_transaction_id == tx_id and r.status == ReversalStatus.COMPLETED
        for r in reversals
    )


def _is_effectively_refunded(tx_id: str, refunds: list[RefundTransaction]) -> bool:
    """R2：只有 COMPLETED 状态的退款才改变资金事实。"""
    return any(
        r.original_transaction_id == tx_id and r.status == RefundStatus.COMPLETED
        for r in refunds
    )


def evaluate_bill_payments(
    bill: Bill,
    transactions: list[PaymentTransaction],
    reversals: list[ReversalTransaction],
    refunds: list[RefundTransaction],
    account_transactions: Optional[list[PaymentTransaction]] = None,
) -> Verdict:
    """对一张账单执行重复扣费判定。

    参数
    ----
    bill:                 目标账单（计费系统权威记录）
    transactions:         settlesBill 关联到该账单的全部支付交易
    reversals/refunds:    支付系统中相关的冲正/退款记录
    account_transactions: 该账户近期全部交易（用于发现关联缺失的流水，R4）
    """
    v = Verdict(code=VerdictCode.UNKNOWN, summary="")
    r = v.reasoning

    r.append(
        f"目标账单 {bill.bill_id}：计费周期 {bill.billing_period}，"
        f"应收 {bill.amount_due:.2f} 元，账单状态 {bill.bill_status.value}（来源：计费系统）。"
    )
    v.evidence.append(EvidenceItem(
        system="计费系统", object_type="Bill", object_id=bill.bill_id,
        fact=f"计费周期 {bill.billing_period}，应收 {bill.amount_due:.2f} 元，状态 {bill.bill_status.value}",
        grade=EvidenceGrade.CONFIRMED_FACT,
    ))

    # --- R4：检查账户层面是否存在关联缺失的交易 --------------------------
    if account_transactions is not None:
        linked_ids = {t.transaction_id for t in transactions}
        orphans = [
            t for t in account_transactions
            if t.bill_ref is None and t.status == _SUCCESS and t.transaction_id not in linked_ids
        ]
        for t in orphans:
            v.unknowns.append(
                f"交易 {t.transaction_id}（{t.amount:.2f} 元，{t.occurred_at}）在支付系统中"
                f"未提供关联账单（settlesBill 缺失），无法确认其结算对象，需人工核查。"
            )
            v.evidence.append(EvidenceItem(
                system="支付系统", object_type="PaymentTransaction", object_id=t.transaction_id,
                fact=f"{t.amount:.2f} 元，状态 {t.status.value}，关联账单缺失",
                grade=EvidenceGrade.UNKNOWN,
            ))

    # --- R1/R2：按 settlesBill 关联 + 状态维度筛选有效扣款 ----------------
    effective: list[PaymentTransaction] = []
    pending_changes: list[str] = []

    for tx in transactions:
        if tx.status != _SUCCESS:
            r.append(
                f"交易 {tx.transaction_id} 状态为 {tx.status.value}，非成功交易，不计入扣款事实。"
            )
            v.evidence.append(EvidenceItem(
                system="支付系统", object_type="PaymentTransaction", object_id=tx.transaction_id,
                fact=f"关联账单 {tx.bill_ref}，金额 {tx.amount:.2f} 元，状态 {tx.status.value}（非成功）",
                grade=EvidenceGrade.CONFIRMED_FACT,
            ))
            continue

        if _is_effectively_reversed(tx.transaction_id, reversals):
            r.append(
                f"交易 {tx.transaction_id} 虽显示成功，但存在已生效（COMPLETED）的冲正记录，"
                f"该交易已失效，不计入有效扣款。"
            )
            v.evidence.append(EvidenceItem(
                system="支付系统", object_type="PaymentTransaction", object_id=tx.transaction_id,
                fact=f"成功交易，但已被 COMPLETED 冲正撤销",
                grade=EvidenceGrade.CONFIRMED_FACT,
            ))
            continue

        if _is_effectively_refunded(tx.transaction_id, refunds):
            r.append(
                f"交易 {tx.transaction_id} 虽显示成功，但对应退款已完成（COMPLETED），"
                f"资金已退回，不计入有效扣款。"
            )
            v.evidence.append(EvidenceItem(
                system="支付系统", object_type="PaymentTransaction", object_id=tx.transaction_id,
                fact=f"成功交易，但退款已完成",
                grade=EvidenceGrade.CONFIRMED_FACT,
            ))
            continue

        # 处理中的冲正/退款：交易暂计为有效，但结论必须标注待核实（R2）
        pend_rev = [x.reversal_id for x in reversals
                    if x.original_transaction_id == tx.transaction_id
                    and x.status == ReversalStatus.REQUESTED]
        pend_ref = [x.refund_id for x in refunds
                    if x.original_transaction_id == tx.transaction_id
                    and x.status == RefundStatus.REQUESTED]
        if pend_rev:
            pending_changes.append(f"交易 {tx.transaction_id} 存在处理中的冲正 {', '.join(pend_rev)}")
        if pend_ref:
            pending_changes.append(f"交易 {tx.transaction_id} 存在处理中的退款 {', '.join(pend_ref)}")

        effective.append(tx)
        v.evidence.append(EvidenceItem(
            system="支付系统", object_type="PaymentTransaction", object_id=tx.transaction_id,
            fact=f"关联账单 {tx.bill_ref}，金额 {tx.amount:.2f} 元，{tx.occurred_at}，"
                 f"状态 SUCCESS，无已生效冲正/退款",
            grade=EvidenceGrade.CONFIRMED_FACT,
        ))

    r.append(
        f"经 settlesBill 关联与状态维度核对，该账单的有效扣款交易共 {len(effective)} 笔"
        f"（金额相同不作为证据，仅以权威系统关联为准）。"
    )

    # --- R3：情形判定 ----------------------------------------------------
    if len(effective) <= 1 and not v.unknowns and not pending_changes:
        v.code = VerdictCode.NOT_DUPLICATE
        v.summary = (
            f"账单 {bill.bill_id} 仅发现 {len(effective)} 笔有效扣款交易，"
            f"未发现同一账单被重复支付的证据。"
        )
        r.append("情形判定：有效扣款不超过 1 笔 => 不构成重复扣费。")
    elif len(effective) >= 2:
        v.code = VerdictCode.SUSPECTED_DUPLICATE
        tx_list = "、".join(t.transaction_id for t in effective)
        v.summary = (
            f"账单 {bill.bill_id} 关联 {len(effective)} 笔支付成功且未失效的交易（{tx_list}），"
            f"存在重复扣费的可能，需进一步核实。"
        )
        r.append(
            "情形判定（情形 B）：两笔及以上有效交易关联同一张账单 => 疑似重复扣费。"
            "注意：即使如此也不能直接确认，仍需核实计费规则、交易最终状态、"
            "是否存在业务上允许的多次支付/分次结算。"
        )
        v.evidence.append(EvidenceItem(
            system="规则引擎", object_type="Verdict", object_id=bill.bill_id,
            fact=f"同一账单关联 {len(effective)} 笔有效成功交易",
            grade=EvidenceGrade.SUSPECTED,
        ))
        v.next_actions.append("转计费核查岗核实该账单是否允许多次支付/分次结算")
        v.next_actions.append("向支付渠道核对两笔交易的最终清算状态")
    else:
        v.code = VerdictCode.UNKNOWN
        v.summary = (
            f"账单 {bill.bill_id} 的有效扣款交易为 {len(effective)} 笔，"
            f"结论待定，存在未核实事项。"
        )

    # --- R2/R4：待核实事项改写结论强度 ------------------------------------
    if pending_changes:
        for p in pending_changes:
            v.unknowns.append(p + "，处理结果可能改变最终结论。")
        r.append("存在处理中的冲正/退款，资金事实处于变化中，当前结论为阶段性结论。")

    if v.unknowns:
        v.next_actions.append("对未知项发起人工核查后再给出最终结论")
        if v.code == VerdictCode.NOT_DUPLICATE:
            # 有未知项时不能给出完全干净的否定结论
            v.summary += "（注意：仍存在未核实的交易/处理中事项，详见未知项。）"

    return v
