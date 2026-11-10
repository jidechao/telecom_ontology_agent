# -*- coding: utf-8 -*-
"""
本体 - 关系（Relationship）定义与约束
======================================

对应文章第 03 节第二步「定义对象之间的关系」：

    hasAccount / hasPhoneNumber / hasBill / settlesBill /
    reversesTransaction / refundsTransaction / hasComplaint

关键建模原则（文章原文）：
- 「先明确业务关系代表什么，再决定用什么字段、接口和数据规则去实现它。」
- settlesBill 必须讲清楚是「交易被系统关联到该账单」还是「这笔交易已经
  成功结算该账单」。本模型采用前者：**关系说明对象之间的联系，状态及其
  证据说明这段业务关系目前处于什么阶段。**
- 跨系统标识不强行统一，通过 MDM 中经过验证的映射关联；
  不能因姓名/金额/号码相似就认定属于同一业务对象。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RelationDef:
    name: str            # 关系名
    domain: str          # 定义域（源类）
    range: str           # 值域（目标类）
    cardinality: str     # 基数约束
    business_meaning: str  # 业务含义
    semantics_note: str    # 语义注意事项（防止误读）


RELATION_REGISTRY = [
    RelationDef(
        name="hasAccount",
        domain="Customer", range="Account", cardinality="1:N",
        business_meaning="客户关联业务账户",
        semantics_note="客户与账户不是一一对应；跨系统关联必须以 MDM 中经过验证的映射为准，不能凭姓名相同认定。",
    ),
    RelationDef(
        name="hasPhoneNumber",
        domain="Account", range="PhoneNumber", cardinality="1:N",
        business_meaning="业务账户关联电话号码",
        semantics_note="一个账户可关联多个号码；核对账单时须确认用户所说的是哪个账户、哪个号码、哪个计费周期。",
    ),
    RelationDef(
        name="hasBill",
        domain="Account", range="Bill", cardinality="1:N",
        business_meaning="业务账户关联账单（账单由哪个账户产生）",
        semantics_note="以计费系统中账单携带的账户标识为权威依据。",
    ),
    RelationDef(
        name="settlesBill",
        domain="PaymentTransaction", range="Bill", cardinality="N:1",
        business_meaning="支付交易被系统关联到某张账单",
        semantics_note=(
            "仅表示支付系统记录了该交易的结算对象，不等于该账单已成功结算；"
            "是否有效结算须结合交易状态、冲正/退款记录判断。"
            "关联缺失（bill_ref 为空）属于『待核实』，不得凭金额/时间相似自行补全。"
        ),
    ),
    RelationDef(
        name="reversesTransaction",
        domain="ReversalTransaction", range="PaymentTransaction", cardinality="1:1",
        business_meaning="冲正记录针对某笔原始交易",
        semantics_note="出现冲正记录不代表冲正已生效；只有 COMPLETED 状态的冲正才使原交易失效。",
    ),
    RelationDef(
        name="refundsTransaction",
        domain="RefundTransaction", range="PaymentTransaction", cardinality="N:1",
        business_meaning="退款交易关联原始支付交易",
        semantics_note="退款申请存在不代表退款已到账；只有 COMPLETED 状态的退款才改变资金事实。",
    ),
    RelationDef(
        name="hasComplaint",
        domain="Customer", range="ComplaintTicket", cardinality="1:N",
        business_meaning="客户关联投诉工单",
        semantics_note="工单描述（如『疑似重复扣费』）是用户主观主张，不是已核实的处理结论。",
    ),
]


def describe_relations() -> str:
    """以文本形式呈现全部关系定义，供 Agent 工具返回。"""
    lines = []
    for r in RELATION_REGISTRY:
        lines.append(
            f"- {r.name}: {r.domain} -> {r.range} ({r.cardinality})\n"
            f"  业务含义: {r.business_meaning}\n"
            f"  语义注意: {r.semantics_note}"
        )
    return "\n".join(lines)
