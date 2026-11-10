# -*- coding: utf-8 -*-
"""
模拟企业系统的存储与查询层
===========================

每个业务系统使用独立的 SQLite 数据库文件，模拟真实企业中
CRM / BSS / 计费 / 支付 / 客服各自为政、标识互不相通的局面；
跨系统关联只能通过 MDM（主数据管理）中经过验证的映射获得 ——
对应文章：「不同系统可以保留自己的主键，但系统需要知道它们之间
有哪些经过验证的关联。」
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ontology.classes import (
    Account,
    Bill,
    BillStatus,
    ComplaintTicket,
    Customer,
    PaymentStatus,
    PaymentTransaction,
    PhoneNumber,
    Plan,
    RefundStatus,
    RefundTransaction,
    ReversalStatus,
    ReversalTransaction,
    TicketStatus,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SYSTEMS = ("crm", "bss", "billing", "payment", "cs", "mdm")


def _db_path(system: str) -> Path:
    return DATA_DIR / f"{system}.db"


def _conn(system: str) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(system))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# 建库
# ---------------------------------------------------------------------------
def init_all_systems() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with _conn("crm") as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS customers(
            customer_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            id_type TEXT NOT NULL,
            id_number_masked TEXT NOT NULL,
            contact_phone TEXT NOT NULL
        );""")

    with _conn("mdm") as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS verified_links(
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_type TEXT NOT NULL,          -- e.g. CUSTOMER_ACCOUNT
            source_system TEXT NOT NULL,
            source_id TEXT NOT NULL,
            target_system TEXT NOT NULL,
            target_id TEXT NOT NULL,
            verified_by TEXT NOT NULL,        -- 核验方式/人员
            verified_at TEXT NOT NULL
        );""")

    with _conn("bss") as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS accounts(
            account_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,        -- 来自 MDM 验证映射
            account_type TEXT NOT NULL,
            open_date TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS phone_numbers(
            msisdn TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plans(
            plan_id TEXT PRIMARY KEY,
            plan_name TEXT NOT NULL,
            monthly_fee REAL NOT NULL,
            account_id TEXT NOT NULL,
            effective_date TEXT NOT NULL
        );""")

    with _conn("billing") as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS bills(
            bill_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            billing_period TEXT NOT NULL,     -- YYYY-MM
            amount_due REAL NOT NULL,
            bill_status TEXT NOT NULL,
            generated_at TEXT NOT NULL
        );""")

    with _conn("payment") as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS transactions(
            transaction_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            amount REAL NOT NULL,
            occurred_at TEXT NOT NULL,
            status TEXT NOT NULL,
            channel TEXT NOT NULL,
            bill_ref TEXT,                    -- settlesBill，可为空（关联缺失）
            request_id TEXT NOT NULL          -- 支付请求标识
        );
        CREATE TABLE IF NOT EXISTS reversals(
            reversal_id TEXT PRIMARY KEY,
            original_transaction_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS refunds(
            refund_id TEXT PRIMARY KEY,
            original_transaction_id TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );""")

    with _conn("cs") as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS tickets(
            ticket_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            complaint_type TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            related_bill_id TEXT,
            related_transaction_ids TEXT,     -- JSON array
            resolution TEXT
        );""")


def reset_all_systems() -> None:
    """删除并重建全部系统库（重新播种前调用）。"""
    for s in SYSTEMS:
        p = _db_path(s)
        if p.exists():
            p.unlink()
    init_all_systems()


# ---------------------------------------------------------------------------
# 查询接口（模拟各系统的业务 API，返回本体对象）
# ---------------------------------------------------------------------------
def crm_find_customers_by_name(name: str) -> list[Customer]:
    with _conn("crm") as c:
        rows = c.execute("SELECT * FROM customers WHERE name = ?", (name,)).fetchall()
    return [Customer(**dict(r)) for r in rows]


def crm_get_customer(customer_id: str) -> Customer | None:
    with _conn("crm") as c:
        r = c.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
    return Customer(**dict(r)) if r else None


def mdm_verified_accounts_of_customer(customer_id: str) -> list[str]:
    """MDM 中经过验证的 客户->账户 映射。查不到映射 = 不能确认关联。"""
    with _conn("mdm") as c:
        rows = c.execute(
            "SELECT target_id FROM verified_links "
            "WHERE link_type='CUSTOMER_ACCOUNT' AND source_id=?",
            (customer_id,),
        ).fetchall()
    return [r["target_id"] for r in rows]


def bss_get_account(account_id: str) -> Account | None:
    with _conn("bss") as c:
        r = c.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    return Account(**dict(r)) if r else None


def bss_get_phones(account_id: str) -> list[PhoneNumber]:
    with _conn("bss") as c:
        rows = c.execute("SELECT * FROM phone_numbers WHERE account_id = ?", (account_id,)).fetchall()
    return [PhoneNumber(**dict(r)) for r in rows]


def bss_get_plans(account_id: str) -> list[Plan]:
    with _conn("bss") as c:
        rows = c.execute("SELECT * FROM plans WHERE account_id = ?", (account_id,)).fetchall()
    return [Plan(**dict(r)) for r in rows]


def billing_list_bills(account_id: str, billing_period: str | None = None) -> list[Bill]:
    sql = "SELECT * FROM bills WHERE account_id = ?"
    params: list = [account_id]
    if billing_period:
        sql += " AND billing_period = ?"
        params.append(billing_period)
    sql += " ORDER BY billing_period DESC"
    with _conn("billing") as c:
        rows = c.execute(sql, params).fetchall()
    return [Bill(**{**dict(r), "bill_status": BillStatus(r["bill_status"])}) for r in rows]


def billing_get_bill(bill_id: str) -> Bill | None:
    with _conn("billing") as c:
        r = c.execute("SELECT * FROM bills WHERE bill_id = ?", (bill_id,)).fetchone()
    return Bill(**{**dict(r), "bill_status": BillStatus(r["bill_status"])}) if r else None


def payment_get_transaction(transaction_id: str) -> PaymentTransaction | None:
    with _conn("payment") as c:
        r = c.execute(
            "SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,)
        ).fetchone()
    return _to_tx(r) if r else None


def payment_list_transactions_for_bill(bill_id: str) -> list[PaymentTransaction]:
    """按 settlesBill 关联查询。关联缺失（bill_ref 为空）的交易不会出现在结果中。"""
    with _conn("payment") as c:
        rows = c.execute("SELECT * FROM transactions WHERE bill_ref = ?", (bill_id,)).fetchall()
    return [_to_tx(r) for r in rows]


def payment_list_transactions_for_account(account_id: str, since: str | None = None) -> list[PaymentTransaction]:
    sql = "SELECT * FROM transactions WHERE account_id = ?"
    params: list = [account_id]
    if since:
        sql += " AND occurred_at >= ?"
        params.append(since)
    sql += " ORDER BY occurred_at"
    with _conn("payment") as c:
        rows = c.execute(sql, params).fetchall()
    return [_to_tx(r) for r in rows]


def payment_get_reversals(transaction_id: str) -> list[ReversalTransaction]:
    with _conn("payment") as c:
        rows = c.execute(
            "SELECT * FROM reversals WHERE original_transaction_id = ?", (transaction_id,)
        ).fetchall()
    return [ReversalTransaction(**{**dict(r), "status": ReversalStatus(r["status"])}) for r in rows]


def payment_get_refunds(transaction_id: str) -> list[RefundTransaction]:
    with _conn("payment") as c:
        rows = c.execute(
            "SELECT * FROM refunds WHERE original_transaction_id = ?", (transaction_id,)
        ).fetchall()
    return [RefundTransaction(**{**dict(r), "status": RefundStatus(r["status"])}) for r in rows]


def cs_list_tickets(customer_id: str) -> list[ComplaintTicket]:
    with _conn("cs") as c:
        rows = c.execute("SELECT * FROM tickets WHERE customer_id = ?", (customer_id,)).fetchall()
    return [
        ComplaintTicket(
            **{
                **dict(r),
                "status": TicketStatus(r["status"]),
                "related_transaction_ids": tuple(json.loads(r["related_transaction_ids"] or "[]")),
            }
        )
        for r in rows
    ]


def _to_tx(r: sqlite3.Row) -> PaymentTransaction:
    return PaymentTransaction(**{**dict(r), "status": PaymentStatus(r["status"])})
