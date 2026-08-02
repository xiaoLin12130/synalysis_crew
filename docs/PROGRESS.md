# 项目进度存档（2026-08-03 00:55 暂停）

> 状态：v2.1 全量重构已完成并提交推送，待用户验收体验。

## 已完成（全部测试通过、已推送 GitHub）

### 架构（v2 重构）
- 后端：FastAPI（backend/main.py）异步任务 + 进度轮询 + 历史接口 + 静态托管前端
- 前端：React + Vite + ECharts（frontend/），Codex 桌面风格、全中文、可收起侧栏、分步进度条
- 指标引擎：v2.1 逐日 TWR 模拟（出入金不影响收益率）、完整交易（买入→清仓闭环）口径、
  账户级翻倍/腰斩、收益率曲线、数据字典（docs/requirements-v2.md 第六节）
- 分析师模块：5 位分析师 LangGraph 讨论 + 单报告 + 免责声明 + 降级（复用 stock_review_crew skills）

### 测试
- `python -m pytest` → **96 passed, 1 skipped**（parser/metrics/analyst/storage/backend 集成/e2e）
- 前端 `npm run build` 成功；normalize 断言脚本 `frontend/verify-normalize.mjs` 通过
- R1 业务逻辑审计 15 项问题（S1-S4/M1-M11）已全部修复

### 真实数据冒烟（通过）
- data/20251127-20260731.xlsx：TWR -16.52%，胜率 49.01%（253 笔完整交易），
  翻倍 0、腰斩 1、最大回撤 52.16%，真实 LLM 报告生成（degraded=False）
- data/all.xlsx（引擎直算）：TWR -93.54%，翻倍 0、腰斩 1、最大回撤 93.54%，
  完整交易 1461 笔、胜率 42.51%（对照简单收益率 -98.41%）

## 当前状态
- 服务运行中：uvicorn PID 27352，http://localhost:8501（已在前端页面打开）
- 重启命令：`python -m uvicorn backend.main:app --host 127.0.0.1 --port 8501`（工作目录 H:\synalysis_crew）
- 最新提交：`d4153e6`（已推送）
- GitHub issues：#6/#7/#8（v2 三项）；旧 #1-#5 为 v1 历史

## 明天继续的步骤
1. 用户体验新页面（上传真实交割单 → 进度条 → 5 个 Tab）
2. 按体验反馈调整（若有）
3. 最终验收说明 + 可选的 GitHub token 撤销提醒

## 关键文档
- 需求规格：docs/requirements-v2.md（第六节 = 数据字典，字段唯一真源）
- 需求 v1：docs/requirements.md；issue 文本：docs/issues.md
