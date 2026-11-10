# 话费重复扣费核查 Agent（Ontology + OpenAI Agents SDK）

复现文章《RAG、GraphRAG、Ontology、Agent，到底谁才是企业 AI 的关键？》中的
电信运营商场景：用户问「我的话费是不是被重复扣了？」，Agent 不能仅凭
「两笔 100 元」下结论，而是沿着**本体定义的业务对象与关系**收集证据，
由**业务规则引擎**给出分级结论（已确认事实 / 异常线索 / 未知信息）。

## 目录结构

```
telecom_ontology_agent/
├── ontology/               # 本体语义层（文章第 02/03/04 节）
│   ├── classes.py          #   类与属性：Customer/Account/PhoneNumber/Plan/
│   │                       #   Bill/PaymentTransaction/ReversalTransaction/
│   │                       #   RefundTransaction/ComplaintTicket
│   │                       #   + 独立状态维度（账单状态/支付状态/冲正状态/退款状态）
│   ├── relations.py        #   关系：hasAccount/hasPhoneNumber/hasBill/
│   │                       #   settlesBill/reversesTransaction/refundsTransaction/hasComplaint
│   └── rules.py            #   业务规则引擎：R1 金额相同不是证据 / R2 状态维度 /
│                           #   R3 情形判定 / R4 证据不足返回 UNKNOWN / R5 结论分级
├── systems/                # 模拟企业系统（各自独立 SQLite 库，标识互不相通）
│   ├── db.py               #   CRM / BSS / 计费 / 支付 / 客服 / MDM 六库 + 查询接口
│   └── seed.py             #   文章 STEP 06 的六组验证样本
├── tools/query_tools.py    # Agent 只读工具（带来源系统与查询时间；全部按 ID 查询均做会话归属校验）
├── agent.py                # OpenAI Agents SDK 装配（五步核查工作流注入指令）
├── demo_scenario.py        # 无 LLM 的确定性验证：六组样本跑规则引擎
├── main.py                 # CLI 入口：复现「我的话费是不是被重复扣了？」
└── article_extract/        # 原文提取（供对照）
```

## 本体建模要点（与文章一一对应）

| 文章概念 | 代码体现 |
|---|---|
| 类 vs 实例 | `ontology/classes.py` 的 dataclass 是类；`B-3105`、`P-7781` 是实例 |
| 支付成功 ≠ 账单结清 ≠ 退款完成 | `BillStatus` / `PaymentStatus` / `RefundStatus` 三个独立枚举 |
| settlesBill 只是「关联」不是「已结算」 | `PaymentTransaction.bill_ref` + 状态维度分开表达 |
| 金额相同不是证据 | 规则 R1：判定只走 settlesBill 权威关联 |
| 冲正/退款存在 ≠ 已生效 | 规则 R2：只有 `COMPLETED` 才改变资金事实 |
| 跨系统标识不强行统一 | 六库独立主键，靠 MDM `verified_links` 经过验证的映射 |
| 关联缺失不得臆断 | 规则 R4：返回 UNKNOWN / 未知项 |
| 只读权限边界 | 工具全部只读；Agent 只能建议转人工，不得承诺已退款 |

## 六组验证样本（文章 STEP 06）

| 客户 | 场景 | 期望结论 |
|---|---|---|
| 张伟 C-1001 | 两笔 100 元分属本月/上月不同账单 | NOT_DUPLICATE |
| 李娜 C-1002 | 同一账单两笔成功扣款，无冲正/退款 | SUSPECTED_DUPLICATE |
| 王强 C-1003 | 同一账单两笔扣款，一笔已 COMPLETED 冲正 | NOT_DUPLICATE |
| 赵敏 C-1004 | 同一账单两笔扣款，一笔退款 REQUESTED 中 | SUSPECTED_DUPLICATE + 未知项 |
| 陈晨 C-1005 | 一人多账户，扣款分属移动/宽带 | NOT_DUPLICATE |
| 刘洋 C-1006 | 存在 settlesBill 关联缺失的交易 | UNKNOWN + 未知项 |

## 快速开始

```powershell
# 1. 创建 venv 并安装依赖
cd telecom_ontology_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. 确定性验证（不需要 LLM，直接验证本体+规则引擎）
python demo_scenario.py

# 3. 运行 Agent（复现「我的话费是不是被重复扣了？」）
python main.py                          # 默认：李娜（情形 B）
python main.py --customer 张伟          # 文章开头的「陷阱案例」：两笔100元但非重复
python main.py --customer 王强          # 已冲正
python main.py --customer 赵敏          # 退款处理中
python main.py --customer 陈晨          # 一人多账户
python main.py --customer 刘洋          # 关联缺失
```

## 大模型配置

从 `.env` 读取（默认查找顺序：环境变量 `ENV_FILE` 显式指定的文件 → 项目内 `.env`）：

```
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

也兼容 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`。
SDK 通过 `chat_completions` API 接入，支持任意 OpenAI 兼容端点。
配置的模型不存在时自动回退 `deepseek-chat`（回退通过参数直传，不受 `.env` 覆盖影响）。
