# Synalysis Crew — 同花顺交割单分析套件

Synalysis Crew 是一款本地优先的 A 股交易分析工具：上传同花顺导出的交割单
（xlsx / xls / csv），自动完成 **解析 → 指标计算 → AI 分析师点评 → 历史存档**，
在 Streamlit 前端以「图表 + 文字」呈现账户总览、交易统计、盈亏分析与行为画像。

AI 分析复用 `stock_review_crew` 的 5 位分析师 Skill（阿狼 / 爱在冰川 / 拔小弦 /
炒股养家 / 铁锤狂砸盘），用 LangGraph 编排「画像 → 5 路并行点评 → 主持人找分歧 →
辩论循环 → 单份最终报告」流程，最终报告带幽默标签、风险提示与免责声明。
没有 DeepSeek API Key 或断网时自动降级为规则引擎点评，前端功能不受影响。

## 快速开始

前置条件：Python 3.12+（本机已验证 3.13），依赖已列于 `pyproject.toml`。

```powershell
# 1. 安装依赖（二选一）
uv sync --extra dev
# 或
pip install -e ".[dev]"

# 2. 配置环境变量：复制 .env.example 为 .env，填入 DEEPSEEK_API_KEY
#    （若项目尚无 .env.example，可手工创建 .env，变量见下表）

# 3. 启动前端
streamlit run app.py
# 或一键启动（自动检查 .env 并给出中文提示）
.\scripts\run.ps1
```

浏览器打开 http://localhost:8501 后，点击左侧「＋ 新建分析」上传同花顺交割单即可。
没有 API Key 也能完整使用：AI 区显示规则引擎兜底结果并标注降级。

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek API Key；为空时 AI 自动降级为规则引擎 | 空（降级） |
| `DEEPSEEK_API_BASE` | OpenAI 兼容 Base URL | `https://opencode.ai/zen/go/v1` |
| `DEEPSEEK_MODEL` | 模型名 | `deepseek-v4-flash` |
| `STOCK_REVIEW_CREW_SKILLS_DIR` | 5 位分析师 Skill 目录；目录缺失时降级项目内 `assets/skills`，再缺失使用内置兜底 | `H:\stock_review_crew\skills` |
| `SYNALYSIS_DATA_DIR` | 历史分析记录根目录（`{时间戳}/{meta.json, metrics.json, analysis.json}`） | `<项目>/data/analyses` |

## 目录结构

```text
synalysis_crew/
├─ app.py                  # Streamlit 前端入口
├─ scripts/
│  ├─ run.ps1              # 一键启动（检查 .env → streamlit run app.py）
│  └─ progress.py
├─ src/synalysis_crew/
│  ├─ parser.py            # 交割单解析器：10 种操作归一化、脏数据/多格式日期容错
│  ├─ metrics.py           # 指标引擎：2.3 节 32 项指标、FIFO 配对（含费用）、翻倍/腰斩
│  ├─ analyst.py           # Skill 加载、脱敏画像、规则引擎兜底、免责声明强制追加
│  ├─ graph.py / state.py  # LangGraph：profile → 5 分析师并行 → 主持人 → 辩论 → 单份报告
│  ├─ llm.py               # DeepSeek（OpenAI 兼容）LLM 配置
│  ├─ storage.py           # 历史记录存储：meta/metrics/analysis 三文件拆分
│  └─ ui.py                # 前端组件、图表与上传流水线
├─ tests/                  # pytest 单元 + 端到端测试（全部使用合成数据）
│  └─ fixtures/            # 合成交割单夹具（make_trades / build_xlsx）
├─ data/                   # 真实交割单与历史分析（均已 gitignore，绝不入库）
├─ docs/                   # 需求文档与 GitHub issue 文本
├─ assets/skills/          # 5 位分析师 Skill 副本（可选降级路径）
├─ .env / .env.example     # 环境变量（.env 不入库）
└─ pyproject.toml
```

## 指标清单（需求 2.3，共 32 项）

- **A 账户总览（8 项）**：统计区间、期初/期末资金、净转入、总收益率、年化收益率、
  累计已实现盈亏（FIFO 含费用）、总交易成本及占比、期末持仓市值/浮动盈亏。
- **B 交易统计（7 项）**：总成交金额/笔数、买卖拆分、日均笔数/成交额、
  去重股票数/持仓只数、平均单笔金额、资金周转率、平均持仓周期。
- **C 盈亏分析（9 项）**：已实现盈亏、胜率、盈亏比、最大单笔盈亏、
  **翻倍次数 / 腰斩次数**（按个股完整持仓周期）、月度盈亏序列、
  累计收益曲线 + 最大回撤、个股盈亏榜 Top10。
- **D 行为画像（6 项）**：持仓周期分布（≤1 / 2–5 / 6–20 / >20 天）、月度活跃度、
  单票最大仓位、Top5 集中度、偏好个股 Top10、风格初判 + 特殊操作统计。
- **E AI 分析（2 项）**：5 位分析师个人点评与标签、综合报告 + 总标签 +
  风险提示 + 免责声明。

区间口径：文件从账户中途开始（期初资金 ≠ 0 或期初有持仓）时 `is_partial=True`，
页面明确标注「区间收益」，不冒充总收益；期末持仓市值优先用实时行情（akshare），
失败时按成本兜底并标注 `market_value_source="cost"`。

## 隐私说明

- 真实交割单（`data/*.xlsx` / `*.xls` / `*.csv`）、历史分析（`data/analyses/`）
  与 `.env` 均已被 `.gitignore` 排除，**绝不进入 git**；
- AI 只接收脱敏画像（证券代码/名称/数量/价格/日期 + 指标摘要），
  **合同编号、资金余额、银行转账明细不会出现在 prompt 中**（需求 H4）；
- 上传文件只写入本地临时目录，分析完成后即删除；
- 自动化测试全部使用 `tests/fixtures` 中的合成交割单，不依赖任何真实数据与网络。

## 测试

```powershell
python -m pytest -q
```

测试覆盖：解析器（10 种操作、脏数据、日期格式、缺列/文件不存在中文异常、xlsx 往返、
UNKNOWN 归并与中途开始）、指标引擎（32 项清单、FIFO 含费用、翻倍/腰斩、最大回撤、
区间口径）、AI 模块（无 Key 降级、脱敏、坏输入容错）、storage（存取/损坏文件/字段拆分）、
端到端全链路，以及 Streamlit AppTest 前端冒烟（5 Tab 渲染、上传、历史回看）。
测试过程中不发网络请求（行情拉取被固定为成本兜底），无 Key 时 AI 走规则引擎。

## 免责声明

本工具输出仅供学习与研究参考，**不构成任何投资建议**。市场有风险，投资需谨慎。
