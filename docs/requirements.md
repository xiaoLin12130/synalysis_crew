# Synalysis Crew — 需求分析文档（v0.1 待审核）

> 状态：**已定稿（2026-08-02 用户确认）**。按本文档拆分为 GitHub issues，并交给多 agent 并行开发。
> 日期：2026-08-02

## 一、项目背景

用户持有同花顺导出的交割单（xlsx），需要：

1. 解析交割单，计算常见账户/交易/盈亏/行为指标；
2. 前端以「图表 + 文字」展示分析结果；
3. 复用 `H:\stock_review_crew` 项目的 5 位分析师 Skill（阿狼、爱在冰川、拔小弦、炒股养家、铁锤狂砸盘），对用户操作进行点评、给出意见、打上幽默标签，并**必须**附带"仅供参考"提示；
4. 页面风格：简单但不难看，贴近 Codex 桌面端风格，左侧保留历史分析记录。

## 二、数据与口径

### 2.1 交割单结构（同花顺标准导出，已用样本验证）

| 列 | 说明 |
|---|---|
| 证券代码 / 证券名称 / 证券中文全称 | 标的 |
| 操作 | 证券买入 / 证券卖出 / 银行转证券 / 证券转银行 / 通用回购逆回 / 利息归本 / 红利入账 / 红股入账 / 股息红利差异 / 指定交易 |
| 成交数量 / 成交均价 / 成交金额 / 股票余额 | 成交信息 |
| 发生金额 | 资金变动（买入为负、卖出为正） |
| 手续费 / 印花税 / 佣金 / 过户费 / 其他杂费 | 交易成本 |
| 资金余额 | 成交后现金余额（用于推算期初/期末资金） |
| 交收日期 | 交易日 |
| 合同编号 / 币种 | 其他 |

样本文件（仅本地使用，**不提交 GitHub**）：

- `data/all.xlsx`：5176 行，2023-12-11 ~ 2026-07-31，约 798 只股票，买卖金额约 ±1430 万（完整历史，期初资金≈0）；
- `data/20251127-20260731.xlsx`：1016 行，2025-11-27 ~ 2026-07-31，174 只股票（中途开始，期初有持仓/资金，只能算"区间口径"）。

### 2.2 计算口径假设（需用户确认）

- **H1 覆盖区间**：指标以交割单文件覆盖区间为统计范围。若文件从账户中途开始（期初资金≠0 或期初有持仓），页面明确标注"区间收益"，不冒充总收益；完整文件（期初资金=0）则显示"总收益"。
- **H2 已实现盈亏**：同股票先进先出（FIFO）配对；买入费用计入买入成本，卖出费用从卖出净额扣除。
- **H3 持仓市值**：期末持仓市值优先用实时行情（akshare 拉最新收盘价）；无网络/失败时用持仓成本市值兜底，并在页面上标注"按成本估算"。
- **H4 数据隐私**：AI 分析只发送"指标摘要 + 个股级统计（代码/名称/数量/均价/日期）"，**绝不发送合同编号、资金余额、银行转账明细**；原始交割单只存本地。
- **H5 测试数据**：自动化测试使用**合成交割单**（含买卖/分红/逆回购/中途开始等边界场景），用户真实 xlsx 仅作手动验收，不进入 git。

### 2.3 指标清单（已确认，共 32 项）

#### A. 账户总览（8 项）
1. 统计区间（首末交易日）
2. 期初资金 / 期末资金（资金余额口径）
3. 净转入资金（银行转证券 − 证券转银行）
4. 总收益率 = (期末资金 + 期末持仓市值 − 期初资金 − 净转入) / 期初资金（按 H1 标注口径）
5. 年化收益率（按区间天数折算）
6. 累计已实现盈亏（FIFO，含费用）
7. 总交易成本（手续费 + 印花税 + 佣金 + 过户费 + 杂费）及占成交额比例
8. 期末持仓市值 / 浮动盈亏（H3 口径）

#### B. 交易统计（7 项）
9. 总成交金额、总笔数
10. 买入笔数/金额、卖出笔数/金额
11. 日均交易笔数、日均成交额
12. 交易股票数（去重）、当前持仓只数
13. 平均单笔金额
14. 资金周转率 = 总成交额 / 平均资金余额
15. 平均持仓周期（FIFO 配对，天数）

#### C. 盈亏分析（9 项）
16. 已实现盈亏总额（含费用）
17. 盈利笔数 / 亏损笔数 / 胜率（按卖出配对笔数）
18. 总盈利金额 / 总亏损金额 / 盈亏比
19. 最大单笔盈利 / 最大单笔亏损
20. **翻倍次数**：按个股完整持仓周期（首次买入→清仓，FIFO 汇总）收益率 ≥ +100% 的次数（仍持仓的按成本 vs 最新价估算）
21. **腰斩次数**：个股完整持仓周期收益率 ≤ -50% 的次数（口径同上）
22. 月度盈亏序列（时间序列图）
23. 累计收益曲线 + 最大回撤（基于月末资产近似净值）
24. 个股盈亏榜 Top10（盈利 / 亏损）

#### D. 行为画像（6 项）
23. 持仓周期分布（≤1 天 / 2–5 天 / 6–20 天 / >20 天）
24. 月度交易活跃度（每月笔数）
25. 单票最大仓位（占资金比例）
26. 交易集中度（Top5 股票成交额占比）
27. 偏爱个股 Top10（按交易次数）
28. 风格初判（规则引擎：短线/波段/长线、集中/分散、激进/稳健）+ 特殊操作统计（逆回购/分红/打新记录）

#### E. AI 分析（2 项）
29. 5 位分析师个人点评 + 个人标签（幽默风格，规则兜底 + LLM 生成）
30. 综合分析报告 + 总标签 + 风险提示 + **"仅供参考，不构成投资建议"免责声明（必须出现）**

## 三、功能模块拆分（对应 5 个 GitHub Issue）

### Issue #1：项目脚手架 + 交割单解析器
- 结构：`src/synalysis_crew/parser.py`、`pyproject.toml`（uv）、`.gitignore`（排除 `data/*.xlsx`、`.env`、`output/`）
- 功能：读取 xlsx（兼容 xls/csv 尽力而为）；列名自动识别（容忍列序变化）；操作分类归一（买卖/资金转账/逆回购/分红等）；异常与脏数据容错（空行、日期格式、金额为 0）；返回 `TradeRecord` 列表（dataclass + `to_dict()`）
- 验收：对两个真实样本解析 0 报错；合成用例覆盖 10 种操作类型；非法文件给出中文错误提示

### Issue #2：指标计算引擎
- 结构：`src/synalysis_crew/metrics.py`
- 功能：按 2.3 清单实现 A/B/C/D 全部指标；FIFO 配对器（含费用分摊、拆分红股调整）；月度/年度聚合；输出固定 JSON Schema（`MetricsResult`），字段名全英文 snake_case
- 验收：对 `data/all.xlsx` 与合成数据跑通；胜率/盈亏比/最大回撤手算抽查一致；中途开始文件正确标注"区间口径"

### Issue #3：AI 分析模块（LangGraph + stock_review_crew Skills）
- 结构：`src/synalysis_crew/llm.py`、`src/synalysis_crew/analyst.py`、`src/synalysis_crew/state.py`、`src/synalysis_crew/graph.py`
- 功能：
  - Skill 加载：读取 `STOCK_REVIEW_CREW_SKILLS_DIR`（默认 `H:\stock_review_crew\skills`），找不到时降级到项目内 `assets/skills` 副本（提供同步脚本）
  - **LangGraph 流程（参照 stock_review_crew 的 graph 模式）**：profile 节点（组装脱敏交易画像）→ 5 位分析师并行节点（ThreadPool，max_workers=5）→ 主持人节点（判断分歧、提炼议题）→ 辩论节点（循环，max_rounds 默认 2）→ 报告节点（**只输出一份**最终 Markdown 报告）
  - 最终报告结构：账户概况 → 各分析师核心观点 → 分歧与讨论 → 操作意见 → 幽默标签 → 风险提示；程序级强制追加"仅供参考，不构成投资建议"（LLM 忘写也要补）
  - 降级：无 API Key / 调用失败时输出规则引擎兜底点评与标签，不阻塞前端
- 验收：无网络/无 Key 时功能可用；有 Key 时完整跑通「分析师→辩论→报告」；最终只产出一份报告；标签幽默且含免责声明；合同编号等敏感字段不出现在 prompt 中

### Issue #4：前端展示（Streamlit + Codex 风格）
- 结构：`app.py`、`src/synalysis_crew/ui.py`、`src/synalysis_crew/storage.py`
- 功能：
  - 上传交割单 → 解析 → 指标 → AI 分析 → 保存历史
  - 左侧深色侧栏：历史分析列表（时间/文件/总标签/收益率摘要），点击切换查看；顶部"新建分析"
  - 主区 Tab：账户总览（KPI 卡片 + 累计收益曲线 + 回撤）、交易明细（可筛选表格）、盈亏分析（月度盈亏柱状图 + 胜率 + 盈亏分布）、行为画像（持仓周期分布 + 活跃度 + 风格标签）、AI 分析（5 位分析师折叠卡片 + 综合报告 + 幽默标签 + 免责声明）
  - 图表用 Plotly；中文字体；自定义 CSS 贴近 Codex 桌面端（深色侧栏 + 浅色内容区 + 细边框 + 圆角 + 单一强调色）
  - 历史记录存 `data/analyses/{时间戳}/`（metrics.json + analysis.json + 摘要），侧栏即时读取
- 验收：上传两个真实样本均能完整走通；断网时 AI 区显示兜底结果；历史记录可切换回看

### Issue #5：测试、文档与联调收尾
- 功能：pytest 单元测试（parser/metrics/FIFO/兜底逻辑）、合成数据夹具、README（启动步骤、环境变量、目录说明）、`.env.example`、一键启动脚本；Wave 2 阶段负责端到端联调、修复集成问题
- 验收：`uv run pytest` 全绿；README 按步骤可跑通全流程

## 四、接口契约（跨模块，供并行开发对齐）

```
TradeRecord:  code, name, op_type(枚举), qty, price, amount, balance,
              fee, stamp_tax, commission, transfer_fee, contract_no(脱敏),
              trade_date, currency

parse_trades(path) -> list[TradeRecord]
compute_metrics(trades) -> MetricsResult   # 固定 JSON Schema（含翻倍/腰斩次数）
analyze(trades, metrics, max_rounds=2) -> AnalysisResult
  AnalysisResult: { final_report(仅一份 Markdown),
                    analysts[], debate_history[],
                    overall_tags[], disclaimer, degraded, round_count }

storage: save_analysis(timestamp, meta) / list_analyses() / load_analysis(id)
前端只依赖 parse_trades / compute_metrics / analyze / storage。
```

## 五、多 Agent 开发方案（并发 ≤ 5，防冲突设计）

### 5.1 文件所有权表（每个 agent 只允许写自己名下的文件）

| Agent | Issue | 唯一写权限 | 只读依赖 |
|---|---|---|---|
| A1 | #1 解析器 | `src/synalysis_crew/__init__.py`、`src/synalysis_crew/parser.py`、`tests/test_parser.py`、`tests/fixtures/synthetic_trades.py` | 无 |
| A2 | #2 指标引擎 | `src/synalysis_crew/metrics.py`、`tests/test_metrics.py` | `TradeRecord` 契约（#1 定义，未落地前用本地 stub） |
| A3 | #3 AI 分析（LangGraph） | `src/synalysis_crew/llm.py`、`analyst.py`、`state.py`、`graph.py`、`tests/test_analyst.py` | `MetricsResult` 契约（#2）、`H:\stock_review_crew\skills`（只读） |
| A4 | #4 前端 | `app.py`、`src/synalysis_crew/ui.py`、`src/synalysis_crew/storage.py` | 5 个公共函数契约（见第 4 章，开发期用 mock） |
| A5（Wave 2） | #5 联调收尾 | `README.md`、`tests/test_e2e.py`、`scripts/run.ps1`、合成数据夹具补充 | 全部模块；**集成修复需主 agent 确认后才能改其他文件** |

> `pyproject.toml`、`.gitignore`、`.env.example`、`.env` 由主 agent 预置，任何 agent 不得修改；
> 任何 agent 不得执行 `git commit`/`git push`、不得修改 `data/` 下真实交割单、不得把真实数据写入仓库。

### 5.2 交接与防冲突规则

- 契约（第 4 章）是各模块间唯一接口，并行期禁止互相读源码细节、禁止改他人文件；
- A2 在 parser 落地前用本地 stub 数据开发测试；A3/A4 用固定 JSON/mock 开发；
- Wave 1 完成后由主 agent（我）逐个审核、跑测试、解决集成冲突并提交；任何交叉问题记入 issue 评论，供 Wave 2 处理；
- Wave 2 只允许 A5 修改 README/测试/脚本，集成修复先经我确认；
- 峰值并发 4（Wave 1），低于 5 上限；全程在对话中汇报每个 agent 的运行轨迹。

## 六、技术栈

- Python 3.13 + uv（与 stock_review_crew 一致）
- Streamlit + Plotly + pandas + openpyxl
- langchain-openai + DeepSeek（复用 stock_review_crew 的 config 模式；`.env` 从 stock_review_crew/.env 复制 DEEPSEEK_* 变量）
- 引入 LangGraph（langgraph + langchain-openai + langfuse 可选）：分析师并行 → 主持人 → 辩论循环 → 单份最终报告，流程对齐 stock_review_crew；`max_rounds` 默认 2 控制 token 消耗

## 七、GitHub 仓库与 Issue

- 现状：`H:\synalysis_crew` 不是 git 仓库；GitHub 插件提供 create_issue 等能力，但**无创建仓库工具**。
- 方案：用户手动在 GitHub 创建 **private** 空仓库（如 `synalysis_crew`），我负责本地 `git init`、push、按本文档创建 5 个 issue（含详细验收标准），后续 agent 按 issue 开发。
- 真实交割单与 `.env` 一律不进 git（`.gitignore` 强制）。

## 八、确认记录（2026-08-02 用户确认）

1. ✅ 指标清单：接受 30 项，**新增翻倍次数、腰斩次数**（口径见 2.3 第 20/21 项）
2. ✅ 口径假设 H1–H5 接受
3. ✅ 技术栈：**改用 LangGraph**，分析师讨论后汇总，只出一份报告，类似 stock_review_crew
4. ✅ 模块拆分 5 个 issue + 两波 agent（4 + 1），**任务分配按 5.1 文件所有权表防冲突**
5. ⏳ GitHub：private 空仓库由用户手动创建（插件无建仓能力），待用户提供 URL
6. ✅ 真实交割单不提交仓库，测试用合成数据

## 九、详细操作步骤（执行顺序）

1. 需求文档定稿（本文档）——✅ 已完成
2. 用户创建 GitHub private 空仓库（不勾选 README/.gitignore），把 URL 发给我
3. 主 agent：本地 `git init` + 写 `.gitignore`（排除 `data/*.xlsx`、`.env`、`output/`、`.venv`、`__pycache__`）+ 首次 commit + push
4. 主 agent：从 `stock_review_crew/.env` 复制 `DEEPSEEK_*` 到本项目 `.env`（gitignored，仅本地）
5. 主 agent：按第 3 章创建 5 个 issue（正文含验收标准 + 文件所有权表）
6. Wave 1：spawn 4 个 agent（A1–A4）并行开发，每个 agent 一份 issue + 契约 + 所有权说明；对话中实时汇报进度
7. 主 agent 审核：跑 `pytest`、逐文件 review、修复集成冲突、commit
8. Wave 2：spawn 1 个 agent（A5）补测试/文档/联调脚本
9. 最终验收：`uv run pytest` 全绿；`streamlit run app.py` 上传真实样本全流程走通
10. 交付说明 + 使用文档
