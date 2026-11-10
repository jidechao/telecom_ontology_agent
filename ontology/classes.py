# -*- coding: utf-8 -*-
"""
本体 - 类（Class）与属性定义
=============================

对应文章第 02 节「先把业务世界拆清楚：什么是对象，什么是关系？」：

- 类定义某种对象的共同语义；实例对应业务世界中的具体对象。
  （Bill 是一类业务对象，B-3105 才是一张具体账单）
- 对象不是数据表。属性描述对象自身的特征。
- **支付成功、账单结清、退款完成，是三个不同的业务事实。**
  如果把它们压缩成一个 status 字段，Agent 很容易得出过于粗糙的结论，
  因此这里刻意把三个状态维度分开建模。
- 每个对象都带 source_system 属性：跨系统回答业务问题时，
  结论必须能追溯到权威来源系统（文章 STEP05「可追溯的查询工具」）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# 来源系统（文章第 01 节的简化电信业务架构）
# ---------------------------------------------------------------------------
class SourceSystem(str, Enum):
    CRM = "CRM"            # 客户资料、客户编号、联系信息
    BSS = "BSS"            # 业务账户、订购关系、套餐信息
    BILLING = "计费系统"    # 账单、费用明细、计费周期
    PAYMENT = "支付系统"    # 支付流水、支付状态、冲正记录
    CS = "客服系统"         # 投诉工单、处理过程、解决结果
    MDM = "主数据管理"      # 经过验证的跨系统标识映射（身份核验）


# ---------------------------------------------------------------------------
# 状态枚举：刻意分离的状态维度
# ---------------------------------------------------------------------------
class BillStatus(str, Enum):
    """账单状态（应收费用这一事实维度）。"""
    UNPAID = "UNPAID"          # 未结清
    PAID = "PAID"              # 已结清
    OVERDUE = "OVERDUE"        # 逾期未结清
    DISPUTED = "DISPUTED"      # 争议中


class PaymentStatus(str, Enum):
    """支付交易状态（一次支付活动这一事实维度）。"""
    INITIATED = "INITIATED"    # 支付请求已发起 —— 不代表扣款成功
    SUCCESS = "SUCCESS"        # 支付通道返回成功 —— 不代表账单已结清
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReversalStatus(str, Enum):
    """冲正记录状态。出现冲正记录 ≠ 冲正已生效，须看状态。"""
    REQUESTED = "REQUESTED"    # 已发起，未生效
    COMPLETED = "COMPLETED"    # 已生效：原交易被撤销
    REJECTED = "REJECTED"


class RefundStatus(str, Enum):
    """退款状态。退款申请存在 ≠ 退款已到账。"""
    REQUESTED = "REQUESTED"    # 已申请，未到账
    COMPLETED = "COMPLETED"    # 已到账
    REJECTED = "REJECTED"


class TicketStatus(str, Enum):
    """工单状态。工单描述是用户的主观主张，不等于已核实事实。"""
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"      # 已有核实结论
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# 业务对象（类）
# ---------------------------------------------------------------------------
@dataclass
class Customer:
    """客户：接受电信服务的客户主体（CRM 权威来源）。"""
    customer_id: str           # CRM 客户编号，如 C-1001
    name: str
    id_type: str               # 证件类型
    id_number_masked: str      # 证件号（脱敏）
    contact_phone: str
    source_system: SourceSystem = SourceSystem.CRM


@dataclass
class Account:
    """业务账户：承载业务关系、费用或结算信息的账户（BSS 权威来源）。

    注意：客户与业务账户不是一一对应（一个客户可有多个账户）。
    """
    account_id: str            # BSS 账户编号，如 A-2088
    customer_id: str           # 经 MDM 验证的所属客户
    account_type: str          # MOBILE / BROADBAND / ...
    open_date: str
    status: str                # ACTIVE / SUSPENDED / CLOSED
    source_system: SourceSystem = SourceSystem.BSS


@dataclass
class PhoneNumber:
    """号码：用户实际使用的电话号码。"""
    msisdn: str
    account_id: str
    status: str
    source_system: SourceSystem = SourceSystem.BSS


@dataclass
class Plan:
    """套餐：用户订购的通信服务及其规则。"""
    plan_id: str
    plan_name: str
    monthly_fee: float
    account_id: str
    effective_date: str
    source_system: SourceSystem = SourceSystem.BSS


@dataclass
class Bill:
    """账单：某个计费周期内形成的应收费用记录（计费系统权威来源）。"""
    bill_id: str               # 如 B-3105
    account_id: str            # 由哪个账户产生
    billing_period: str        # 计费周期，如 2026-10
    amount_due: float          # 应收金额
    bill_status: BillStatus
    generated_at: str
    source_system: SourceSystem = SourceSystem.BILLING


@dataclass
class PaymentTransaction:
    """支付交易：支付系统记录的一次支付尝试或交易。

    settles_bill（bill_ref）表示「交易被系统关联到该账单」这一业务关联；
    是否「已经成功结算该账单」由 status + 后续冲正/退款记录共同决定 ——
    关系与状态分开表达（文章第 03 节第二步）。
    bill_ref 为 None 表示权威系统未提供关联，属「待核实」，不得臆断补全。
    """
    transaction_id: str        # 如 P-7781
    account_id: str
    amount: float
    occurred_at: str
    status: PaymentStatus
    channel: str               # 支付渠道：银行卡代扣/微信/支付宝...
    bill_ref: Optional[str]    # settlesBill 关联（权威系统提供，可能缺失）
    request_id: str            # 支付请求标识：识别同一请求的重复流水
    source_system: SourceSystem = SourceSystem.PAYMENT


@dataclass
class ReversalTransaction:
    """冲正记录：针对某笔原始交易的撤销记录。"""
    reversal_id: str           # 如 REV-9001
    original_transaction_id: str  # reversesTransaction 关联的原始交易
    status: ReversalStatus
    reason: str
    created_at: str
    source_system: SourceSystem = SourceSystem.PAYMENT


@dataclass
class RefundTransaction:
    """退款交易：与退款相关的交易记录。"""
    refund_id: str             # 如 REF-8001
    original_transaction_id: str  # refundsTransaction 关联的原始支付交易
    amount: float
    status: RefundStatus
    created_at: str
    source_system: SourceSystem = SourceSystem.PAYMENT


@dataclass
class ComplaintTicket:
    """投诉工单：客户提出问题后形成的服务处理记录。

    工单中的「疑似重复扣费」是用户主观主张；只有 RESOLVED/CLOSED 且
    带核实结论的工单才可作为已核实事实参考。
    """
    ticket_id: str             # 如 T-9002
    customer_id: str
    complaint_type: str
    description: str
    status: TicketStatus
    created_at: str
    related_bill_id: Optional[str] = None
    related_transaction_ids: tuple = ()
    resolution: Optional[str] = None   # 核实结论（如有）
    source_system: SourceSystem = SourceSystem.CS


# ---------------------------------------------------------------------------
# 类注册表：每个类的业务语义定义（供 describe_ontology 工具向 Agent 呈现）
# ---------------------------------------------------------------------------
CLASS_REGISTRY = {
    "Customer": "客户：接受电信服务的客户主体。权威来源 CRM。同一客户在不同系统中可能有多个标识。",
    "Account": "业务账户：承载业务关系、费用或结算信息的账户。权威来源 BSS。客户与账户不是一一对应。",
    "PhoneNumber": "号码：用户实际使用的电话号码，隶属于某个业务账户。",
    "Plan": "套餐：用户订购的通信服务及其计费规则。",
    "Bill": "账单：某个计费周期内形成的应收费用记录。权威来源计费系统。账单状态与支付状态是两个不同的状态维度。",
    "PaymentTransaction": "支付交易：支付系统记录的一次支付尝试或交易。支付成功 ≠ 账单结清。",
    "ReversalTransaction": "冲正记录：针对某笔原始交易的撤销。存在冲正记录 ≠ 冲正已生效，须看其状态。",
    "RefundTransaction": "退款交易：与退款相关的记录。退款申请存在 ≠ 退款已到账。",
    "ComplaintTicket": "投诉工单：客户问题的服务处理记录。工单描述是用户主张，不等于已核实事实。",
}
