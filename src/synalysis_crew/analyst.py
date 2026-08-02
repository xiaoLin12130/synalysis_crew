"""分析师层：Skill 加载、脱敏交易画像、提示词组装与规则引擎兜底（Issue #3）。

职责边界：
- 只读取 ``STOCK_REVIEW_CREW_SKILLS_DIR``（默认 ``H:\\stock_review_crew\\skills``）；
- 画像只包含证券代码/名称/数量/价格/日期 + 指标摘要（H4 数据隐私）；
- 无 Key / LLM 调用失败时提供确定性规则引擎，绝不向上抛异常。
"""

import json
import math
import os
import re
import shutil
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DISCLAIMER = "仅供参考，不构成投资建议"

DEFAULT_SKILLS_DIR = r"H:\stock_review_crew\skills"
# 规范顺序：阿狼 / 爱在冰川 / 拔小弦 / 炒股养家 / 铁锤狂砸盘
SKILL_ID_ORDER = ["alang", "bingchuan", "baxiaoxian", "yangjia", "tiechui"]

# 敏感字段标记（中英文命中即丢弃，杜绝 contract_no / 资金余额 / 银行转账进入画像或 prompt）
_SENSITIVE_MARKERS = (
    "contract", "balance", "bank", "transfer",
    "资金余额", "银行", "转账", "合同",
)

# 个股画像允许出现的字段（H4：代码/名称/数量/价格/日期，另加操作类型便于点评）
_TRADE_FIELD_MAP = {
    "code": ("code", "证券代码"),
    "name": ("name", "证券名称", "证券中文全称"),
    "op_type": ("op_type", "operation", "操作"),
    "qty": ("qty", "quantity", "成交数量"),
    "price": ("price", "成交均价"),
    "trade_date": ("trade_date", "date", "交收日期", "交易日期"),
}

# 指标摘要白名单：仅这些标签/键允许进入画像（其余一律忽略）
_METRIC_LABELS = [
    ("interval_start", "统计起始"),
    ("interval_end", "统计截止"),
    ("total_return_rate", "总收益率"),
    ("annualized_return", "年化收益率"),
    ("realized_pnl", "累计已实现盈亏"),
    ("total_trade_amount", "总成交金额"),
    ("total_trade_count", "总笔数"),
    ("buy_count", "买入笔数"),
    ("sell_count", "卖出笔数"),
    ("avg_daily_trades", "日均交易笔数"),
    ("trade_stock_count", "交易股票数"),
    ("holding_count", "期末持仓只数"),
    ("avg_single_amount", "平均单笔金额"),
    ("turnover_rate", "资金周转率"),
    ("avg_holding_days", "平均持仓周期"),
    ("win_rate", "胜率"),
    ("profit_loss_ratio", "盈亏比"),
    ("total_profit", "总盈利金额"),
    ("total_loss", "总亏损金额"),
    ("max_single_profit", "最大单笔盈利"),
    ("max_single_loss", "最大单笔亏损"),
    ("double_count", "翻倍次数"),
    ("halved_count", "腰斩次数"),
    ("max_drawdown", "最大回撤"),
    ("total_cost", "总交易成本"),
    ("cost_ratio", "交易成本占比"),
    ("max_position_ratio", "单票最大仓位"),
    ("top5_concentration", "Top5 集中度"),
    ("monthly_activity", "月度交易活跃度"),
    ("style", "风格初判"),
    # 与 metrics.py 实际 Schema 对齐的键名（嵌套结构，如 account.total_return_rate）
    ("start_date", "统计起始"),
    ("end_date", "统计截止"),
    ("annualized_return_rate", "年化收益率"),
    ("total_cost_ratio", "交易成本占比"),
    ("total_amount", "总成交金额"),
    ("total_count", "总笔数"),
    ("daily_avg_count", "日均交易笔数"),
    ("distinct_stock_count", "交易股票数"),
    ("current_holding_count", "期末持仓只数"),
    ("avg_trade_amount", "平均单笔金额"),
    ("capital_turnover_rate", "资金周转率"),
    ("avg_holding_period_days", "平均持仓周期"),
]

# 百分比类键（格式化时转成 %）。注意：盈亏比（1 : N）与资金周转率（倍）不属于百分比字段。
_PCT_KEYS = (
    "return", "annual", "win", "drawdown", "ratio",
    "收益率", "年化", "胜率", "回撤", "占比", "集中度",
)


# ───────────────────────── 内置兜底 Skill（磁盘 Skill 全部不可用时的最后防线） ─────────────────────────

FALLBACK_SKILLS = [
    {
        "id": "alang",
        "name": "阿狼",
        "group": "trend",
        "prompt": "你是阿狼（狼大），趋势波段总教头：核心底仓+打野增强，用13/34/60/144均线管理仓位，"
        "趋势不结束底仓不动，破60线收缩。点评时关注持仓周期与回撤，给出均线纪律型建议。",
    },
    {
        "id": "bingchuan",
        "name": "爱在冰川",
        "group": "trend",
        "prompt": "你是爱在冰川，逻辑预判+低吸潜伏型选手：只做逻辑尚未被市场定价的方向，只做龙头与主升，"
        "逻辑证伪当天纠错。点评时判断账户持仓逻辑是否成立，给出龙头信仰型建议。",
    },
    {
        "id": "baxiaoxian",
        "name": "拔小弦",
        "group": "sentiment",
        "prompt": "你是拔小弦，断板趋势反包+板块前排容量标低吸做T的短线选手：缩量分歧不接，"
        "换手健康十日线有承接才是买点。点评时关注短线节奏与胜率，给出纪律型建议。",
    },
    {
        "id": "yangjia",
        "name": "炒股养家",
        "group": "sentiment",
        "prompt": "你是炒股养家，情绪周期大师：基于市场情绪揣摩风险收益，高潮兑现、冰点轻仓，"
        "顺势而为。点评时判断账户是否踩中情绪节奏，给出情绪周期型建议。",
    },
    {
        "id": "tiechui",
        "name": "铁锤狂砸盘",
        "group": "sentiment",
        "prompt": "你是铁锤，从巨亏中悟道的实战派：敬畏市场、不预判只跟随、等待是最高明的操作。"
        "点评时提醒敬畏风险、控制回撤，给出跟随确定性型建议。",
    },
]


# ───────────────────────── 基础工具 ─────────────────────────

def _as_dict(obj) -> dict:
    """把 dict / 带 to_dict() / 带 __dict__ 的对象统一转成 dict。"""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
            if isinstance(result, dict):
                return result
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return vars(obj)
    return {}


def _pick(raw: dict, *names, default=None):
    for name in names:
        if name in raw and raw[name] is not None:
            return raw[name]
    return default


def _fmt_num(v) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        if float(v).is_integer():
            return str(int(v))
        return f"{v:.2f}"
    return str(v)


def _fmt_pct(v) -> str:
    """数值按百分比展示（Schema 约定比率以小数存储，0.1234 = 12.34%）；已是字符串则原样返回。"""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return f"{v * 100:.1f}%"
    s = str(v)
    return s if s.endswith("%") else s


def _fmt_profit_loss_ratio(v) -> str:
    """盈亏比按 `1 : N` 展示（数据字典：总盈利 ÷ 总亏损，前端 1 : N）。

    N 取 max(ratio, 1/ratio) 并四舍五入两位：1.33 → "1 : 1.33"；0.957 → "1 : 1.04"。
    绝不做百分比（×100）输出。
    """
    if isinstance(v, bool):
        return str(v)
    try:
        r = float(v)
    except (TypeError, ValueError):
        return _fmt_num(v)
    if not math.isfinite(r) or r <= 0:
        return _fmt_num(v)
    n = r if r >= 1 else 1.0 / r
    return f"1 : {Decimal(str(n)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"

# ───────────────────────── Skill 加载 ─────────────────────────

def _load_skills_from_dir(skills_dir: str) -> list[dict]:
    skills = []
    root = Path(skills_dir)
    if not root.is_dir():
        return skills
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        skill_file = sub / "skill.json"
        if not skill_file.is_file():
            continue
        try:
            data = json.loads(skill_file.read_text(encoding="utf-8-sig"))
        except Exception:
            try:
                data = json.loads(skill_file.read_text(encoding="gbk"))
            except Exception:
                continue
        if not isinstance(data, dict):
            continue
        data["id"] = sub.name
        if data.get("name") and data.get("prompt"):
            skills.append(data)
    return skills


def _ensure_skills_dir(assets_dir: str | None = None) -> str:
    """解析 Skill 目录；缺失时降级项目内 assets/skills，并自动从默认目录复制。"""
    env_dir = (os.getenv("STOCK_REVIEW_CREW_SKILLS_DIR") or DEFAULT_SKILLS_DIR).strip()
    if env_dir and Path(env_dir).is_dir():
        return str(Path(env_dir))

    if assets_dir:
        assets = Path(assets_dir)
    else:
        assets = Path(__file__).resolve().parent.parent.parent / "assets" / "skills"
    if assets.is_dir():
        return str(assets)

    # 自动复制：从默认 stock_review_crew skills 同步到项目内 assets/skills
    src = Path(DEFAULT_SKILLS_DIR)
    if src.is_dir():
        try:
            assets.mkdir(parents=True, exist_ok=True)
            for sub in sorted(src.iterdir()):
                if sub.is_dir() and (sub / "skill.json").is_file():
                    shutil.copytree(sub, assets / sub.name, dirs_exist_ok=True)
            return str(assets)
        except Exception:
            pass
    return ""


def load_skills() -> list[dict]:
    """加载 5 位分析师 Skill（阿狼/爱在冰川/拔小弦/炒股养家/铁锤狂砸盘）。

    优先级：STOCK_REVIEW_CREW_SKILLS_DIR → 项目内 assets/skills（自动复制）→ 内置兜底。
    返回固定 5 位、固定顺序；缺失的个别 Skill 用内置兜底补足。
    """
    skills_dir = _ensure_skills_dir()
    loaded = _load_skills_from_dir(skills_dir) if skills_dir else []
    by_id = {s["id"]: s for s in loaded}

    result = []
    for sid in SKILL_ID_ORDER:
        if sid in by_id:
            result.append(by_id[sid])
            continue
        fallback = next((s for s in FALLBACK_SKILLS if s["id"] == sid), None)
        if fallback:
            result.append(dict(fallback))
    for s in loaded:  # 目录里的额外 Skill 追加在后
        if s["id"] not in SKILL_ID_ORDER and s not in result:
            result.append(s)
    return result


# ───────────────────────── 脱敏交易画像（H4） ─────────────────────────

def _safe_trade_row(trade) -> dict:
    """只保留 代码/名称/操作/数量/价格/日期；其余字段（含 contract_no/balance）一律不读。"""
    raw = _as_dict(trade)
    row = {}
    for target, names in _TRADE_FIELD_MAP.items():
        row[target] = _pick(raw, *names, default=("" if target in ("code", "name", "op_type", "trade_date") else 0))
    return row


def _metrics_allowed(key: str) -> bool:
    k = str(key).lower()
    if any(marker in k for marker in _SENSITIVE_MARKERS):
        return False
    return any(hint in k for hint in (
        "return", "annual", "pnl", "profit", "loss", "win", "drawdown", "hold",
        "turnover", "trade", "cost", "fee", "stock", "double", "halv", "style",
        "monthly", "concentr", "position", "avg", "period", "active", "prefer",
        "special", "interval", "amount", "count", "rate", "ratio", "value",
        "asset", "date", "资金", "资产",
    ))


def _metric_label(key: str) -> str:
    k = str(key).lower()
    for canonical, label in _METRIC_LABELS:
        if canonical == k:
            return label
    return str(key)


def _flatten_metrics(metrics: dict) -> dict:
    """递归展平嵌套指标 dict，键保留路径（如 account.total_return_rate）。"""
    out: dict = {}

    def walk(node: dict, prefix: str) -> None:
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                walk(v, key)
            else:
                out[key] = v

    walk(metrics or {}, "")
    return out


def _metrics_summary(metrics: dict) -> list[tuple[str, str]]:
    """按白名单提取指标摘要（支持嵌套 Schema）；命中敏感键直接跳过。"""
    if not metrics:
        return []
    flat = _flatten_metrics(metrics)
    allowed = {k: v for k, v in flat.items() if _metrics_allowed(k)}
    ordered: list[tuple[str, str]] = []
    used: set[str] = set()
    for canonical, label in _METRIC_LABELS:
        for k, v in allowed.items():
            seg = str(k).lower().rsplit(".", 1)[-1]
            if seg != canonical or k in used:
                continue
            if isinstance(v, dict):
                # style 等短值字典合并为 "a/b/c"；其余嵌套结构（已展平，理论不会出现）跳过
                if "style" not in k.lower():
                    continue
                text = "/".join(
                    str(x) for x in v.values() if isinstance(x, (str, int, float, bool))
                )
                if not text:
                    continue
                ordered.append((label, text))
            elif isinstance(v, (str, int, float, bool)):
                if canonical == "profit_loss_ratio":
                    value = _fmt_profit_loss_ratio(v)
                elif any(p in (label or canonical) for p in _PCT_KEYS):
                    value = _fmt_pct(v)
                else:
                    value = _fmt_num(v)
                ordered.append((label, value))
            used.add(k)
            break
    return ordered


def _aggregate_stocks(trades: list[dict], limit: int = 40) -> list[dict]:
    groups: dict[str, dict] = {}
    for row in trades:
        code = str(row.get("code") or "")
        if not code:
            continue
        g = groups.setdefault(code, {
            "code": code,
            "name": row.get("name") or "",
            "buy_qty": 0,
            "sell_qty": 0,
            "count": 0,
            "first_date": row.get("trade_date") or "",
            "last_date": row.get("trade_date") or "",
        })
        qty = row.get("qty") or 0
        op = str(row.get("op_type") or "")
        if "卖出" in op or "sell" in op.lower():
            g["sell_qty"] += abs(int(qty)) if isinstance(qty, (int, float)) else 0
        else:
            g["buy_qty"] += abs(int(qty)) if isinstance(qty, (int, float)) else 0
        g["count"] += 1
        if not g["first_date"] or str(row.get("trade_date") or "") < str(g["first_date"]):
            g["first_date"] = str(row.get("trade_date") or "")
        if str(row.get("trade_date") or "") > str(g["last_date"]):
            g["last_date"] = str(row.get("trade_date") or "")
    result = sorted(groups.values(), key=lambda g: (-g["count"], g["code"]))
    return result[:limit]


def build_profile(trades, metrics) -> str:
    """构建脱敏交易画像：指标摘要 + 个股级统计（代码/名称/数量/价格/日期）。

    绝不包含 contract_no / 资金余额 / 银行转账等敏感字段。
    """
    metrics_dict = _as_dict(metrics)
    trade_rows = [_safe_trade_row(t) for t in (trades or [])]

    lines = ["# 交易画像（脱敏）"]

    summary = _metrics_summary(metrics_dict)
    if summary:
        lines.append("")
        lines.append("## 账户指标摘要")
        lines.extend(f"- {label}：{value}" for label, value in summary)

    stocks = _aggregate_stocks(trade_rows)
    if stocks:
        lines.append("")
        lines.append("## 个股级统计（仅代码/名称/数量/日期）")
        for g in stocks:
            lines.append(
                f"- {g['code']} {g['name']}：买入{g['buy_qty']}股 / 卖出{g['sell_qty']}股，"
                f"{g['count']}笔，{g['first_date']} ~ {g['last_date']}"
            )

    recent = trade_rows[-20:]
    if recent:
        lines.append("")
        lines.append("## 近期交易明细（最近 20 笔，仅代码/名称/数量/价格/日期）")
        lines.append("| 日期 | 代码 | 名称 | 操作 | 数量 | 价格 |")
        lines.append("|---|---|---|---|---|---|")
        for r in recent:
            lines.append(
                f"| {r['trade_date']} | {r['code']} | {r['name']} | {r['op_type']} "
                f"| {_fmt_num(r['qty'])} | {_fmt_num(r['price'])} |"
            )

    if len(trade_rows) > 20:
        lines.append("")
        lines.append(f"（共 {len(trade_rows)} 笔交易，此处仅展示最近 20 笔）")

    return "\n".join(lines)


# ───────────────────────── 免责声明（程序级强制） ─────────────────────────

def ensure_disclaimer(text: str) -> str:
    """保证免责声明出现在报告末尾且仅一次。"""
    text = (text or "").strip()
    if not text:
        return f"> {DISCLAIMER}"
    parts = [p.strip() for p in text.split(DISCLAIMER) if p.strip()]
    body = "\n\n".join(parts)
    return f"{body}\n\n---\n\n> {DISCLAIMER}"


# ───────────────────────── LLM 输出解析 ─────────────────────────

def parse_analyst_output(content, skill=None) -> dict:
    """解析分析师结构化输出：【操作点评】【操作建议】【幽默标签】。"""
    content = (content or "").strip()
    m_review = re.search(r"【操作点评】\s*(.*?)(?=【操作建议】|【幽默标签】|$)", content, re.S)
    m_advice = re.search(r"【操作建议】\s*(.*?)(?=【幽默标签】|$)", content, re.S)
    m_tags = re.search(r"【幽默标签】\s*(.*)$", content, re.S)

    analysis = (m_review.group(1).strip() if m_review else content)[:300]
    suggestion = (m_advice.group(1).strip() if m_advice else "")[:200]
    tags = []
    if m_tags:
        tags = re.findall(r"#([^\s#，,。；;]+)", m_tags.group(1))
    if not tags and skill:
        persona = _RULE_PERSONAS.get(skill.get("id") or "")
        if persona:
            tags = list(persona["tags"])
    return {"analysis": analysis, "suggestion": suggestion, "tags": tags}


def parse_host_output(content) -> tuple[bool, str]:
    """解析主持人两行式输出：分歧判断：有/无 + 讨论议题：<议题>。返回 (是否有分歧, 议题)。"""
    has = False
    topic = ""
    for line in (content or "").splitlines():
        s = line.strip().lstrip("-*•").strip()
        for sep in ("：", ":"):
            if sep not in s:
                continue
            head, tail = s.split(sep, 1)
            tail = tail.strip()
            if "分歧" in head:
                has = "有" in tail
            elif "议题" in head or "话题" in head:
                topic = tail
            break
    if not topic or topic in ("无", "有", "无分歧", "无实质分歧", "暂无"):
        return False, ""
    return has, topic


# ───────────────────────── 提示词组装 ─────────────────────────

def build_analyst_prompt(skill: dict, profile: str, topic: str = "", others: str = "") -> str:
    name = skill.get("name", "分析师")
    parts = [
        f"你是{name}。请基于下方脱敏后的个人交易画像，给出你的操作点评。",
        f"## 你的角色设定\n{skill.get('prompt', '')}",
        f"## 脱敏交易画像\n{profile}",
    ]
    if topic:
        parts.append(f"## 讨论议题\n{topic}")
    if others:
        parts.append(f"## 其他分析师的回应（供交叉引用，不必重复）\n{others}")
    parts.append(
        "## 输出要求（严格按以下格式，不要输出其他内容）\n"
        "【操作点评】≤200字：结合画像点评账户操作风格与得失\n"
        "【操作建议】≤150字：给出可执行建议\n"
        "【幽默标签】2-3个：#标签1 #标签2"
    )
    parts.append("注意：只依据画像中的信息，不得编造未出现的证券或数据；不得提及账户标识、资金流水等敏感信息。")
    return "\n\n".join(parts)


def build_host_prompt(analysts: list[dict], debate_history: list[dict], round_label: str) -> str:
    parts = [f"这是{round_label}分析。以下是各位分析师的独立观点："]
    for a in analysts:
        parts.append(
            f"### {a.get('skill_name', '分析师')}\n"
            f"点评：{a.get('analysis', '')}\n建议：{a.get('suggestion', '')}"
        )
    if debate_history:
        lines = ["", "## 前几轮讨论记录"]
        for entry in debate_history:
            lines.append(f"### 第{entry.get('round', '?')}轮：{entry.get('topic', '')}")
            for r in entry.get("responses", []):
                lines.append(f"{r.get('skill_name', '')}：{r.get('response', '')}")
        parts.append("\n".join(lines))
    parts.append(
        "请判断分析师之间是否存在实质性分歧（方向/仓位/标的判断本质不同才算；措辞不同但结论一致不算），"
        "严格按两行格式输出：\n"
        "分歧判断：有 / 无\n"
        "讨论议题：<一句话议题> 或 讨论议题：无"
    )
    return "\n\n".join(parts)


def build_debate_prompt(skill: dict, profile: str, topic: str, others: str) -> str:
    name = skill.get("name", "分析师")
    parts = [
        f"你是{name}，请针对讨论议题发表你的观点。",
        f"## 你的角色设定\n{skill.get('prompt', '')}",
        f"## 脱敏交易画像\n{profile}",
        f"## 讨论议题\n{topic}",
    ]
    if others:
        parts.append(f"## 其他分析师的立场（可同意、反对或补充）\n{others}")
    parts.append("要求：直接表达观点，≤150字；只做观点分析，不模拟买卖操作；不得编造画像之外的证券或数据；不得提及敏感信息。")
    return "\n\n".join(parts)


def build_report_prompt(profile: str, analysts: list[dict], debate_history: list[dict], overall_tags: list[str]) -> str:
    views = "\n\n".join(
        f"### {a.get('skill_name', '分析师')}\n点评：{a.get('analysis', '')}\n建议：{a.get('suggestion', '')}"
        for a in analysts
    )
    if debate_history:
        debate_text = "\n\n".join(
            f"### 第{entry.get('round', '?')}轮：{entry.get('topic', '')}\n"
            + "\n".join(f"{r.get('skill_name', '')}：{r.get('response', '')}" for r in entry.get("responses", []))
            for entry in debate_history
        )
    else:
        debate_text = "无讨论记录。"
    tag_line = " ".join(f"#{t}" for t in (overall_tags or [])) or "暂无"
    return "\n\n".join([
        "你是资深交易报告撰稿人。请基于以下脱敏交易画像、分析师观点与讨论记录，生成**唯一一份** Markdown 分析报告。",
        f"## 脱敏交易画像\n{profile}",
        f"## 各分析师观点\n{views}",
        f"## 讨论记录\n{debate_text}",
        f"## 汇总幽默标签\n{tag_line}",
        "## 报告结构（严格按此章节输出）\n"
        "# 交易分析报告\n"
        "## 一、账户概况\n"
        "## 二、各分析师核心观点\n"
        "## 三、分歧与讨论\n"
        "## 四、操作意见\n"
        "## 五、幽默标签\n"
        "## 六、风险提示",
        "要求：全文只输出一份报告；观点必须基于画像数据，不编造；专业、克制、可执行。",
    ])


# ───────────────────────── 规则引擎兜底（无 Key / 调用失败） ─────────────────────────

_RULE_PERSONAS = {
    "alang": {
        "up": "趋势波段视角下，账户整体处于向上区间，底仓思路基本成立；但单票波动要靠均线纪律约束，别让打野仓位反噬底仓。",
        "down": "趋势波段视角下，账户处于逆风区间，死扛不如按均线纪律收缩；亏损主要来自逆势时的仓位过重，先降风险再谈反弹。",
        "suggestion": "核心底仓管住手，回踩不破关键均线不砍；打野仓位不超过三成，做错次日离场。",
        "tags": ["均线控盘", "波段为王"],
    },
    "bingchuan": {
        "up": "逻辑视角看，账户盈利说明阶段性踩中了市场认可的逻辑；持仓越集中，越要确认逻辑是否还在，不在了就果断纠错。",
        "down": "逻辑视角看，亏损往往不是不努力，而是做了市场不认可的方向；先问持有理由是否成立，不成立当天纠错，不补仓摊薄。",
        "suggestion": "只做逻辑仍成立的主升方向，杂毛不碰；逻辑证伪当天纠错。",
        "tags": ["逻辑先行", "龙头信仰"],
    },
    "baxiaoxian": {
        "up": "短线视角看，账户胜率和节奏尚可，属于能赚到钱的手；关键是别在情绪退潮期重仓，断板反包要等换手健康再低吸。",
        "down": "短线视角看，亏损多来自分歧期追高或缩量反包；情绪退潮期最好的操作就是不做，等放量换手确认再说。",
        "suggestion": "只在板块前排容量标里做T；断板后缩量分歧不接，情绪冰点再出手。",
        "tags": ["断板反包", "低吸做T"],
    },
    "yangjia": {
        "up": "情绪周期视角看，账户能赚钱说明踩上了情绪上升期；接下来要防高位一致性后的分歧，别人贪婪时先想好退出路径。",
        "down": "情绪周期视角看，亏损大概率发生在情绪退潮期仍逆势操作；恐慌期不接飞刀，等场外资金回补再谈机会。",
        "suggestion": "高潮期减仓兑现，冰点期轻仓试探；只做市场最强方向，弱转强确认再上。",
        "tags": ["情绪周期", "顺势而为"],
    },
    "tiechui": {
        "up": "铁律视角看，连赚之后最危险：市场永远是对的，涨了就拿住，节奏走坏就走人，别把盈利单拿成亏损单。",
        "down": "铁律视角看，亏损多半是预判代替了跟随；行情是走出来的不是猜出来的，等确定性信号再动手，空仓不丢人。",
        "suggestion": "不预判只跟随，抓0-1确定性；亏损后强制休息，等市场给出明确方向再进场。",
        "tags": ["敬畏市场", "只做跟随"],
    },
}

_RULE_DEBATE = {
    "alang": "趋势没坏之前不因一两根K线改判断：底仓按均线持有，回踩13/34线企稳就是加仓点，破60线再全面收缩。",
    "bingchuan": "方向之争不重要，逻辑在不在才重要：标的只要主升逻辑未被证伪就不必恐慌离场；证伪则当天纠错。",
    "baxiaoxian": "情绪分歧期重仓才是大忌：断板缩量先观察，换手放量确认反包再低吸，宁可错过不可做错。",
    "yangjia": "一致转分歧是必然过程：高潮后先兑现一部分，等恐慌释放、场外资金回流信号出现再考虑加仓。",
    "tiechui": "行情是走出来的不是猜出来的：现在多看少动，等确定性方向出现再动手，空仓等待不丢人。",
}

_BULLISH_WORDS = ("加仓", "买入", "低吸", "看多", "抄底", "做多", "持有")
_BEARISH_WORDS = ("减仓", "卖出", "看空", "清仓", "离场", "空仓", "观望", "止损")


def _facts(metrics: dict) -> dict:
    """从指标 dict 中模糊提取常用事实（支持嵌套 Schema，键名不敏感）。"""
    flat = _flatten_metrics(metrics)

    def first(*keys):
        low_keys = [k.lower() for k in keys]
        for raw_k, v in flat.items():
            seg = str(raw_k).lower().rsplit(".", 1)[-1]
            if any(lk == seg or lk in seg for lk in low_keys):
                return v
        return None
    return {
        "total_return": first("total_return_rate", "return_rate", "总收益率", "总收益"),
        "annual": first("annualized_return", "annual_return", "年化收益率", "年化收益"),
        "win_rate": first("win_rate", "胜率"),
        "drawdown": first("max_drawdown", "最大回撤"),
        "holding": first("avg_holding_days", "avg_holding", "平均持仓周期", "平均持有天数"),
        "double": first("double_count", "翻倍次数"),
        "halved": first("halved_count", "腰斩次数"),
        "count": first("total_trade_count", "total_count", "总笔数", "交易笔数"),
        "stocks": first("trade_stock_count", "distinct_stock_count", "交易股票数"),
        "style": first("style", "风格初判"),
    }


def _fact_sentence(facts: dict) -> str:
    parts = []
    if facts["total_return"] is not None:
        parts.append(f"总收益率{_fmt_pct(facts['total_return'])}")
    if facts["annual"] is not None:
        parts.append(f"年化{_fmt_pct(facts['annual'])}")
    if facts["win_rate"] is not None:
        parts.append(f"胜率{_fmt_pct(facts['win_rate'])}")
    if facts["drawdown"] is not None:
        parts.append(f"最大回撤{_fmt_pct(facts['drawdown'])}")
    if facts["holding"] is not None:
        parts.append(f"平均持仓{_fmt_num(facts['holding'])}天")
    if facts["count"] is not None:
        parts.append(f"{_fmt_num(facts['count'])}笔交易")
    if facts["stocks"] is not None:
        parts.append(f"涉{_fmt_num(facts['stocks'])}只股票")
    return "、".join(parts) if parts else "交易数据有限"


def _dynamic_tag(facts: dict) -> str | None:
    if facts["win_rate"] is not None:
        try:
            return f"胜率{_fmt_pct(float(facts['win_rate']))}"
        except Exception:
            return None
    return None


def rule_analyst_entry(skill: dict, metrics: dict, profile: str = "") -> dict:
    """规则引擎生成单个分析师条目（点评+建议+2-3个幽默标签）。"""
    sid = skill.get("id") or ""
    name = skill.get("name") or sid or "分析师"
    facts = _facts(_as_dict(metrics))
    fact_line = _fact_sentence(facts)
    direction = "up"
    if facts["total_return"] is not None:
        try:
            direction = "up" if float(facts["total_return"]) >= 0 else "down"
        except Exception:
            pass
    persona = _RULE_PERSONAS.get(sid, _RULE_PERSONAS["tiechui"])
    tags = list(persona["tags"])
    dynamic = _dynamic_tag(facts)
    if dynamic and len(tags) < 3:
        tags.append(dynamic)
    return {
        "skill_name": name,
        "skill_id": sid,
        "analysis": f"{fact_line}。{persona[direction]}",
        "suggestion": persona["suggestion"],
        "tags": tags,
    }


def rule_tags(metrics: dict) -> list[str]:
    """基于指标生成汇总幽默标签。"""
    facts = _facts(_as_dict(metrics))
    tags = []
    if facts["style"]:
        tags.append(str(facts["style"]).strip())
    if facts["win_rate"] is not None:
        try:
            wr = float(facts["win_rate"])
            tags.append("胜率稳健" if wr >= 0.55 else ("胜率待打磨" if wr < 0.4 else "胜率一般"))
        except Exception:
            pass
    if facts["annual"] is not None:
        try:
            an = float(facts["annual"])
            tags.append("收益能打" if an >= 0.2 else ("亏钱小能手" if an <= -0.2 else "收益平平"))
        except Exception:
            pass
    if facts["drawdown"] is not None:
        try:
            if float(facts["drawdown"]) >= 0.2:
                tags.append("回撤凶猛")
        except Exception:
            pass
    if facts["holding"] is not None:
        try:
            hd = float(facts["holding"])
            tags.append("超短选手" if hd <= 5 else ("短线波段" if hd <= 20 else "偏中长线"))
        except Exception:
            pass
    if facts["double"] is not None:
        try:
            if float(facts["double"]) > 0:
                tags.append("翻倍传说")
        except Exception:
            pass
    if facts["halved"] is not None:
        try:
            if float(facts["halved"]) > 0:
                tags.append("腰斩警告")
        except Exception:
            pass
    if facts["stocks"] is not None:
        try:
            n = float(facts["stocks"])
            if n <= 10:
                tags.append("集中打法")
            elif n >= 30:
                tags.append("分散撒网")
        except Exception:
            pass
    seen: list[str] = []
    for t in tags:
        if t and t not in seen:
            seen.append(t)
    return seen[:6]


def rule_host(analysts: list[dict]) -> tuple[bool, str]:
    """规则版主持人：按多空关键词判断是否存在实质性分歧。"""
    text = " ".join(
        f"{a.get('skill_name', '')}{a.get('analysis', '')}{a.get('suggestion', '')}"
        for a in (analysts or [])
    )
    has_bullish = any(w in text for w in _BULLISH_WORDS)
    has_bearish = any(w in text for w in _BEARISH_WORDS)
    if has_bullish and has_bearish:
        return True, "多空方向分歧：当前账户该继续加仓进攻，还是减仓防守？"
    return False, ""


def rule_debate_response(skill: dict, topic: str) -> str:
    return _RULE_DEBATE.get(skill.get("id") or "", _RULE_DEBATE["tiechui"])


def _risk_lines(metrics: dict) -> list[str]:
    facts = _facts(_as_dict(metrics))
    risks = ["市场有风险，历史交易数据不代表未来表现，请独立判断。"]
    if facts["drawdown"] is not None:
        try:
            if float(facts["drawdown"]) >= 0.2:
                risks.append("历史最大回撤较深，注意单票集中与仓位控制。")
        except Exception:
            pass
    if facts["halved"] is not None:
        try:
            if float(facts["halved"]) > 0:
                risks.append("存在腰斩级亏损记录，需警惕追高与补仓摊薄行为。")
        except Exception:
            pass
    if facts["holding"] is not None:
        try:
            if float(facts["holding"]) <= 5:
                risks.append("持仓周期偏短、交易偏高频，手续费与滑点成本不可忽视。")
        except Exception:
            pass
    return risks


def rule_report(profile: str, metrics: dict, analysts: list[dict], debate_history: list[dict], overall_tags: list[str]) -> str:
    """规则版最终报告（降级路径）：固定章节 + 免责声明由 ensure_disclaimer 强制追加。"""
    lines = ["# 交易分析报告", "", "## 一、账户概况"]
    summary = _metrics_summary(_as_dict(metrics))
    if summary:
        lines.append("")
        lines.extend(f"- {label}：{value}" for label, value in summary)
    else:
        lines += ["", "- 指标摘要暂缺。"]

    lines += ["", "## 二、各分析师核心观点"]
    for a in analysts:
        lines += ["", f"### {a.get('skill_name', '分析师')}"]
        lines.append(a.get("analysis", ""))
        if a.get("suggestion"):
            lines.append(f"> 建议：{a['suggestion']}")
        tags = a.get("tags") or []
        if tags:
            lines.append("> 标签：" + " ".join(f"#{t}" for t in tags))

    lines += ["", "## 三、分歧与讨论"]
    if debate_history:
        for entry in debate_history:
            lines += ["", f"### 第{entry.get('round', '?')}轮：{entry.get('topic', '')}"]
            for r in entry.get("responses", []):
                lines.append(f"- **{r.get('skill_name', '分析师')}**：{r.get('response', '')}")
    else:
        lines += ["", "本轮分析未发现实质性分歧，观点整体一致。"]

    lines += [
        "",
        "## 四、操作意见",
        "",
        "- 方向：以趋势与逻辑未破坏为前提，仓位向强势方向集中；情绪分歧期优先控制仓位。",
        "- 纪律：单票止损线提前设定，破位即走；连亏后强制休息，避免情绪化交易。",
        "- 节奏：短线分歧期多看少动，等换手与情绪确认后再出手。",
    ]

    lines += ["", "## 五、幽默标签"]
    if overall_tags:
        lines += ["", " ".join(f"#{t}" for t in overall_tags)]
    else:
        lines += ["", "暂无"]

    lines += ["", "## 六、风险提示", ""]
    lines.extend(f"- {r}" for r in _risk_lines(metrics))
    return "\n".join(lines)
