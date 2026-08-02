"""LangGraph 流程：profile → analysts(5 路并行) → host → debate(循环) → report。

对齐 stock_review_crew 的 graph 模式（仅参考流程编排，不复制其数据获取逻辑）。
只输出一份最终 Markdown 报告；无 Key / 调用失败自动降级规则引擎，绝不抛异常。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from langgraph.graph import END, StateGraph

from synalysis_crew.analyst import (
    DISCLAIMER,
    _as_dict,
    build_analyst_prompt,
    build_debate_prompt,
    build_host_prompt,
    build_profile,
    build_report_prompt,
    ensure_disclaimer,
    load_skills,
    parse_analyst_output,
    parse_host_output,
    rule_analyst_entry,
    rule_debate_response,
    rule_host,
    rule_report,
    rule_tags,
)
from synalysis_crew.llm import llm, llm_available, llm_strict
from synalysis_crew.state import AnalysisResult, AnalysisState

_MAX_WORKERS = 5  # 5 位分析师并行
_DEFAULT_MAX_ROUNDS = 2


# ───────────────────────── profile 节点 ─────────────────────────

def profile_node(state: AnalysisState) -> dict:
    return {"profile": build_profile(state.get("trades", []), state.get("metrics", {}))}


# ───────────────────────── analysts 节点（ThreadPool 并行，max_workers=5） ─────────────────────────

def _run_analyst(skill: dict, profile: str, metrics: dict) -> tuple[dict, bool]:
    """单个分析师推理；返回 (条目, 是否降级)。LLM 失败或无 Key 时走规则引擎。"""
    name = skill.get("name", "分析师")
    sid = skill.get("id", "")
    if llm_available():
        try:
            content = llm.invoke([
                {"role": "system", "content": skill.get("prompt", "")},
                {"role": "user", "content": build_analyst_prompt(skill, profile)},
            ]).content
            parsed = parse_analyst_output(content, skill)
            return {"skill_name": name, "skill_id": sid, **parsed}, False
        except Exception:
            pass
    return rule_analyst_entry(skill, metrics, profile), True


def analysts_node(state: AnalysisState) -> dict:
    skills = load_skills()
    profile = state.get("profile", "")
    metrics = state.get("metrics", {})
    entries: list[dict] = []
    degraded = False
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_run_analyst, s, profile, metrics): i for i, s in enumerate(skills)}
        for future in as_completed(futures):
            entry, fell_back = future.result()
            entries.append((futures[future], entry))
            degraded = degraded or fell_back
    entries.sort(key=lambda item: item[0])
    return {"analysts": [entry for _, entry in entries], "degraded": degraded}


# ───────────────────────── host 节点（找实质性分歧） ─────────────────────────

def host_node(state: AnalysisState) -> dict:
    analysts = state.get("analysts", [])
    round_label = "首轮" if not state.get("debate_history") else f"第{state.get('round_count', 0) + 1}轮"
    if llm_available():
        try:
            content = llm_strict.invoke([
                {"role": "system", "content": "你是A股复盘主持人，只做分歧判断，不输出分析内容。"},
                {"role": "user", "content": build_host_prompt(analysts, state.get("debate_history", []), round_label)},
            ]).content
            has, topic = parse_host_output(content)
            return {"discussion_topic": topic, "discussion_done": not has}
        except Exception:
            pass
    has, topic = rule_host(analysts)
    return {"discussion_topic": topic, "discussion_done": not has, "degraded": True}


# ───────────────────────── debate 节点（循环，max_rounds 控制） ─────────────────────────

def debate_node(state: AnalysisState) -> dict:
    topic = state.get("discussion_topic", "")
    round_no = state.get("round_count", 0) + 1
    if not topic:
        return {
            "round_count": round_no,
            "debate_history": [{"round": round_no, "topic": "", "responses": []}],
        }

    skills = {s.get("id"): s for s in load_skills()}
    analysts = state.get("analysts", [])
    prev = {}
    if state.get("debate_history"):
        for r in state["debate_history"][-1].get("responses", []):
            prev[r.get("skill_name")] = r.get("response", "")
    profile = state.get("profile", "")

    def run_one(analyst: dict) -> tuple[dict, bool]:
        skill = skills.get(analyst.get("skill_id")) or {}
        others = "\n".join(
            f"【{n}】{text[:300]}" for n, text in prev.items() if n != analyst.get("skill_name")
        )
        if llm_available() and skill:
            try:
                content = llm.invoke([
                    {"role": "system", "content": skill.get("prompt", "")},
                    {"role": "user", "content": build_debate_prompt(skill, profile, topic, others)},
                ]).content
                return {
                    "skill_name": analyst.get("skill_name"),
                    "skill_id": analyst.get("skill_id"),
                    "response": (content or "").strip()[:500],
                }, False
            except Exception:
                pass
        return {
            "skill_name": analyst.get("skill_name"),
            "skill_id": analyst.get("skill_id"),
            "response": rule_debate_response(skill, topic),
        }, True

    responses: list[tuple[int, dict]] = []
    degraded = False
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(run_one, a): i for i, a in enumerate(analysts)}
        for future in as_completed(futures):
            resp, fell_back = future.result()
            responses.append((futures[future], resp))
            degraded = degraded or fell_back
    responses.sort(key=lambda item: item[0])

    return {
        "round_count": round_no,
        "debate_history": [{
            "round": round_no,
            "topic": topic,
            "responses": [resp for _, resp in responses],
        }],
        "degraded": degraded,
    }


# ───────────────────────── report 节点（只输出一份 Markdown） ─────────────────────────

def _merge_tags(state: AnalysisState, fallback: list[str] | None = None) -> list[str]:
    tags: list[str] = []
    for a in state.get("analysts", []):
        for t in a.get("tags") or []:
            t = str(t).strip()
            if t and t not in tags:
                tags.append(t)
    if not tags and fallback:
        for t in fallback:
            if t not in tags:
                tags.append(t)
    return tags[:8]


def report_node(state: AnalysisState) -> dict:
    profile = state.get("profile", "")
    metrics = state.get("metrics", {})
    analysts = state.get("analysts", [])
    debate_history = state.get("debate_history", [])
    tags = _merge_tags(state, fallback=rule_tags(metrics))

    if llm_available():
        try:
            content = llm.invoke([
                {"role": "system", "content": "你是一位专业的交易报告撰稿人。"},
                {"role": "user", "content": build_report_prompt(profile, analysts, debate_history, tags)},
            ]).content
            report = ensure_disclaimer(content)
            if report.strip():
                return {"final_report": report, "overall_tags": tags}
        except Exception:
            pass

    report = ensure_disclaimer(rule_report(profile, metrics, analysts, debate_history, tags))
    return {"final_report": report, "overall_tags": tags, "degraded": True}


# ───────────────────────── 路由与构图 ─────────────────────────

def router(state: AnalysisState) -> str:
    """host 之后：无分歧 / 达轮次上限 → report；否则 → debate。"""
    if state.get("discussion_done", True):
        return "report"
    if state.get("round_count", 0) >= state.get("max_rounds", _DEFAULT_MAX_ROUNDS):
        return "report"
    return "debate"


def build_graph():
    graph = StateGraph(AnalysisState)
    graph.add_node("profile", profile_node)
    graph.add_node("analysts", analysts_node)
    graph.add_node("host", host_node)
    graph.add_node("debate", debate_node)
    graph.add_node("report", report_node)

    graph.set_entry_point("profile")
    graph.add_edge("profile", "analysts")
    graph.add_edge("analysts", "host")
    graph.add_conditional_edges("host", router, {"report": "report", "debate": "debate"})
    graph.add_edge("debate", "host")
    graph.add_edge("report", END)
    return graph.compile()


_app = None


def _get_app():
    global _app
    if _app is None:
        _app = build_graph()
    return _app


# ───────────────────────── analyze() 对外入口 ─────────────────────────

def _to_result(state: AnalysisState) -> AnalysisResult:
    report = (state.get("final_report") or "").strip()
    if not report:
        return _fallback_result(state)
    return {
        "final_report": report,
        "analysts": [
            {
                "skill_name": a.get("skill_name", ""),
                "skill_id": a.get("skill_id", ""),
                "analysis": a.get("analysis", ""),
                "suggestion": a.get("suggestion", ""),
                "tags": list(a.get("tags") or []),
            }
            for a in state.get("analysts", [])
        ],
        "debate_history": list(state.get("debate_history", [])),
        "overall_tags": list(state.get("overall_tags") or []),
        "disclaimer": DISCLAIMER,
        "degraded": bool(state.get("degraded", False)),
        "round_count": int(state.get("round_count", 0)),
    }


def _fallback_result(state: AnalysisState) -> AnalysisResult:
    """纯 Python 兜底（连 LangGraph 都不可用时的最后防线），规则引擎全流程。"""
    trades = state.get("trades", []) or []
    metrics = state.get("metrics", {}) or {}
    max_rounds = max(0, int(state.get("max_rounds", _DEFAULT_MAX_ROUNDS)))
    profile = build_profile(trades, metrics)
    analysts = [rule_analyst_entry(s, metrics, profile) for s in load_skills()]

    debate_history: list[dict] = []
    has, topic = rule_host(analysts)
    round_no = 0
    while has and topic and round_no < max_rounds:
        round_no += 1
        responses = [
            {
                "skill_name": a["skill_name"],
                "skill_id": a["skill_id"],
                "response": rule_debate_response({"id": a["skill_id"]}, topic),
            }
            for a in analysts
        ]
        debate_history.append({"round": round_no, "topic": topic, "responses": responses})
        has, topic = rule_host(analysts)

    tags = _merge_tags({"analysts": analysts}, fallback=rule_tags(metrics))
    report = ensure_disclaimer(rule_report(profile, metrics, analysts, debate_history, tags))
    return {
        "final_report": report,
        "analysts": analysts,
        "debate_history": debate_history,
        "overall_tags": tags,
        "disclaimer": DISCLAIMER,
        "degraded": True,
        "round_count": round_no,
    }


def analyze(trades, metrics, max_rounds: int = _DEFAULT_MAX_ROUNDS) -> AnalysisResult:
    """AI 分析入口：profile → analysts → host → debate → report，绝不抛异常。

    trades: 交易记录列表（dict 或带 to_dict() 的对象，仅读取脱敏字段）
    metrics: MetricsResult（dict 或带 to_dict() 的对象）
    max_rounds: 辩论轮次上限，默认 2
    """
    try:
        metrics_dict = _as_dict(metrics)
        try:
            max_rounds = max(0, int(max_rounds if max_rounds is not None else _DEFAULT_MAX_ROUNDS))
        except (TypeError, ValueError):
            max_rounds = _DEFAULT_MAX_ROUNDS
        initial: AnalysisState = {
            "trades": trades or [],
            "metrics": metrics_dict,
            "profile": "",
            "analysts": [],
            "debate_history": [],
            "discussion_topic": "",
            "discussion_done": True,
            "round_count": 0,
            "max_rounds": max_rounds,
            "final_report": "",
            "overall_tags": [],
            "degraded": False,
        }
        result = _get_app().invoke(initial)
        return _to_result(result)
    except Exception:
        # 任何意外都不允许抛给前端：整体降级为规则引擎结果
        safe_metrics = _as_dict(metrics)
        try:
            safe_rounds = max(0, int(max_rounds if max_rounds is not None else _DEFAULT_MAX_ROUNDS))
        except (TypeError, ValueError):
            safe_rounds = _DEFAULT_MAX_ROUNDS
        return _fallback_result({
            "trades": trades or [],
            "metrics": safe_metrics,
            "max_rounds": safe_rounds,
        })
