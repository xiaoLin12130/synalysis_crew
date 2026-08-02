"""Synalysis Crew — 同花顺交割单分析套件（公共 API）。"""

from .parser import OP_LABELS, OpType, ParseError, TradeRecord, parse_trades

__all__ = [
    "OP_LABELS",
    "OpType",
    "ParseError",
    "TradeRecord",
    "parse_trades",
]
