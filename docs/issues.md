# 5 个 Issue 现成文本（GitHub 创建用）

> 由于 GitHub 插件（GitHub App）没有被授权到 xiaoLin12130 账号，插件无法自动创建 issue。
> 方式一：手动创建——逐个复制下方每个「Issue #N」的全文，粘贴到 GitHub 新建 issue 页面（标题 + 正文）。
> 方式二：提供 fine-grained PAT 后由主 agent 自动创建。

---

## Issue #1

标题：`[模块1] 交割单解析器（parser）`

正文：

## 背景
synalysis_crew：基于同花顺交割单的 A 股交易分析系统。需求文档：`docs/requirements.md`（仓库内，已定稿）。

## 写权限（只允许改这些文件）
- `src/synalysis_crew/__init__.py`
- `src/synalysis_crew/parser.py`
- `tests/test_parser.py`
- `tests/fixtures/synthetic_trades.py`

禁止：改 pyproject.toml/.gitignore/.env（主 agent 预置）；动 `data/` 真实 xlsx；`git commit/push`。

## 功能要求
1. `TradeRecord` dataclass：字段 `code, name, op_type, qty, price, amount, balance, fee, stamp_tax, commission, transfer_fee, contract_no, trade_date, currency` + `to_dict()`；`op_type` 枚举：BUY / SELL / BANK_TO_SEC / SEC_TO_BANK / REPO / INTEREST / DIVIDEND / BONUS_SHARE / DIVIDEND_DIFF / DESIGNATED_TRADE / UNKNOWN
2. `parse_trades(path) -> list[TradeRecord]`：支持 .xlsx（openpyxl 为主）、.xls/.csv 尽力而为；列名自动识别（同花顺标准列，容忍列序变化与表头空格，参考 `data/20251127-20260731.xlsx`）
3. 脏数据容错：空行跳过；日期兼容 int(20251127)/datetime/str；金额为 0 保留；未知操作归 UNKNOWN 不报错
4. 错误处理：文件不存在/不可解析时抛中文信息自定义异常
5. `tests/fixtures/synthetic_trades.py`：提供 `make_trades()`（覆盖 10 种操作的 TradeRecord 列表，含"中途开始"场景）和 `build_xlsx(path)`（生成临时 xlsx 供 parser 测试）

## 验收
- `python -m pytest tests/test_parser.py` 全绿（用系统 Python，依赖已装；不要运行 uv sync / pip install）
- 本地验证 `data/all.xlsx`、`data/20251127-20260731.xlsx` 解析 0 报错（只读验证，不提交）
- 合成夹具覆盖全部操作类型

---

## Issue #2

标题：`[模块2] 指标计算引擎（含翻倍/腰斩次数）`

正文：

## 背景
同花顺交割单分析系统的指标层。需求文档 `docs/requirements.md` 2.3 节（32 项指标，已确认）。

## 写权限（只允许改这些文件）
- `src/synalysis_crew/metrics.py`
- `tests/test_metrics.py`

禁止：改 parser.py 等他人文件；`git commit/push`；动 `data/` 真实数据。
只读契约：`TradeRecord` 字段见需求文档第 4 章；parser 未落地前测试用本地 stub 记录（若 `tests.fixtures.synthetic_trades` 已存在可复用，否则在测试文件内自建最小 stub，不要创建 fixtures 文件）。

## 功能要求
`compute_metrics(trades: list[TradeRecord]) -> MetricsResult`（固定 JSON schema，字段全英文 snake_case）：
- A 账户总览：统计区间、期初/期末资金（资金余额口径）、净转入（银行转证券−证券转银行）、总收益率、年化收益率、累计已实现盈亏、总交易成本及占比、持仓市值/浮动盈亏（akshare 拉最新价，失败/未安装时按成本兜底并标记 `market_value_source="cost"`）
- B 交易统计：总成交金额/笔数、买卖拆分、日均笔数/成交额、去重股票数、当前持仓只数、平均单笔金额、资金周转率、平均持仓周期
- C 盈亏分析（FIFO 配对，买入费用入成本、卖出费用扣净额）：已实现盈亏、胜率、盈亏比、最大单笔盈亏、**翻倍次数**（个股完整持仓周期收益率≥+100%）、**腰斩次数**（≤-50%）、月度盈亏序列、累计收益曲线+最大回撤、个股盈亏榜 Top10
- D 行为画像：持仓周期分布（≤1/2–5/6–20/>20 天）、月度活跃度、单票最大仓位、Top5 成交额集中度、偏爱个股 Top10、风格初判（短线/波段/长线 × 集中/分散，规则引擎）+ 特殊操作统计
- 区间口径：期初资金≠0 时 `is_partial=True`，页面据此标注"区间收益"

## 验收
- `python -m pytest tests/test_metrics.py` 全绿（系统 Python；不要 uv sync / pip install）
- 合成数据手算抽查一致：胜率、盈亏比、最大回撤、翻倍/腰斩次数
- 对 `data/all.xlsx`（总收益口径）与 `data/20251127-20260731.xlsx`（区间口径）本地跑通

---

## Issue #3

标题：`[模块3] AI 分析模块（LangGraph 分析师讨论 + 单份报告）`

正文：

## 背景
复用 `H:\stock_review_crew\skills` 的 5 位分析师（阿狼/爱在冰川/拔小弦/炒股养家/铁锤狂砸盘），用 LangGraph 跑「分析师并行 → 主持人找分歧 → 辩论 → 单份最终报告」，对齐 stock_review_crew 的 graph 模式。需求文档 `docs/requirements.md` 第 3 章 Issue #3。

## 写权限（只允许改这些文件）
- `src/synalysis_crew/llm.py`
- `src/synalysis_crew/analyst.py`
- `src/synalysis_crew/state.py`
- `src/synalysis_crew/graph.py`
- `tests/test_analyst.py`

禁止：改他人文件；`git commit/push`；动 `data/` 真实数据；不引入 langfuse（无 key）。

## 环境
- `.env` 已配置：`DEEPSEEK_API_KEY`、`DEEPSEEK_API_BASE=https://opencode.ai/zen/go/v1`、`DEEPSEEK_MODEL=deepseek-v4-flash`（可被环境变量覆盖）
- 系统 Python 已装 langgraph / langchain-openai / python-dotenv

## 功能要求
1. `llm.py`：`llm`（temperature 0.7）与 `llm_strict`（0.1），ChatOpenAI 指向 DEEPSEEK_API_BASE，模型 DEEPSEEK_MODEL；不 import langfuse
2. `analyst.py`：
   - 加载 skills：`STOCK_REVIEW_CREW_SKILLS_DIR` 环境变量，默认 `H:\stock_review_crew\skills`；目录不存在时降级 `assets/skills`（自动复制并提示）
   - `build_profile(trades, metrics) -> str`：**脱敏**画像（只有代码/名称/数量/价格/日期 + 指标摘要；严禁出现 contract_no、资金余额、银行转账）
   - `DISCLAIMER = "仅供参考，不构成投资建议"`，报告末尾程序级强制追加（LLM 忘写也要补）
3. `state.py` + `graph.py`（LangGraph StateGraph）：profile → analysts（5 人 ThreadPool 并行，max_workers=5）→ host（分歧判断）→ debate（循环，max_rounds 默认 2）→ report（**只输出一份** Markdown）
   - 报告结构：账户概况 → 各分析师核心观点 → 分歧与讨论 → 操作意见 → 幽默标签（2–4 个，风趣不死板）→ 风险提示 → 免责声明
4. `analyze(trades, metrics, max_rounds=2) -> AnalysisResult`：`{final_report, analysts[], debate_history[], overall_tags[], disclaimer, degraded, round_count}`
5. 降级：无 Key/网络失败时规则引擎兜底（基于指标出点评+标签+免责声明），`degraded=True`，绝不抛异常

## 验收
- `python -m pytest tests/test_analyst.py` 全绿（无 Key 路径）
- 有 Key 时完整跑通 分析师→辩论→报告，最终仅一份报告
- 检查 prompt 内容不含 contract_no/资金余额（测试断言）

---

## Issue #4

标题：`[模块4] 前端展示（Streamlit，Codex 风格 + 历史记录）`

正文：

## 背景
交割单分析的前端。需求文档 `docs/requirements.md` 第 3 章 Issue #4。风格要求：简单但不难看，贴近 Codex 桌面端（深色侧栏 + 浅色内容区 + 细边框 + 圆角 + 单一强调色），左侧保留历史分析。

## 写权限（只允许改这些文件）
- `app.py`
- `src/synalysis_crew/ui.py`
- `src/synalysis_crew/storage.py`

禁止：改他人模块（parser/metrics/analyst/graph）；`git commit/push`；动 `data/` 真实数据。
只读契约：`parse_trades(path)` / `compute_metrics(trades)` / `analyze(trades, metrics, max_rounds=2)`（见需求文档第 4 章）；开发期用内置 mock 数据，不要依赖其他模块已落地。

## 功能要求
1. `storage.py`：分析记录存 `data/analyses/{时间戳}/`（meta.json + metrics.json + analysis.json）；`save_analysis(meta)` / `list_analyses()` / `load_analysis(id)`；`data/` 已在 .gitignore
2. `app.py` + `ui.py`（Streamlit + Plotly，中文界面）：
   - 左侧深色侧栏：历史分析列表（时间/文件名/收益率/总标签），点击回看；顶部「新建分析」+ 交割单上传（xlsx）
   - 主区 Tabs：
     a) 账户总览：KPI 卡片（总收益率/年化/已实现盈亏/胜率/最大回撤/总成本等）+ 累计收益曲线 + 月度盈亏柱状图
     b) 交易明细：可筛选表格（股票/时间范围）
     c) 盈亏分析：盈亏分布、翻倍/腰斩次数醒目展示、个股盈亏榜
     d) 行为画像：持仓周期分布、月度活跃度、风格标签
     e) AI 报告：Markdown 报告 + 幽默标签徽章 + 免责声明醒目展示
   - 区间口径（is_partial）时明确标注「区间收益」；持仓市值按成本估算时标注
   - 断网/无 Key：AI 区显示 degraded 兜底结果，不报错
3. 不引入额外 UI 框架；整体简洁、留白充足

## 验收
- `streamlit run app.py` 启动无报错（系统 Python 已装 streamlit/plotly；不要 uv sync / pip install）
- 用 mock 数据全流程走通；历史记录可切换回看；侧栏样式贴近 Codex 桌面端

---

## Issue #5

标题：`[模块5] 测试、文档与联调收尾（Wave 2）`

正文：

## 背景
Wave 2 收尾任务：在 Wave 1 四个模块（parser/metrics/AI-LangGraph/前端）落地并经过主 agent 审核后执行。

## 写权限（只允许改这些文件）
- `README.md`
- `tests/test_e2e.py`
- `scripts/run.ps1`
- `tests/fixtures/` 补充（如需）

集成修复若涉及其他模块文件，先与主 agent 确认再改。禁止 `git commit/push`；禁止把真实交割单写入仓库。

## 功能要求
1. `README.md`：项目介绍、快速启动（`streamlit run app.py`）、环境变量表（DEEPSEEK_*）、目录结构、隐私说明（真实交割单不进 git）
2. `scripts/run.ps1`：一键启动（检查 .env → 启动 Streamlit）
3. `tests/test_e2e.py`：合成数据端到端：parse → metrics → analyze（无 Key 兜底）→ storage 存取
4. 联调：修复 Wave 1 遗留的集成问题（import 路径、schema 不一致、字段命名等），改动范围先与主 agent 确认

## 验收
- `python -m pytest` 全绿（系统 Python；不要 uv sync / pip install）
- README 步骤可完整跑通全流程
