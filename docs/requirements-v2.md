# Synalysis Crew — v2 需求规格（2026-08-02 用户反馈修订，全量重构）

> 本规格为 v2 唯一契约。旧文档 requirements.md 中与本文冲突的以本文为准。
> 原则：**不逐项打补丁**，按本文档完成「设计 → 开发 → 测试 → 冒烟 → 验收」整轮交付。

## 一、业务逻辑口径（全部用户确认）

### 1.0 收益率总口径（v2.1 修订：时间加权 TWR，逐日模拟）
- 按交割单**逐日模拟账户**：现金 = 资金余额（权威），持仓 = 数量按 BUY/SELL/红股 增减，
  估值价 = 该股最近成交价（交割单内最后已知价）；期初持仓（卖出未配对部分）以
  其变现价值计入期初资产（合成持仓，价值 1:1 跟踪），避免"期初持仓卖出"被误算成收益。
- 每日收益率 `r_d = (当日末资产 − 当日净出入金 − 前一日末资产) / 前一日末资产`；
  前一日末资产 ≤ 0 的日跳过（数据异常保护）；出入金只影响分子扣除，**不影响收益率本身**。
- 累计收益率（时间加权）`R = Π(1 + r_d) − 1`；`total_return_rate` 主口径 = 最终 R。
- 收益率曲线 `return_curve`：每月末累计 R（无记录月份沿用上一值补齐）。
- 最大回撤、账户翻倍/腰斩 全部基于 `(1 + R)` 曲线（见 1.4 新定义）。
- 保留辅助字段：`gross_deposit/gross_withdraw/net_transfer_in/opening_asset_value`；
  `total_return_rate_net` 改为"期初资产基准简单收益率"（仅供对照，非主口径）。

### 1.1 完整交易（trades）
- 定义：**个股首次买入 → 清仓闭环**（FIFO 配对；多笔买入/卖出合并为一个闭环）。
- 每闭环输出：`code, name, buy_qty, buy_amount(含买入费用成本), sell_qty, sell_amount(卖出净额扣费用), pnl(周期盈亏), holding_days(首买日→清仓日), start_date, end_date, status="closed"`。
- **剔除**：分红/红股/利息/逆回购/指定交易/银行转账一律不进 trades；期初持仓卖出（无法配对）不进 trades，单列 `unmatched_sell_amount`。
- 前端「交易明细」Tab = 该列表（可搜索/按状态筛选），**不展示原始交割单**。

### 1.2 胜率 / 盈亏比 / 持仓周期（按完整交易）
- 胜率 = 盈利完整交易数 / (盈利 + 亏损完整交易数)，未清仓不计。
- 盈亏比 = 总盈利金额 / 总亏损金额（前端显示为 "1 : N" 比例格式并附口径说明）。
- 平均持仓周期 = 完整交易的平均 holding_days；持仓周期分布按完整交易统计。

### 1.3 收益率曲线（现金流调整，替代"累计收益曲线"）
- 月度近似资产 `equity_m` = 月末资金余额 + 月末持仓成本。
- 每月净转入 `t_m`、每月入金 `d_m`（转账行当月合计）。
- 期初资产 `A0` = 期初资金 + 期初持仓变现估值（unmatched_sell_amount）。
- 累计收益率 `R_m`：
  - `A0 > 0`：`R_m = (equity_m − Σt_i − A0) / A0`
  - `A0 = 0`（完整历史）：`R_m = (equity_m − Σd_i) / Σd_i`
- 输出 `return_curve: [{month, date, return_rate}]`（小数）；`equity_curve` 保留原始净值供调试。
- **最大回撤**基于 `(1 + R_m)` 序列计算。

### 1.4 账户级翻倍 / 腰斩（不是个股）
- 基于 TWR 收益率曲线（v2.1）`v = 1 + R`：
  - **翻倍次数**：累计收益率 R 达到 **+100%** 的独立事件次数（从 R < 100% 升到 ≥ 100% 计 1 次；
    禁止"从运行低点翻倍"口径——接近归零的账户会产生假阳性）。
  - **腰斩次数**：`v` 从运行高点回撤 ≥ 50%（`v ≤ 0.5·v_peak`）的独立事件次数（创新高后重新计数）。
- 字段 `pnl.double_count / pnl.halved_count`，前端文案「账户翻倍次数 / 账户腰斩次数」。

### 1.5 总收益率（保留 v1 已确认口径）
- 主口径 `total_return_rate`：期初资产基准 `(期末资产 − A0 − 净转入)/A0`；A0=0 退化累计入金基准。
- 辅口径 `total_return_rate_net`：纯现金期初基准。
- 出入金字段：`gross_deposit / gross_withdraw / net_transfer_in / opening_asset_value`。

### 1.6 亏损榜排序
- `stock_leaderboard.top_loss` 按 total_pnl **升序（亏损最多在前）**；top_profit 降序。

### 1.7 中文展示（前端）
- 月份一律「2025年11月」；日期「2025-11-27」；状态「已清仓 / 持有中」；来源「按成本估算 / 实时行情」；盈亏比「1 : 1.04」格式；所有界面文案中文。

## 二、系统架构（React + FastAPI）

### 2.1 后端（FastAPI，backend/main.py 已有雏形）
- `POST /api/analyze`（multipart file）→ 异步任务，返回 `{job_id}`。
- `GET /api/jobs/{id}` → `{status, stage, pct, message, analysts_done, analysts_total, result, error}`。
- `GET /api/analyses` / `GET /api/analyses/{id}`（历史记录）。
- `GET /api/health`；`frontend/dist` 存在时静态托管前端。
- 任务线程：parse_trades → compute_metrics → analyze(progress 回调) → save_analysis；错误给中文信息；上传临时文件用后即删。

### 2.2 前端（React + Vite + ECharts，frontend/ 已有脚手架与依赖）
- Codex 桌面风格：深色侧栏 #17181D、内容区 #F7F7F5、强调绿 #10A37F、圆角卡片、细边框。
- 侧栏：可收起/展开（收起后必须有恢复入口）；历史分析列表；「新建分析」始终可用（回到上传页）。
- 上传 → **分步进度条**（解析交割单 → 指标计算 → 分析师点评 0/5→5/5 → 主持人 → 辩论 → 生成报告 → 完成），轮询 job 接口，禁止白屏；错误醒目提示。
- Tabs：
  a) 账户总览：KPI（总收益率+口径标注、年化、已实现盈亏、胜率（按完整交易）、账户翻倍/腰斩、累计入金/出金/净转入、总成本、持仓市值）+ **收益率曲线** + 月度盈亏柱状图（中文月份）。
  b) 交易明细：完整交易列表（见 1.1），搜索/筛选，含盈亏与持股天数。
  c) 盈亏分析：胜率/盈亏比（"1 : N"）/单笔极值/翻倍腰斩 + 盈亏分布 + 个股盈亏榜（亏损榜亏损最多在前）。
  d) 行为画像：持仓周期分布、月度活跃度、风格标签、特殊操作统计（分红/逆回购等独立展示）。
  e) AI 报告：幽默标签徽章、免责声明、Markdown 报告、5 位分析师折叠卡片。
- 图表全部 ECharts，中文 tooltip；数据字段映射见 API 契约。

## 三、API 契约（前端依赖）

```
POST /api/analyze  FormData: file → {job_id}
GET  /api/jobs/{job_id} →
  {job_id, filename, status(queued|running|done|error), stage, pct, message,
   analysts_done, analysts_total, result|null, error|null}
  result = {record_id, metrics, analysis}
  metrics 关键字段（v2）：
    account: {initial_balance, ending_balance, net_transfer_in, gross_deposit,
              gross_withdraw, opening_asset_value, total_return_rate,
              total_return_rate_net, annualized_return_rate, realized_pnl,
              total_cost, total_cost_ratio, holding_market_value, holding_cost_value,
              unrealized_pnl, market_value_source}
    trading: {total_amount, total_count, buy_count, sell_count, distinct_stock_count,
              current_holding_count, avg_holding_period_days, ...}
    pnl: {realized_pnl, win_count, loss_count, win_rate, total_profit, total_loss,
          profit_loss_ratio, max_single_profit, max_single_loss,
          double_count, halved_count, unmatched_sell_amount,
          monthly_pnl[], equity_curve[], return_curve[], max_drawdown,
          stock_leaderboard{top_profit[], top_loss[]}}
    behavior: {holding_period_distribution, monthly_activity[], max_position,
               top5_concentration, favorite_stocks_top10[], style, special_operations}
    stocks: [{code,name,buy_count,sell_count,buy_amount,sell_amount,realized_pnl,
              unrealized_pnl,total_pnl,first_date,last_date,holding_days,status}]
    trades: [{code,name,buy_qty,buy_amount,sell_qty,sell_amount,pnl,
              holding_days,start_date,end_date,status}]
    meta: {is_partial, start_date, end_date, ...}
GET  /api/analyses → [{id,timestamp,filename,total_return_pct,is_partial,label,tags}]
GET  /api/analyses/{id} → {meta, metrics, analysis}
```

## 四、任务分配与文件所有权（并发 ≤ 5，防冲突）

| Agent | 任务 | 唯一写权限 | 只读 |
|---|---|---|---|
| M1 | 指标引擎 v2（1.1–1.6 + return_curve） | `src/synalysis_crew/metrics.py`、`tests/test_metrics.py`、`tests/test_e2e.py` | parser 契约、requirements-v2.md |
| M2 | 后端 API v2（2.1 + 进度 + 中文错误） | `backend/**` | metrics/graph 契约 |
| F1 | React 前端（2.2 + 1.7 + 三） | `frontend/**`（npm 依赖已装） | API 契约（开发期用 mock） |
| R1（Wave 2） | 全量业务逻辑审查 | 只读，输出审计报告 | 全部代码与本文档 |

规则：禁止 git、禁止改他人文件、禁止真实数据入库、`python -m pytest` 用系统 Python（frontend 用 `npm run build` 验证）；发现问题写入报告由主 agent 派发修复。

## 五、流程
1. 主 agent 提交 v2 检查点 → 创建 3 个 issue（metrics v2 / backend v2 / frontend react）
2. Wave 1：M1 + M2 + F1 并行（3 ≤ 5）
3. 主 agent 集成审查：全量 pytest、构建前端、启动冒烟（真实交割单全链路 + UI 截图）
4. Wave 2：R1 业务逻辑审计 → 派发修复
5. 最终验收：测试全绿、新架构启动、交付说明

## 六、数据字典（每个计算/展示字段的唯一定义，v2.1）

> 约定：比率一律**小数**存储（0.5 = 50%）；金额单位元；日期 `YYYY-MM-DD`；月份 `YYYY-MM`；
> `None` = 无数据（前端显示 `—`，**禁止显示 0**）；前端负责全部格式化（×100、中文、`1 : N`）。
> 总收益率主口径 = TWR（见 1.0）；`total_return_rate_net` 仅为对照口径。

| 字段 | 定义 / 公式 | 数据来源 | 边界情况 | 单位/展示 |
|---|---|---|---|---|
| account.initial_balance | 期初资金余额（首笔交易前） | 首行资金余额 − 首行变化 | 首行银行转证券→0（完整历史）；首行证券转银行→按 M6 规则计入出金后反推 | 元 |
| account.ending_balance | 期末资金余额 | 末行资金余额 | — | 元 |
| account.net_transfer_in | 净转入 = Σ(银行转证券) − Σ(证券转银行) | 转账行余额差分 | 首行证转银必须计入（M6） | 元 |
| account.gross_deposit / gross_withdraw | 累计入金 / 累计出金（正数） | 同上分正负 | — | 元 |
| account.opening_asset_value | 期初资产 = 期初资金 + 期初持仓变现估值 | unmatched_sell_amount | — | 元 |
| account.total_return_rate | **TWR 累计收益率**（1.0 逐日模拟，出入金不影响） | 逐日模拟 | 起始日资产≤0 跳过 | 小数→% |
| account.total_return_rate_net | 简单收益率 = (期末资产−A0−净转入)/A0；A0=0 → (期末−累计入金)/累计入金 | 期初资产基准 | 无基准 → None | 小数→%（对照） |
| account.annualized_return_rate | (1+R)^(365/span_days) − 1，R = TWR | 自然日 | R≤−50% 或 span≤0 → None | 小数→% |
| account.realized_pnl | 已实现盈亏（逐笔卖出 FIFO，含费用；部分卖出即入账） | 卖出配对 | — | 元 |
| account.total_cost / total_cost_ratio | Σ(印花税+过户费+max(手续费,佣金)) / 占成交额比 | 每笔成本 | — | 元 / 小数→% |
| account.holding_market_value / holding_cost_value / unrealized_pnl | 期末持仓市值 / 成本 / 浮动盈亏 | akshare 最新价，失败按成本（source=cost） | 部分行情缺失时标注 | 元 |
| trading.total_amount / total_count | 买卖成交金额合计 / 笔数（仅 BUY/SELL） | — | 特殊操作不计 | 元 / 笔 |
| trading.buy_count / sell_count / buy_amount / sell_amount | 买入/卖出拆分 | — | — | 笔 / 元 |
| trading.daily_avg_count / daily_avg_amount | 总笔数/总金额 ÷ 活跃交易日数 | — | — | 笔 / 元 |
| trading.distinct_stock_count / current_holding_count | 去重股票数 / 期末持仓只数 | — | — | 只 |
| trading.avg_trade_amount | 总成交额 ÷ 总笔数 | — | — | 元 |
| trading.capital_turnover_rate | 总成交额 ÷ 平均资金余额 | — | 无余额 → None | 倍 |
| trading.avg_holding_period_days | 完整交易平均持股天数 | trades 闭环 | 无完整交易 → None | 天 |
| pnl.win_count / loss_count / win_rate | 完整交易盈/亏笔数；胜率 = 盈÷(盈+亏) | 闭环周期盈亏 | 未清仓不计；无闭环 → None | 笔 / 小数→% |
| pnl.total_profit / total_loss | 盈利闭环合计 / 亏损闭环合计（loss 记正数） | 闭环 | — | 元 |
| pnl.profit_loss_ratio | 总盈利 ÷ 总亏损 | 闭环 | 无亏损 → None；前端 `1 : N` | 比率 |
| pnl.max_single_profit / max_single_loss | 单笔闭环最大盈利 / 最大亏损（负数） | 闭环 | 无 → 0 | 元 |
| pnl.double_count | **账户翻倍次数**：TWR 累计 R ≥ +100% 的独立事件（R 从 <1.0 升到 ≥1.0 计 1 次） | return_curve（1.4） | — | 次 |
| pnl.halved_count | **账户腰斩次数**：(1+R) ≤ 0.5×(1+R) 运行峰值 的独立事件（创新高重置） | return_curve（1.4） | — | 次 |
| pnl.unmatched_sell_amount | 期初持仓卖出未配对金额 | FIFO | — | 元 |
| pnl.monthly_pnl | 月度已实现盈亏 [{month, pnl}] | 逐月汇总 | 无记录月 0 | 元 |
| pnl.equity_curve | 月末原始资产（资金余额+持仓成本）[{month,date,balance,holding_cost,equity,net_value,drawdown}] | 月末快照 | 调试/净值参考 | 元 |
| pnl.return_curve | 月末 TWR 累计收益率 [{month,date,return_rate}] | 1.0 逐日模拟 | 无记录月份沿用上月 | 小数 |
| pnl.max_drawdown | 基于 (1+R) 序列的最大回撤（**正值**，如 0.5=50%） | 1.0 | — | 小数→% |
| pnl.stock_leaderboard | top_profit 降序；top_loss **升序（亏损最多在前）** | total_pnl = 已实现+浮动 | — | 元 |
| behavior.holding_period_distribution | 完整交易持仓天数分布 dict {le_1d, 2_5d, 6_20d, gt_20d} | 闭环 | 前端转带中文标签数组 | 笔 |
| behavior.monthly_activity | 月度交易笔数 [{month,total_count,buy_count,sell_count}] | — | — | 笔 |
| behavior.max_position | 历史单票最大仓位 {ratio, code, name, date} | 成本÷总资产 | 前端渲染 ratio/name/date | 小数 |
| behavior.top5_concentration | 前 5 大个股**成交金额** ÷ 总成交金额（买卖合计口径） | — | — | 小数 |
| behavior.favorite_stocks_top10 | 交易笔数 Top10 [{code,name,count,amount}] | — | — | 笔 |
| behavior.style | 风格初判 {holding_style, concentration, risk_style, label} | 规则引擎 | 前端全中文映射 | 中文 |
| behavior.special_operations | 逆回购/分红/红股/利息/打新/其他 {count, amount} | 特殊操作行 | 前端中文映射 | 笔/元 |
| stocks[] | 个股维度：买卖笔数/数量/金额、已实现/浮动/总盈亏、首末日期、持股天数、status(held/closed) | 逐股统计 | — | 元/天 |
| trades[] | **完整交易（仅 closed）**：code/name/buy_qty/buy_amount(含费成本)/sell_qty/sell_amount(扣费净额)/pnl/holding_days/start_date/end_date/status | FIFO 闭环 | 不含分红/转账/逆回购/期初持仓卖出 | 元/天 |
| meta.is_partial / start_date / end_date | 中途开始（期初资金≠0 或期初持仓）/ 区间起止 | — | — | bool/日期 |
| analysis（AnalysisResult） | **final_report**（唯一 Markdown）、**analysts[{skill_name, skill_id, analysis, suggestion, tags[]}]**、**debate_history[{round, topic, responses[{skill_name, response}]}]**、**overall_tags[]**、**disclaimer**、**degraded**、**round_count** | graph.py _to_result | 前端严格按此结构映射 | 文本 |

## 七、R1 审计修复清单（按 owner 派发）

- **F2（frontend/**）：S1 AI 报告字段映射、S2 持仓周期 dict→数组+中文标签、S3 历史收益率 ×100、M1 进度条 analysts 阶段匹配、M5 行为画像英文键中文映射、M7 None 显示「—」、M8 job result 缺 meta（前端回退 metrics.meta）、M9 Top5 集中度文案改成交金额口径、M10 删除「持有中」死筛选并同步 mock；建议项：盈亏分布桶标签、历史时间戳格式化、max_position 渲染、mock 严格对齐后端 Schema（比率小数）。
- **L1（src/synalysis_crew/analyst.py、tests/test_analyst.py）**：M3 盈亏比移出百分比（用 `1 : N`）、M4 最大回撤符号统一为正值（>= 0.2 触发）、对应测试。
- **B2（backend/**）**：S4 FastAPI 集成测试（TestClient：上传→轮询→done→历史→404/400）、M8 job result 增加 meta、建议项：JOBS TTL 清理、上传大小限制与文件名校验；`total_return_pct` 语义定为**小数比率**并在契约注明。
- **M1b（metrics.py 进行中）**：M6 首行证券转银行计入出金与期初反推、M11 e2e 年化断言容差收紧；并落实 1.0 TWR 与本节数据字典。
