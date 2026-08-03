# AGENTS.md（所有 agent 开工前必读）

## 项目速览
- synalysis_crew：同花顺/涨乐财富通交割单分析系统。FastAPI 后端 + React 前端 + TWR 指标引擎 + LangGraph 多分析师。
- 需求与**数据字典（字段唯一真源）**：`docs/requirements-v2.md`（第六节）
- 进度存档与 agent 登记：`docs/PROGRESS.md`
- **环境/工具/业务逻辑踩坑与解法：`docs/PLAYBOOK.md`（必读）**

## 铁律
1. 开工前先读 `docs/PLAYBOOK.md` 与 `docs/requirements-v2.md`；
2. 遇到环境/工具/权限/网络问题，先查 PLAYBOOK，解决后**按模板追加新条目**；
3. 禁止：`git commit/push`、真实交割单数据写入仓库、修改自己写权限之外的文件、`uv sync`/`pip install`（系统 Python 依赖已装）；
4. 测试用 `python -m pytest`；前端构建 `npm run build` 需提权（esbuild 沙箱 EPERM）；
5. 所有面向用户的投资内容必须带「仅供参考，不构成投资建议」；
6. 比率一律小数存储，前端 ×100；`None` 显示「—」；全中文展示。

## 服务
- 本地：`python -m uvicorn backend.main:app --host 127.0.0.1 --port 8501`
- 公网隧道：`scripts\start_tunnel.ps1`（cloudflared，快速隧道地址每次重启变化）
- 公网无历史模式：环境变量 `SYNALYSIS_PUBLIC_MODE=1`（默认关闭）
