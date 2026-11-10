# -*- coding: utf-8 -*-
"""
Agent 装配（OpenAI Agents SDK）
================================

按照文章第 05 节的完整核查流程组织 Agent 行为：

    用户问题 → 定位客户与账户 → 查询账单 → 查询支付
             → 核对关联关系与状态 → 检查异常 → 输出带证据的结论

大模型配置：从 .env 读取 DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL
（OpenAI 兼容端点），通过 chat_completions API 接入 OpenAI Agents SDK。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

from agents import (
    Agent,
    Runner,
    function_tool,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from agents.exceptions import AgentsException

from tools import query_tools as qt

# ---------------------------------------------------------------------------
# 指令：把本体语义 + 核查工作流 + 判断纪律写进系统提示
# ---------------------------------------------------------------------------
INSTRUCTIONS = """你是电信运营商的客服核查 Agent，专门协助用户核对「话费是否被重复扣取」。

【业务本体】你必须严格按以下业务语义理解和组织查询：
- Customer（客户，CRM 权威）—hasAccount→ Account（业务账户，BSS 权威，客户与账户非一一对应）
- Account —hasBill→ Bill（账单：计费周期、应收金额、账单状态；计费系统权威）
- PaymentTransaction（支付交易）—settlesBill→ Bill：仅表示交易被系统关联到该账单，不等于账单已成功结算
- ReversalTransaction —reversesTransaction→ 原始交易：只有 COMPLETED 冲正才使原交易失效
- RefundTransaction —refundsTransaction→ 原始交易：只有 COMPLETED 退款才改变资金事实
- Customer —hasComplaint→ ComplaintTicket：工单描述是用户主观主张，非已核实事实
- 支付成功、账单结清、退款完成是三个不同的业务事实，状态维度必须分开看。

【判断纪律】（违反任何一条都是严重错误）
1. 金额相同 ≠ 重复扣费；客户相同 ≠ 交易属于同一笔业务。严禁仅凭金额/时间相似下结论。
2. 判断只能基于 settlesBill 权威关联 + 交易状态 + 冲正/退款状态。
3. 接口没提供的信息（如关联缺失），明确列为「未知/待核实」，不得自行脑补。
4. 你的结论必须分级：已确认事实 / 异常线索 / 未知信息。
5. 你是只读 Agent：无权退款、无权修改账单，只能给出核查结论与后续建议，不得承诺「已退款」「问题已解决」。

【标准核查流程】（按顺序执行，每步调用相应工具）
STEP 1  确认客户与账户：get_current_customer → get_verified_accounts。
        若客户名下有多个账户，先向用户说明并分别核查，不得混在一起。
STEP 2  查询目标账单：list_bills 定位用户所说计费周期的账单（金额、账单状态）。
STEP 3  查询关联支付：对每张目标账单 list_bill_payments；同时 list_account_payments
        检查是否存在关联缺失的流水；对可疑交易 get_transaction_adjustments 查冲正/退款。
STEP 4  规则判定：对每张目标账单调用 check_duplicate_billing，以规则引擎结论为准，
        不得绕过规则引擎自行判定。
STEP 5  输出可追溯的回答，格式：
        【结论】未发现重复扣费证据 / 疑似重复扣费需核实 / 证据不足无法确认
        【核查过程】客户→账户→账单→支付 的核对路径
        【证据清单】每条证据注明来源系统与对象编号
        【未知与待核实】（没有则写「无」）
        【后续建议】如转人工核查、向支付渠道核对清算状态等（只建议，不执行）
        最后用一段自然、有同理心的话向用户总结，不要堆砌术语。
"""

_FALLBACK_MODEL = "deepseek-chat"


def _load_config(env_file: str | None) -> tuple[str, str, str]:
    """返回 (api_key, base_url, model)。"""
    if env_file:
        load_dotenv(env_file, override=True)
    else:
        # 默认：ENV_FILE 显式指定的配置优先，其次使用项目内 .env
        candidates = []
        if configured_env_file := os.getenv("ENV_FILE"):
            candidates.append(Path(configured_env_file))
        candidates.append(Path(__file__).resolve().parent / ".env")
        for c in candidates:
            if c.exists():
                load_dotenv(c, override=True)
                break

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    base_url = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com"
    )
    model = os.getenv("OPENAI_MODEL") or os.getenv("DEEPSEEK_MODEL") or _FALLBACK_MODEL
    if not api_key:
        raise RuntimeError("未找到 API Key：请在 .env 中配置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY")
    return api_key, base_url, model


def build_agent(
    env_file: str | None = None, model_override: str | None = None
) -> tuple[Agent, str]:
    """构建 Agent，返回 (agent, model_name)，可显式覆盖配置的模型。"""
    api_key, base_url, model = _load_config(env_file)
    if model_override:
        model = model_override

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    set_default_openai_client(client, use_for_tracing=False)
    set_default_openai_api("chat_completions")  # 非 OpenAI 端点只支持 Chat Completions
    set_tracing_disabled(True)  # 非 OpenAI 端点无法导出 trace，避免告警噪音

    agent = Agent(
        name="话费核查Agent",
        instructions=INSTRUCTIONS,
        model=model,
        tools=[
            function_tool(qt.describe_ontology),
            function_tool(qt.get_current_customer),
            function_tool(qt.get_verified_accounts),
            function_tool(qt.get_account_details),
            function_tool(qt.list_bills),
            function_tool(qt.get_bill),
            function_tool(qt.list_bill_payments),
            function_tool(qt.list_account_payments),
            function_tool(qt.get_transaction_adjustments),
            function_tool(qt.list_complaint_tickets),
            function_tool(qt.check_duplicate_billing),
        ],
    )
    return agent, model


async def run_query(question: str, env_file: str | None = None) -> str:
    """运行一次核查问答，返回 Agent 的最终回答。模型不可用时自动回退。"""
    agent, model = build_agent(env_file)
    try:
        result = await Runner.run(agent, question)
    except AgentsException as e:
        # 仅在模型不存在类错误时回退到 deepseek-chat
        error_message = str(e).lower()
        model_missing = any(
            message in error_message
            for message in ("model not found", "model does not exist", "invalid model")
        )
        if model_missing and model != _FALLBACK_MODEL:
            agent, model = build_agent(env_file, model_override=_FALLBACK_MODEL)
            result = await Runner.run(agent, question)
        else:
            raise
    return result.final_output
