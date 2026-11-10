# -*- coding: utf-8 -*-
"""
Agent 查询工具（只读）
======================

对应文章第 08 节 STEP 05「实现可追溯的查询工具」：
- 查询结果不仅返回答案，还保留来源系统、对象标识、状态、查询时间；
- 对于无法确认的关联，明确返回「未知/待核实」，不让模型自行补全；
- 工具全部是只读的 —— 本体定义「什么叫退款」，并不意味着 Agent 有权退款
  （文章第 07 节权限边界）。
"""
from __future__ import annotations

import json
from datetime import datetime

from ontology.classes import CLASS_REGISTRY
from ontology.relations import describe_relations
from ontology.rules import evaluate_bill_payments
from systems import db

# 模拟「已授权登录客户」的会话上下文（生产环境来自认证系统，而非用户口述）
_SESSION_CUSTOMER_ID: str | None = None


def set_session_customer(customer_id: str) -> None:
    global _SESSION_CUSTOMER_ID
    _SESSION_CUSTOMER_ID = customer_id


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _wrap(system: str, payload) -> str:
    """统一包装：来源系统 + 查询时间，保证可追溯。"""
    return json.dumps(
        {"source_system": system, "queried_at": _now(), "result": payload},
        ensure_ascii=False,
        default=str,
    )


def _customer_permission_error(customer_id: str) -> str | None:
    """校验客户入参是否与当前已授权会话一致。"""
    if not _SESSION_CUSTOMER_ID or customer_id != _SESSION_CUSTOMER_ID:
        return _wrap("权限", {"error": "对象不属于当前会话客户或未建立会话"})
    return None


def _account_permission_error(account_id: str) -> str | None:
    """账户必须通过 MDM 已验证映射归属于当前会话客户。"""
    if (
        not _SESSION_CUSTOMER_ID
        or account_id not in db.mdm_verified_accounts_of_customer(_SESSION_CUSTOMER_ID)
    ):
        return _wrap("权限", {"error": "对象不属于当前会话客户或未建立会话"})
    return None


# ---------------------------------------------------------------------------
# 0. 本体说明
# ---------------------------------------------------------------------------
def describe_ontology() -> str:
    """返回业务本体的类定义与关系定义（业务语义基础）。"""
    classes = "\n".join(f"- {k}: {v}" for k, v in CLASS_REGISTRY.items())
    return (
        "【业务对象（类）】\n" + classes
        + "\n\n【业务关系】\n" + describe_relations()
        + "\n\n【核心规则】\n"
        "- 金额相同不是证据：判断重复扣费必须以 settlesBill 关联 + 状态维度为准。\n"
        "- 支付成功 ≠ 账单结清 ≠ 退款完成：三个状态维度独立。\n"
        "- 只有 COMPLETED 的冲正/退款才改变资金事实。\n"
        "- 关联缺失、处理中事项 => 结论必须标注未知/待核实。\n"
        "- 你只有只读权限：不得承诺已退款/已解决，只能提出核查建议。"
    )


# ---------------------------------------------------------------------------
# 1. 客户与账户（CRM + MDM + BSS）
# ---------------------------------------------------------------------------
def get_current_customer() -> str:
    """获取当前已授权登录的客户信息（会话身份，来自认证而非用户口述）。"""
    if not _SESSION_CUSTOMER_ID:
        return _wrap("CRM", {"error": "未建立会话身份"})
    cust = db.crm_get_customer(_SESSION_CUSTOMER_ID)
    if not cust:
        return _wrap("CRM", {"error": f"客户 {_SESSION_CUSTOMER_ID} 不存在"})
    return _wrap("CRM", {
        "customer_id": cust.customer_id,
        "name": cust.name,
        "id_type": cust.id_type,
        "id_number_masked": cust.id_number_masked,
        "contact_phone": cust.contact_phone,
    })


def get_verified_accounts(customer_id: str) -> str:
    """查询客户名下经过 MDM 验证的业务账户（无映射则明确返回空，不得猜测）。"""
    if error := _customer_permission_error(customer_id):
        return error
    account_ids = db.mdm_verified_accounts_of_customer(customer_id)
    if not account_ids:
        return _wrap("主数据管理", {
            "customer_id": customer_id,
            "accounts": [],
            "note": "未找到经过验证的账户映射，不能凭姓名/号码相似推断关联。",
        })
    accounts = []
    for aid in account_ids:
        acc = db.bss_get_account(aid)
        if acc:
            accounts.append({
                "account_id": acc.account_id,
                "account_type": acc.account_type,
                "status": acc.status,
                "open_date": acc.open_date,
            })
    return _wrap("主数据管理+BSS", {"customer_id": customer_id, "accounts": accounts})


def get_account_details(account_id: str) -> str:
    """查询账户详情：号码与套餐（BSS）。"""
    if error := _account_permission_error(account_id):
        return error
    acc = db.bss_get_account(account_id)
    if not acc:
        return _wrap("BSS", {"error": f"账户 {account_id} 不存在"})
    phones = db.bss_get_phones(account_id)
    plans = db.bss_get_plans(account_id)
    return _wrap("BSS", {
        "account_id": acc.account_id,
        "account_type": acc.account_type,
        "status": acc.status,
        "phones": [{"msisdn": p.msisdn, "status": p.status} for p in phones],
        "plans": [{"plan_name": p.plan_name, "monthly_fee": p.monthly_fee,
                   "effective_date": p.effective_date} for p in plans],
    })


# ---------------------------------------------------------------------------
# 2. 账单（计费系统）
# ---------------------------------------------------------------------------
def list_bills(account_id: str, billing_period: str | None = None) -> str:
    """查询账户的账单列表，可按计费周期（YYYY-MM）过滤。"""
    if error := _account_permission_error(account_id):
        return error
    bills = db.billing_list_bills(account_id, billing_period)
    return _wrap("计费系统", {
        "account_id": account_id,
        "bills": [{
            "bill_id": b.bill_id,
            "billing_period": b.billing_period,
            "amount_due": b.amount_due,
            "bill_status": b.bill_status.value,
            "generated_at": b.generated_at,
        } for b in bills],
    })


def get_bill(bill_id: str) -> str:
    """查询单张账单详情。"""
    b = db.billing_get_bill(bill_id)
    if not b:
        return _wrap("计费系统", {"error": f"账单 {bill_id} 不存在"})
    if error := _account_permission_error(b.account_id):
        return error
    return _wrap("计费系统", {
        "bill_id": b.bill_id, "account_id": b.account_id,
        "billing_period": b.billing_period, "amount_due": b.amount_due,
        "bill_status": b.bill_status.value, "generated_at": b.generated_at,
    })


# ---------------------------------------------------------------------------
# 3. 支付 / 冲正 / 退款（支付系统）
# ---------------------------------------------------------------------------
def list_bill_payments(bill_id: str) -> str:
    """按 settlesBill 关联查询结算某张账单的支付交易。"""
    bill = db.billing_get_bill(bill_id)
    if not bill:
        return _wrap("计费系统", {"error": f"账单 {bill_id} 不存在"})
    if error := _account_permission_error(bill.account_id):
        return error
    txs = db.payment_list_transactions_for_bill(bill_id)
    return _wrap("支付系统", {
        "bill_id": bill_id,
        "transactions": [_tx_dict(t) for t in txs],
        "note": "仅含权威系统记录了关联（bill_ref）的交易；关联缺失的流水不在此列。",
    })


def list_account_payments(account_id: str) -> str:
    """查询账户名下全部支付交易（含关联缺失的流水，用于完整性核查）。"""
    if error := _account_permission_error(account_id):
        return error
    txs = db.payment_list_transactions_for_account(account_id)
    return _wrap("支付系统", {
        "account_id": account_id,
        "transactions": [_tx_dict(t) for t in txs],
    })


def get_transaction_adjustments(transaction_id: str) -> str:
    """查询一笔交易的冲正与退款记录（含各自处理状态）。"""
    tx = db.payment_get_transaction(transaction_id)
    if not tx:
        return _wrap("支付系统", {"error": f"交易 {transaction_id} 不存在"})
    if error := _account_permission_error(tx.account_id):
        return error
    revs = db.payment_get_reversals(transaction_id)
    refs = db.payment_get_refunds(transaction_id)
    return _wrap("支付系统", {
        "transaction_id": transaction_id,
        "reversals": [{
            "reversal_id": r.reversal_id, "status": r.status.value,
            "reason": r.reason, "created_at": r.created_at,
        } for r in revs],
        "refunds": [{
            "refund_id": r.refund_id, "amount": r.amount,
            "status": r.status.value, "created_at": r.created_at,
        } for r in refs],
        "note": "只有 COMPLETED 状态的冲正/退款才改变资金事实。",
    })


def _tx_dict(t) -> dict:
    return {
        "transaction_id": t.transaction_id,
        "amount": t.amount,
        "occurred_at": t.occurred_at,
        "status": t.status.value,
        "channel": t.channel,
        "bill_ref": t.bill_ref,           # None = 关联缺失，待核实
        "request_id": t.request_id,
    }


# ---------------------------------------------------------------------------
# 4. 投诉工单（客服系统）
# ---------------------------------------------------------------------------
def list_complaint_tickets(customer_id: str) -> str:
    """查询客户的投诉工单（工单描述是用户主张，非已核实事实）。"""
    if error := _customer_permission_error(customer_id):
        return error
    tickets = db.cs_list_tickets(customer_id)
    return _wrap("客服系统", {
        "customer_id": customer_id,
        "tickets": [{
            "ticket_id": t.ticket_id,
            "complaint_type": t.complaint_type,
            "description": t.description,
            "status": t.status.value,
            "created_at": t.created_at,
            "related_bill_id": t.related_bill_id,
            "related_transaction_ids": list(t.related_transaction_ids),
            "resolution": t.resolution,
        } for t in tickets],
        "note": "OPEN/IN_PROGRESS 工单中的描述是用户主观主张；只有 resolution 才是核实结论。",
    })


# ---------------------------------------------------------------------------
# 5. 规则引擎：重复扣费判定
# ---------------------------------------------------------------------------
def collect_bill_evidence(bill_id: str):
    """汇总账单判定证据；仅查询数据，不执行会话归属校验。"""
    bill = db.billing_get_bill(bill_id)
    if not bill:
        return None, [], [], [], []

    txs = db.payment_list_transactions_for_bill(bill_id)
    account_txs = db.payment_list_transactions_for_account(bill.account_id)
    reversals, refunds = [], []
    for t in account_txs:  # 冲正/退款可能挂在任意相关交易上
        reversals.extend(db.payment_get_reversals(t.transaction_id))
        refunds.extend(db.payment_get_refunds(t.transaction_id))
    return bill, txs, reversals, refunds, account_txs


def check_duplicate_billing(bill_id: str) -> str:
    """对指定账单运行重复扣费判定规则，返回带证据与未知项的结论。"""
    bill, txs, reversals, refunds, account_txs = collect_bill_evidence(bill_id)
    if not bill:
        return _wrap("规则引擎", {"error": f"账单 {bill_id} 不存在"})
    if error := _account_permission_error(bill.account_id):
        return error

    verdict = evaluate_bill_payments(
        bill, txs, reversals, refunds, account_transactions=account_txs
    )
    return _wrap("规则引擎", verdict.to_dict())
