"""LangGraph 共享状态与对外返回结构定义（Issue #3 AI 分析模块）。"""

import operator
from typing import Annotated, Any, TypedDict


class AnalysisState(TypedDict, total=False):
    """AI 分析全流程共享状态：profile → analysts → host → debate → report。"""

    # 输入（由前端传入，本模块只读）
    trades: list[Any]          # 交易记录（仅使用代码/名称/数量/价格/日期，敏感字段天然忽略）
    metrics: dict              # 指标摘要（MetricsResult 契约；metrics.py 未落地时可为 dict）

    # profile 节点产出：脱敏交易画像
    profile: str

    # analysts 节点产出：5 位分析师结果
    analysts: list[dict]

    # debate 节点产出（累加器：每轮一条）
    debate_history: Annotated[list[dict], operator.add]

    # host 节点产出：分歧判断与议题
    discussion_topic: str
    discussion_done: bool
    round_count: int           # 已完成的辩论轮数
    max_rounds: int            # 辩论轮次上限（默认 2）

    # report 节点产出
    final_report: str          # 唯一一份最终 Markdown 报告
    overall_tags: list[str]    # 汇总幽默标签
    degraded: bool             # 是否降级（无 Key / 调用失败 → 规则引擎兜底）


class AnalysisResult(TypedDict):
    """analyze() 对外返回契约（见需求文档第 4 章）。"""

    final_report: str
    analysts: list[dict]
    debate_history: list[dict]
    overall_tags: list[str]
    disclaimer: str
    degraded: bool
    round_count: int
