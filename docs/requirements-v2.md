# Synalysis Crew — v2 需求规格（2026-08-02 用户反馈修订，全量重构）

> 本规格为 v2 唯一契约。旧文档 requirements.md 中与本文冲突的以本文为准。
> 原则：**不逐项打补丁**，按本文档完成「设计 → 开发 → 测试 → 冒烟 → 验收」整轮交付。

## 一、业务逻辑口径（全部用户确认）

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
- 基于收益率曲线 `v_m = 1 + R_m`：
  - 翻倍次数：从运行低点 v_min 起 `v ≥ 2·v_min` 的独立事件次数（创新低后重新计数）。
  - 腰斩次数：从运行高点 v_peak 起 `v ≤ 0.5·v_peak` 的独立事件次数（创新高后重新计数）。
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
