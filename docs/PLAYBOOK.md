# PLAYBOOK — 项目踩坑与解法手册

> 所有 agent（Codex/Claude）开工前必读。遇到环境/工具/权限/网络/业务逻辑问题时**先查这里**；
> 解决问题后**按文末模板追加新条目**，方便后续所有 agent。

## 1. 网络与代理（Windows 本机）
| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| github.com 直连不通 | git push/curl 443 超时 | 本机网络对 github.com 不稳定 | 走代理：`git -c http.proxy=http://127.0.0.1:7890 push`（或写入仓库级 config）；curl 加 `-x http://127.0.0.1:7890` |
| api.github.com 可用 | 与 github.com 不通但 api 通 | 网络分层 | GitHub API 操作（issue/文件）可用 urllib/curl 直连 api.github.com |
| 下载 GitHub releases 失败 | curl 直连超时 | 同上 | 加 `-x http://127.0.0.1:7890` 重试（cloudflared 即如此下载成功） |

## 2. GitHub Issue / 仓库操作
| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| 插件建 issue 404 | `Resource not found` | GitHub 插件 App 看不到你的私有仓库 | 仓库改 public，或把插件账号加为协作者（用户手动） |
| 插件建 issue 403 | `Resource not accessible by integration` | App 未安装/未授权到该账号仓库 | 插件无解 → 改用**用户的 fine-grained PAT**（仓库 + Issues 读写）走 api.github.com；网络不稳要加重试（3 次 + 退避） |
| 创建仓库 | 插件无建仓工具 | 能力缺失 | 用户手动创建（private/public 均可，public 才能被插件看见） |

## 3. 沙箱与提权（workspace-write 环境）
| 问题 | 现象 | 原因 | 解决 |
|---|---|---|---|
| git 写操作被拒 | `index.lock: Permission denied` / config 锁失败 | `.git` 目录在沙箱只读 | git 命令（add/commit/push）用 `require_escalated`，可申请 prefix `["git"]` |
| 前端构建失败 | esbuild `EPERM` spawn 子进程 | 沙箱拦截 | `npm run build` 用 `require_escalated` |
| pip/npm install 失败 | 网络/权限 | 沙箱网络受限 | 提权安装；依赖尽量一次性装好，agent 禁止自行安装 |
| 后台服务 | 需要常驻进程 | — | `Start-Process -WindowStyle Hidden`；健康检查用 `Invoke-RestMethod http://127.0.0.1:PORT/api/health` |
| pytest tmp_path 报错 | WinError 5 拒绝访问 | Windows 沙箱下 pytest 0o700 目录 ACL 问题 | 测试模块覆盖 tmp_path fixture，用 0o777 显式创建并自清理（参考 tests/test_parser.py） |
| PowerShell 管道中文乱码 | python 收到 `??` | PS 按 GBK 编码管道 | 脚本用纯 ASCII（中文用 `\uXXXX`），或 `$env:PYTHONIOENCODING='utf-8'` |

## 4. 业务逻辑纪律（本项目血泪教训）
1. **数据字典先行**：每个字段写死定义（公式/来源/边界/单位/None 语义），见 `requirements-v2.md` 第六节；代码与前端严格对照。
2. **口径先和用户确认再实现**：
   - 收益率 = TWR 逐日模拟（出入金按日扣除，不影响收益率）；期初持仓用合成持仓计入；逆回购本金按应收款中性化（R-007 会击穿曲线）；
   - 胜率/盈亏比/持仓周期 = 按**完整交易（买入→清仓闭环）**统计；
   - 翻倍 = 累计收益率 R≥+100% 的独立事件（禁止"从低点翻倍"，接近归零账户会假阳性）；
   - 腰斩 = 递进式 floor 计数（1→0.5→0.25→0.125 逐级计次，回升创新高才重置）；
   - 亏损榜 top_loss 升序（亏损最多在前）；最大回撤为正值。
3. **前端↔后端契约写进文档**：接口返回结构（含嵌套字段）必须完整记录，前端 normalize 层对照实现——本项目因字段不匹配导致 AI 报告整页失效（S1 事故）。
4. 比率一律小数存储（0.5=50%），前端负责 ×100 与 `1 : N` 格式；`None` 显示「—」不显示 0。
5. 长任务必须：后台 + 进度轮询 + fetch 超时（30s）+ 中文错误；上传控件支持重选同一文件（input value 重置）。
6. 降级链：数据源失败 / LLM 无 Key / 历史缺失 → 明确降级并标注，绝不静默错报。
7. 测试：每个指标至少一个**手算抽查用例**；断言容差不可过大（曾出现 abs=10 形同虚设）；真实数据冒烟。
8. 免责声明程序级强制追加；红涨绿跌（正红负绿）；全中文（月份「2025年11月」等）。

## 5. Agent 协作
- spawn_agent 并发 ≤5；每个 agent 给**文件所有权表**（只写自己名下文件）与只读契约；禁止 git/真实数据入库/改他人文件。
- 完成通知会自动推送；可用 wait_agent 主动查询状态。
- **空闲 agent 会被系统回收**（"保留待命"不等于永存）：重要任务开始前先确认负责人还在，不在就新开并把上下文写全。
- 模块负责人登记表在 `docs/PROGRESS.md`；进度估算脚本 `scripts/progress.py`。
- 测试隔离：`SYNALYSIS_DATA_DIR` 指向 `.tmp/`，不要写仓库 `data/analyses/`。

## 6. 部署（Cloudflare Tunnel）
- cloudflared 下载：GitHub releases（走代理 127.0.0.1:7890），放 `.tmp\cloudflared.exe`。
- 快速隧道：`cloudflared tunnel --url http://127.0.0.1:8501 --no-autoupdate`，公网地址从 stdout/stderr 日志解析 `https://*.trycloudflare.com`；一键脚本 `scripts\start_tunnel.ps1`。
- 快速隧道地址**每次重启变化**；电脑关机服务停止。
- 公网无历史模式：`SYNALYSIS_PUBLIC_MODE=1`（分析不落盘、历史恒空，默认关闭）。
- 安全：公网 URL 不要公开分享；上传的原始文件分析完即删（finally 清理）。

## 7. 新问题记录模板
```markdown
## [YYYY-MM-DD] 问题一句话
- 现象：……
- 原因：……
- 解决：……
- 备注/复现：……
```
