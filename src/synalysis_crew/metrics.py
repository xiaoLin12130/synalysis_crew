"""指标计算引擎（Issue #2）。

输入：``list[TradeRecord]``（跨模块契约见 docs/requirements.md 第 4 章，鸭子类型，
不依赖 parser 具体实现；``op_type`` 支持 parser.OpType 枚举或中英文文本）。
输出：``MetricsResult``（固定 JSON Schema，全英文 snake_case，可直接 json.dumps）。

字段口径（与需求 2.3 对齐）：
- ``amount``：按 parser 落地契约为「成交金额」（恒正）；本模块以「资金余额差额」
  （交易后资金余额 - 上一笔资金余额）作为现金流的权威信号，``amount`` 仅在余额缺失时兜底，
  因此买入费用入成本、卖出费用扣净额、净转入等口径自动成立；
- 费用口径：``fee`` 含「手续费+其他杂费」，``transfer_fee`` 含「过户费+清算费(B股)」，
  总交易成本 = fee + stamp_tax + commission + transfer_fee（佣金与手续费取 max 防重复）；
- FIFO 配对：同股票先进先出，买入费用入成本、卖出费用扣净额；已实现盈亏按卖出配对笔数统计；
- 翻倍/腰斩：按个股完整持仓周期（首次买入→清仓）收益率 >= +100% / <= -50%；
  期末仍持仓的周期按「成本 vs 最新价」估算（akshare 拉最新价，失败/未安装时按成本兜底，
  并标记 ``market_value_source="cost"``，akshare 调用带超时控制）；
- 区间口径：期初资金 != 0 或期初有持仓（文件内先卖后买）时 ``is_partial=True``。

固定 JSON Schema：::

    {
      "meta": {is_partial, start_date, end_date, calendar_days, active_trading_days, generated_at},
      "account": {initial_balance, ending_balance, net_transfer_in,
                  gross_deposit, gross_withdraw, opening_asset_value,
                  total_return_rate, total_return_rate_net, annualized_return_rate,
                  realized_pnl, total_cost, total_cost_ratio,
                  holding_market_value, holding_cost_value, unrealized_pnl,
                  market_value_source, valuation_date},
      "trading": {total_amount, total_count, buy_count, buy_amount, sell_count, sell_amount,
                  daily_avg_count, daily_avg_amount, distinct_stock_count, current_holding_count,
                  avg_trade_amount, capital_turnover_rate, avg_holding_period_days},
      "pnl": {realized_pnl, win_count, loss_count, win_rate, total_profit, total_loss,
              profit_loss_ratio, max_single_profit, max_single_loss, double_count, halved_count,
              unmatched_sell_amount, monthly_pnl[], equity_curve[], max_drawdown,
              stock_leaderboard{top_profit[], top_loss[]}},
      "behavior": {holding_period_distribution{}, monthly_activity[], max_position{},
                   top5_concentration, favorite_stocks_top10[], style{}, special_operations{}}
    }

说明：
- 收益率/胜率/集中度等比率以小数存储（如 0.1234 = 12.34%）；最大回撤为正值（相对峰值跌幅）；
- ``total_return_rate`` 主口径 = 期初资产基准：
  基准 = 期初资金 + 期初持仓变现估值（≈ unmatched_sell_amount）；
  收益率 = (期末资产 − 基准 − 净转入) / 基准；出金经净转入体现，不会把出金误当亏损。
- 完整历史（期初资产 = 0）时退化为「累计入金基准」：
  收益率 = (期末资产 − 累计入金) / 累计入金（用户视角：总共投入多少、现在剩多少）。
- ``total_return_rate_net`` 为辅口径（纯现金期初基准，忽略期初持仓，仅供对照）。
- 金额四舍五入到 2 位、比率到 4 位；非有限数输出 None，保证严格 JSON 序列化；
- 无配对持仓的卖出（期初持仓）记入 ``unmatched_sell_amount``，不计入已实现盈亏与胜率。
"""

from __future__ import annotations

import math
import queue
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

_EPS = 1e-9

# 操作归一化后的分类（内部枚举）
OP_BUY = "buy"
OP_SELL = "sell"
OP_TRANSFER_IN = "transfer_in"
OP_TRANSFER_OUT = "transfer_out"
OP_REVERSE_REPO = "reverse_repo"
OP_DIVIDEND = "dividend"
OP_BONUS_SHARE = "bonus_share"
OP_INTEREST = "interest"
OP_IPO = "ipo"
OP_OTHER = "other"

# parser.OpType 枚举值 / 常见英文值 -> 内部分类
_EN_OP_MAP: Dict[str, str] = {
    "BUY": OP_BUY,
    "SELL": OP_SELL,
    "BANK_TO_SEC": OP_TRANSFER_IN,
    "SEC_TO_BANK": OP_TRANSFER_OUT,
    "REPO": OP_REVERSE_REPO,
    "INTEREST": OP_INTEREST,
    "DIVIDEND": OP_DIVIDEND,
    "BONUS_SHARE": OP_BONUS_SHARE,
    "DIVIDEND_DIFF": OP_DIVIDEND,  # 股息红利差异并入分红统计
    "DESIGNATED_TRADE": OP_OTHER,
    "UNKNOWN": OP_OTHER,
    "buy": OP_BUY,
    "sell": OP_SELL,
    "transfer_in": OP_TRANSFER_IN,
    "transfer_out": OP_TRANSFER_OUT,
    "reverse_repo": OP_REVERSE_REPO,
    "interest": OP_INTEREST,
    "dividend": OP_DIVIDEND,
    "bonus_share": OP_BONUS_SHARE,
    "ipo": OP_IPO,
    "other": OP_OTHER,
}


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        text = str(int(value))
        if len(text) == 8:
            return datetime.strptime(text, "%Y%m%d").date()
        raise ValueError(f"无法解析交易日期: {value!r}")
    text = str(value).strip()
    for fmt in (
        "%Y%m%d",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y年%m月%d日",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"无法解析交易日期: {value!r}")


def _norm_op(op_type: Any) -> str:
    if isinstance(op_type, Enum):
        op_type = op_type.value
    if op_type is None:
        return OP_OTHER
    text = str(op_type).strip()
    if text in _EN_OP_MAP:
        return _EN_OP_MAP[text]
    low = text.lower()
    if low in _EN_OP_MAP:
        return _EN_OP_MAP[low]
    if "回购" in text:
        return OP_REVERSE_REPO
    if "银行转证券" in text or "银转证" in text:
        return OP_TRANSFER_IN
    if "证券转银行" in text or "证转银" in text:
        return OP_TRANSFER_OUT
    if "红股" in text or "送股" in text:
        return OP_BONUS_SHARE
    if "红利" in text or "股息" in text or "分红" in text:
        return OP_DIVIDEND
    if "利息" in text:
        return OP_INTEREST
    if "申购" in text:
        return OP_IPO
    if "买入" in text or "买" in text:
        return OP_BUY
    if "卖出" in text or "卖" in text:
        return OP_SELL
    return OP_OTHER


def _round2(value: float) -> Optional[float]:
    if value is None or not math.isfinite(value):
        return None
    return round(value, 2)


def _round4(value: float) -> Optional[float]:
    if value is None or not math.isfinite(value):
        return None
    return round(value, 4)


def _months_between(start: date, end: date) -> List[str]:
    months: List[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


@dataclass
class _Rec:
    op: str
    code: str
    name: str
    qty: float
    price: float
    amount: float
    balance: Optional[float]
    fee: float
    stamp_tax: float
    commission: float
    transfer_fee: float
    date: date
    idx: int

    @property
    def gross(self) -> float:
        """成交金额（名义金额）。"""
        return self.qty * self.price

    @property
    def cost_fields(self) -> float:
        """单笔交易成本：印花税 + 过户费 + max(手续费, 佣金)。

        parser 已把「其他杂费」并入 fee、「清算费(B股)」并入 transfer_fee，
        因此这里即为需求 2.3 第 7 项「手续费+印花税+佣金+过户费+杂费」口径。
        max(fee, commission) 用于规避同花顺交割单中两列同值导致的重复计算。
        """
        return self.stamp_tax + self.transfer_fee + max(self.fee, self.commission)


@dataclass
class _Lot:
    qty: float
    unit_cost: float
    buy_date: date


@dataclass
class _Cycle:
    """个股完整持仓周期（首次买入→清仓）。"""

    bought_qty: float = 0.0
    sold_qty: float = 0.0
    buy_cost: float = 0.0
    proceeds: float = 0.0
    remaining_cost: float = 0.0
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    def return_rate(self) -> Optional[float]:
        if self.buy_cost <= _EPS:
            return None
        return (self.proceeds - self.buy_cost) / self.buy_cost


@dataclass
class _StockState:
    lots: deque = field(default_factory=deque)
    cycle: Optional[_Cycle] = None
    pre_qty: float = 0.0  # 期初持仓被卖出的股数（无法配对，pnl 中性）

    def holding_qty(self) -> float:
        return sum(lot.qty for lot in self.lots)

    def holding_cost(self) -> float:
        return sum(lot.qty * lot.unit_cost for lot in self.lots)


def _collect(trades: Sequence[Any]) -> List[_Rec]:
    recs: List[_Rec] = []
    for index, trade in enumerate(trades):
        try:
            balance_raw = getattr(trade, "balance", None)
            recs.append(
                _Rec(
                    op=_norm_op(getattr(trade, "op_type", None)),
                    code=str(getattr(trade, "code", "") or "").strip(),
                    name=str(getattr(trade, "name", "") or "").strip(),
                    qty=_num(getattr(trade, "qty", 0.0)),
                    price=_num(getattr(trade, "price", 0.0)),
                    amount=_num(getattr(trade, "amount", 0.0)),
                    balance=None if balance_raw is None else _num(balance_raw),
                    fee=_num(getattr(trade, "fee", 0.0)),
                    stamp_tax=_num(getattr(trade, "stamp_tax", 0.0)),
                    commission=_num(getattr(trade, "commission", 0.0)),
                    transfer_fee=_num(getattr(trade, "transfer_fee", 0.0)),
                    date=_parse_date(getattr(trade, "trade_date", None)),
                    idx=index,
                )
            )
        except Exception:
            # 单条脏数据跳过（脏数据兜底主要职责在 parser）
            continue
    recs.sort(key=lambda rec: (rec.date, rec.idx))
    return recs


def _estimate_cash_delta(rec: _Rec) -> float:
    """余额缺失时按操作类型估算「发生金额」（买入为负、卖出为正）。"""
    if rec.op == OP_BUY:
        return -(rec.gross + rec.cost_fields)
    if rec.op == OP_SELL:
        return rec.gross - rec.cost_fields
    if rec.op == OP_TRANSFER_IN:
        return rec.amount if rec.amount > 0 else 0.0
    if rec.op == OP_TRANSFER_OUT:
        return -(rec.amount if rec.amount > 0 else 0.0)
    if rec.op == OP_REVERSE_REPO:
        return -(rec.gross + rec.cost_fields)
    return rec.amount


def _parse_spot_frame(frame: Any) -> Optional[Dict[str, float]]:
    """把 akshare 全市场行情表（列：代码/最新价）解析为 代码 -> 最新价。"""
    try:
        import pandas as pd

        if not isinstance(frame, pd.DataFrame) or frame is None or frame.empty:
            return None
        code_col: Any = None
        price_col: Any = None
        for col in frame.columns:
            text = str(col)
            if code_col is None and "代码" in text:
                code_col = col
            elif price_col is None and "最新价" in text:
                price_col = col
        if code_col is None or price_col is None:
            return None
        prices: Dict[str, float] = {}
        for _, row in frame.iterrows():
            code_text = str(row[code_col]).strip()
            if len(code_text) >= 6 and code_text[:2].lower() in ("sh", "sz", "bj"):
                code_text = code_text[2:]
            if code_text.isdigit() and len(code_text) > 6:
                code_text = code_text[-6:]
            try:
                price = float(row[price_col])
            except (TypeError, ValueError):
                continue
            if code_text and price > 0:
                prices[code_text] = price
        return prices or None
    except Exception:
        return None


def _fetch_spot_em_table(ak_module: Any) -> Any:
    """调用 akshare 全市场行情；失败返回 None。"""
    try:
        frame = ak_module.stock_zh_a_spot_em()
        if frame is None or getattr(frame, "empty", True):
            return None
        return frame
    except Exception:
        return None


def _market_prefix(code: str) -> str:
    """沪深京市场前缀（新浪/腾讯行情接口用）。"""
    if code[:1] in ("6", "9"):
        return "sh"
    if code[:1] in ("4", "8"):
        return "bj"
    return "sz"


def _get_price_once(
    requests_module: Any, url: str, params: Optional[Dict[str, str]]
) -> Optional[float]:
    """单次拉价尝试：先走环境代理，再直连（trust_env=False），任一成功即返回。"""
    headers = {"Referer": "https://finance.sina.com.cn"} if "sinajs" in url else {}
    for direct in (False, True):
        try:
            if direct:
                session = requests_module.Session()
                session.trust_env = False
                resp = session.get(url, params=params, headers=headers, timeout=8)
            else:
                resp = requests_module.get(url, params=params, headers=headers, timeout=8)
            if resp.status_code != 200:
                continue
            if "eastmoney" in url:
                data = resp.json().get("data") or {}
                price = data.get("f43")
                if isinstance(price, (int, float)) and float(price) > 0:
                    return float(price)
            else:
                text = resp.text
                if '=""' in text:
                    continue
                parts = text.split('"')[1].split("," if "sinajs" in url else "~")
                if len(parts) > 3:
                    try:
                        price = float(parts[3])  # 新浪/腾讯的第 4 个字段均为最新价
                        if price > 0:
                            return price
                    except (TypeError, ValueError):
                        continue
        except Exception:
            continue
    return None


def _fetch_single_em_price(code: str) -> Optional[float]:
    """逐只兜底拉最新价：eastmoney 实时 -> 新浪 -> 腾讯。

    单股请求体小，且每个源都同时尝试代理与直连，兼容代理对大响应体不稳定、
    个别行情域名被阻断等网络环境；全部失败返回 None（按成本兜底）。
    """
    try:
        import requests
    except Exception:
        return None
    prefix = _market_prefix(code)
    em_market = "1" if prefix == "sh" else "0"
    attempts = [
        (
            "https://push2.eastmoney.com/api/qt/stock/get",
            {"fltt": "2", "invt": "2", "fields": "f43,f58", "secid": f"{em_market}.{code}"},
            prefix,
        ),
        (f"https://hq.sinajs.cn/list={prefix}{code}", None, prefix),
        (f"https://qt.gtimg.cn/q={prefix}{code}", None, prefix),
    ]
    for url, params, _ in attempts:
        price = _get_price_once(requests, url, params)
        if price is not None:
            return price
    return None


def _fetch_latest_prices(
    codes: Sequence[str], timeout: float = 15.0
) -> Optional[Dict[str, float]]:
    """拉取 A 股最新价（代码 -> 最新价）。

    优先 akshare ``stock_zh_a_spot_em`` 全市场表；失败时逐只直连 eastmoney 单股行情；
    全部失败 / 超时 / akshare 未安装时返回 None，由调用方按成本兜底
    （``market_value_source="cost"``）。
    拉取放在守护线程中执行并限制等待时间，超时立即返回且不阻塞进程退出。
    """
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return None

    result_queue: "queue.Queue[Any]" = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            frame = _fetch_spot_em_table(ak)
            if frame is not None:
                result_queue.put(("frame", frame))
                return
            prices: Dict[str, float] = {}
            for code in codes:
                price = _fetch_single_em_price(code)
                if price is not None and price > 0:
                    prices[code] = price
            result_queue.put(("prices", prices))
        except Exception as exc:  # noqa: BLE001
            result_queue.put(("error", exc))

    thread = threading.Thread(
        target=_worker, daemon=True, name="metrics-akshare-price-fetch"
    )
    thread.start()
    try:
        kind, payload = result_queue.get(timeout=timeout)
    except queue.Empty:
        return None
    if kind == "error":
        return None
    if kind == "prices":
        return payload or None
    return _parse_spot_frame(payload)


class MetricsResult(dict):
    """固定 JSON Schema 的结果容器：可直接 ``json.dumps``，支持属性访问与 ``to_dict()``。"""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in self.items()}


def _empty_result() -> MetricsResult:
    now = datetime.now().isoformat(timespec="seconds")
    return MetricsResult(
        {
            "meta": {
                "is_partial": False,
                "start_date": None,
                "end_date": None,
                "calendar_days": 0,
                "active_trading_days": 0,
                "generated_at": now,
            },
            "account": {
                "initial_balance": 0.0,
                "ending_balance": 0.0,
                "net_transfer_in": 0.0,
                "gross_deposit": 0.0,
                "gross_withdraw": 0.0,
                "opening_asset_value": 0.0,
                "total_return_rate": None,
                "total_return_rate_net": None,
                "annualized_return_rate": None,
                "realized_pnl": 0.0,
                "total_cost": 0.0,
                "total_cost_ratio": 0.0,
                "holding_market_value": 0.0,
                "holding_cost_value": 0.0,
                "unrealized_pnl": 0.0,
                "market_value_source": "cost",
                "valuation_date": None,
            },
            "trading": {
                "total_amount": 0.0,
                "total_count": 0,
                "buy_count": 0,
                "buy_amount": 0.0,
                "sell_count": 0,
                "sell_amount": 0.0,
                "daily_avg_count": 0.0,
                "daily_avg_amount": 0.0,
                "distinct_stock_count": 0,
                "current_holding_count": 0,
                "avg_trade_amount": 0.0,
                "capital_turnover_rate": None,
                "avg_holding_period_days": None,
            },
            "pnl": {
                "realized_pnl": 0.0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": None,
                "total_profit": 0.0,
                "total_loss": 0.0,
                "profit_loss_ratio": None,
                "max_single_profit": 0.0,
                "max_single_loss": 0.0,
                "double_count": 0,
                "halved_count": 0,
                "unmatched_sell_amount": 0.0,
                "monthly_pnl": [],
                "equity_curve": [],
                "max_drawdown": 0.0,
                "stock_leaderboard": {"top_profit": [], "top_loss": []},
            },
            "behavior": {
                "holding_period_distribution": {
                    "le_1d": 0,
                    "2_5d": 0,
                    "6_20d": 0,
                    "gt_20d": 0,
                },
                "monthly_activity": [],
                "max_position": {"ratio": 0.0, "code": None, "name": None, "date": None},
                "top5_concentration": 0.0,
                "favorite_stocks_top10": [],
                "style": {
                    "holding_style": "波段",
                    "concentration": "分散",
                    "risk_style": "稳健",
                    "label": "波段·分散·稳健",
                },
                "special_operations": {
                    "reverse_repo": {"count": 0, "amount": 0.0},
                    "dividend": {"count": 0, "amount": 0.0},
                    "bonus_share": {"count": 0, "qty": 0.0},
                    "interest": {"count": 0, "amount": 0.0},
                    "ipo": {"count": 0, "amount": 0.0},
                    "other": {"count": 0, "amount": 0.0},
                },
            },
        }
    )


def compute_metrics(
    trades: Sequence[Any], price_timeout: float = 15.0
) -> MetricsResult:
    """按需求 2.3 计算 A/B/C/D 全部指标，返回固定 JSON Schema 的 MetricsResult。"""
    recs = _collect(trades)
    if not recs:
        return _empty_result()

    # ---- 期初资金（资金余额口径）：首笔交易前的余额 ----
    first = recs[0]
    if first.balance is None:
        initial_balance = 0.0
    elif first.op in (OP_TRANSFER_IN, OP_TRANSFER_OUT):
        # 文件以转账开头：银行转证券视为从 0 开始（完整历史），证转银无法反推则按余额本身
        initial_balance = 0.0 if first.op == OP_TRANSFER_IN else first.balance
    else:
        initial_balance = first.balance - _estimate_cash_delta(first)

    start_date = recs[0].date
    end_date = recs[-1].date

    stocks: Dict[str, _StockState] = {}
    code_name: Dict[str, str] = {}
    special: Dict[str, Dict[str, float]] = {
        kind: {"count": 0.0, "amount": 0.0}
        for kind in (
            OP_REVERSE_REPO,
            OP_DIVIDEND,
            OP_BONUS_SHARE,
            OP_INTEREST,
            OP_IPO,
            OP_OTHER,
        )
    }
    net_transfer = 0.0
    gross_deposit = 0.0
    gross_withdraw = 0.0
    total_cost = 0.0
    balances: List[float] = []
    prev_balance = initial_balance
    last_balance = initial_balance
    last_date = start_date
    prev_month: Optional[str] = None
    snapshots: List[Tuple[str, date, float, float]] = []

    realized_by_month: Dict[str, float] = defaultdict(float)
    activity: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"total": 0, "buy": 0, "sell": 0}
    )
    equity_dates = set()
    counts = {"total": 0, "buy": 0, "sell": 0}
    turnover = {"total": 0.0, "buy": 0.0, "sell": 0.0}
    code_turnover: Dict[str, float] = defaultdict(float)
    code_count: Dict[str, int] = defaultdict(int)
    code_realized: Dict[str, float] = defaultdict(float)

    realized_total = 0.0
    win_count = 0
    loss_count = 0
    total_profit = 0.0
    total_loss = 0.0
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    double_count = 0
    halved_count = 0
    unmatched_sell_amount = 0.0

    dist = {"le_1d": 0, "2_5d": 0, "6_20d": 0, "gt_20d": 0}
    hold_days_wsum = 0.0
    hold_qty_sum = 0.0

    max_pos_ratio = 0.0
    max_pos_code: Optional[str] = None
    max_pos_name: Optional[str] = None
    max_pos_date: Optional[str] = None

    def holding_cost_now() -> float:
        return sum(state.holding_cost() for state in stocks.values())

    def update_max_pos(code: str, name: str, trade_date: date) -> None:
        nonlocal max_pos_ratio, max_pos_code, max_pos_name, max_pos_date
        assets = last_balance + holding_cost_now()
        state = stocks.get(code)
        if state is None or assets <= _EPS:
            return
        cost = state.holding_cost()
        if cost <= _EPS:
            return
        ratio = cost / assets
        if ratio > max_pos_ratio:
            max_pos_ratio = ratio
            max_pos_code = code
            max_pos_name = name
            max_pos_date = trade_date.isoformat()

    for rec in recs:
        month = f"{rec.date.year:04d}-{rec.date.month:02d}"
        if prev_month is None:
            prev_month = month
        elif month != prev_month:
            snapshots.append(
                (prev_month, last_date, last_balance, holding_cost_now())
            )
            prev_month = month
        last_date = rec.date

        cash_delta = (
            rec.balance - prev_balance
            if rec.balance is not None
            else _estimate_cash_delta(rec)
        )
        if rec.balance is not None:
            last_balance = rec.balance
            balances.append(rec.balance)
        total_cost += rec.cost_fields

        if rec.code:
            code_name[rec.code] = rec.name or code_name.get(rec.code, "")

        op = rec.op
        if op in (OP_TRANSFER_IN, OP_TRANSFER_OUT):
            net_transfer += cash_delta
            if cash_delta > 0:
                gross_deposit += cash_delta
            else:
                gross_withdraw += -cash_delta
        elif op in (OP_REVERSE_REPO, OP_DIVIDEND, OP_INTEREST, OP_IPO, OP_OTHER):
            sp = special[op]
            sp["count"] += 1
            sp["amount"] += abs(cash_delta) if op == OP_REVERSE_REPO else cash_delta
        elif op == OP_BONUS_SHARE:
            sp = special[op]
            sp["count"] += 1
            sp["amount"] += rec.qty
            state = stocks.get(rec.code)
            if state is not None and rec.qty > 0:
                total_qty = state.holding_qty()
                if total_qty > _EPS:
                    factor = 1.0 + rec.qty / total_qty
                    for lot in state.lots:
                        lot.qty *= factor
                        lot.unit_cost /= factor  # 红股摊薄单位成本，成本基础总额不变
                    if state.cycle is not None:
                        state.cycle.bought_qty += rec.qty
        elif op in (OP_BUY, OP_SELL) and rec.qty > _EPS:
            code = rec.code
            state = stocks.setdefault(code, _StockState())
            equity_dates.add(rec.date)
            counts["total"] += 1
            code_count[code] += 1
            notional = rec.amount if rec.amount > _EPS else rec.gross
            turnover["total"] += notional
            code_turnover[code] += notional
            activity[month]["total"] += 1
            if op == OP_BUY:
                counts["buy"] += 1
                turnover["buy"] += notional
                activity[month]["buy"] += 1
                cost = -cash_delta if cash_delta < -_EPS else rec.gross + rec.cost_fields
                state.lots.append(_Lot(rec.qty, cost / rec.qty, rec.date))
                if state.cycle is None:
                    state.cycle = _Cycle(start_date=rec.date)
                state.cycle.bought_qty += rec.qty
                state.cycle.buy_cost += cost
                state.cycle.remaining_cost += cost
                update_max_pos(code, rec.name, rec.date)
            else:
                counts["sell"] += 1
                turnover["sell"] += notional
                activity[month]["sell"] += 1
                proceeds = cash_delta if cash_delta > _EPS else rec.gross - rec.cost_fields
                remaining = rec.qty
                pnl = 0.0
                matched_qty = 0.0
                days_wsum = 0.0
                while remaining > _EPS and state.lots:
                    lot = state.lots[0]
                    take = min(lot.qty, remaining)
                    cost_taken = take * lot.unit_cost
                    allocated = proceeds * take / rec.qty
                    pnl += allocated - cost_taken
                    matched_qty += take
                    days_wsum += take * (rec.date - lot.buy_date).days
                    if state.cycle is not None:
                        state.cycle.sold_qty += take
                        state.cycle.proceeds += allocated
                        state.cycle.remaining_cost = max(
                            0.0, state.cycle.remaining_cost - cost_taken
                        )
                    lot.qty -= take
                    if lot.qty <= _EPS:
                        state.lots.popleft()
                    remaining -= take
                if remaining > _EPS:
                    state.pre_qty += remaining
                    unmatched_sell_amount += proceeds * remaining / rec.qty
                if matched_qty > _EPS:
                    realized_total += pnl
                    realized_by_month[month] += pnl
                    code_realized[code] += pnl
                    if pnl > _EPS:
                        win_count += 1
                        total_profit += pnl
                        max_profit = pnl if max_profit is None else max(max_profit, pnl)
                    elif pnl < -_EPS:
                        loss_count += 1
                        total_loss += -pnl
                        max_loss = pnl if max_loss is None else min(max_loss, pnl)
                    avg_days = days_wsum / matched_qty
                    hold_days_wsum += days_wsum
                    hold_qty_sum += matched_qty
                    if avg_days <= 1.0:
                        dist["le_1d"] += 1
                    elif avg_days <= 5.0:
                        dist["2_5d"] += 1
                    elif avg_days <= 20.0:
                        dist["6_20d"] += 1
                    else:
                        dist["gt_20d"] += 1
                if (
                    state.cycle is not None
                    and state.cycle.sold_qty >= state.cycle.bought_qty - _EPS
                ):
                    state.cycle.end_date = rec.date
                    cycle_return = state.cycle.return_rate()
                    if cycle_return is not None:
                        if cycle_return >= 1.0:
                            double_count += 1
                        elif cycle_return <= -0.5:
                            halved_count += 1
                    state.cycle.remaining_cost = 0.0
                    state.cycle = None
                update_max_pos(code, rec.name, rec.date)

        if rec.balance is not None:
            prev_balance = rec.balance

    ending_balance = last_balance
    if prev_month is not None:
        snapshots.append((prev_month, last_date, ending_balance, holding_cost_now()))

    # ---- 期末持仓估值（H3：akshare 最新价，失败按成本兜底） ----
    held_codes = sorted(
        code for code, state in stocks.items() if state.holding_qty() > _EPS
    )
    prices: Dict[str, float] = {}
    market_value_source = "cost"
    valuation_date: Optional[str] = None
    if held_codes:
        fetched = _fetch_latest_prices(held_codes, timeout=price_timeout)
        if fetched:
            market_value_source = "akshare"
            valuation_date = date.today().isoformat()
            prices = fetched

    holding_market_value = 0.0
    holding_cost_value = holding_cost_now()
    code_unrealized: Dict[str, float] = {}
    for code in held_codes:
        state = stocks[code]
        cost = state.holding_cost()
        qty = state.holding_qty()
        price = prices.get(code)
        if price is None or price <= 0:
            price = cost / qty if qty > _EPS else 0.0
        market_value = qty * price
        holding_market_value += market_value
        code_unrealized[code] = market_value - cost
        # 仍持仓的完整周期：按成本 vs 最新价估算翻倍/腰斩
        if state.cycle is not None and state.cycle.remaining_cost > _EPS:
            remaining_qty = state.cycle.bought_qty - state.cycle.sold_qty
            estimate_price = prices.get(code)
            if estimate_price is None or estimate_price <= 0:
                estimate_price = (
                    state.cycle.remaining_cost / remaining_qty
                    if remaining_qty > _EPS
                    else 0.0
                )
            estimated_return = (
                remaining_qty * estimate_price - state.cycle.remaining_cost
            ) / state.cycle.remaining_cost
            if estimated_return >= 1.0:
                double_count += 1
            elif estimated_return <= -0.5:
                halved_count += 1

    # ---- 收益率（H1 区间口径） ----
    # 主口径：期初资产基准（期初资金 + 期初持仓变现估值）；期初资产为 0（完整历史）
    # 时退化为累计入金基准。辅口径：纯现金期初基准（忽略期初持仓）。
    end_assets = ending_balance + holding_market_value
    opening_position_value = unmatched_sell_amount  # 期初持仓变现估值（卖出未配对部分）
    opening_asset_value = initial_balance + opening_position_value
    total_return_rate = None
    total_return_rate_net = None
    if opening_asset_value > _EPS:
        total_return_rate = (
            end_assets - opening_asset_value - net_transfer
        ) / opening_asset_value
    elif gross_deposit > _EPS:
        total_return_rate = (end_assets - gross_deposit) / gross_deposit
    if abs(initial_balance) > _EPS:
        total_return_rate_net = (
            end_assets - initial_balance - net_transfer
        ) / initial_balance
    elif net_transfer > _EPS:
        total_return_rate_net = (end_assets - net_transfer) / net_transfer

    span_days = (end_date - start_date).days
    annualized_return_rate = None
    if (
        total_return_rate is not None
        and total_return_rate > -0.5
        and span_days > 0
    ):
        annualized_return_rate = (1.0 + total_return_rate) ** (365.0 / span_days) - 1.0

    # ---- 交易统计 ----
    total_count = counts["total"]
    active_days = len(equity_dates)
    avg_balance = sum(balances) / len(balances) if balances else 0.0
    avg_trade_amount = turnover["total"] / total_count if total_count else 0.0
    daily_avg_count = total_count / active_days if active_days else 0.0
    daily_avg_amount = turnover["total"] / active_days if active_days else 0.0
    capital_turnover_rate = (
        turnover["total"] / avg_balance if avg_balance > _EPS else None
    )
    avg_holding_days = (
        hold_days_wsum / hold_qty_sum if hold_qty_sum > _EPS else None
    )
    win_rate = (
        win_count / (win_count + loss_count) if (win_count + loss_count) else None
    )
    profit_loss_ratio = (
        total_profit / total_loss if total_loss > _EPS else None
    )
    total_cost_ratio = (
        total_cost / turnover["total"] if turnover["total"] > _EPS else 0.0
    )

    # ---- 月末资产近似净值 + 最大回撤 ----
    equity_curve: List[Dict[str, Any]] = []
    base_equity: Optional[float] = None
    peak_equity: Optional[float] = None
    max_drawdown = 0.0
    for month, snapshot_date, balance, holding_cost in snapshots:
        equity = balance + holding_cost
        if base_equity is None:
            base_equity = equity
        peak_equity = equity if peak_equity is None else max(peak_equity, equity)
        drawdown = (peak_equity - equity) / peak_equity if peak_equity > _EPS else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        equity_curve.append(
            {
                "month": month,
                "date": snapshot_date.isoformat(),
                "balance": _round2(balance),
                "holding_cost": _round2(holding_cost),
                "equity": _round2(equity),
                "net_value": _round4(equity / base_equity)
                if base_equity and base_equity > _EPS
                else 0.0,
                "drawdown": _round4(drawdown),
            }
        )

    months = _months_between(start_date, end_date)
    monthly_pnl = [
        {"month": month, "pnl": _round2(realized_by_month.get(month, 0.0))}
        for month in months
    ]
    monthly_activity = [
        {
            "month": month,
            "total_count": activity[month]["total"],
            "buy_count": activity[month]["buy"],
            "sell_count": activity[month]["sell"],
        }
        for month in months
    ]

    # ---- 个股维度 ----
    top5_codes = sorted(code_turnover.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top5_amount = sum(value for _, value in top5_codes)
    top5_concentration = (
        top5_amount / turnover["total"] if turnover["total"] > _EPS else 0.0
    )
    favorite_sorted = sorted(
        code_count.items(),
        key=lambda kv: (-kv[1], -code_turnover[kv[0]], kv[0]),
    )[:10]
    favorite_stocks_top10 = [
        {
            "code": code,
            "name": code_name.get(code, ""),
            "count": count,
            "amount": _round2(code_turnover[code]),
        }
        for code, count in favorite_sorted
    ]
    leaderboard_entries: List[Dict[str, Any]] = []
    for code in set(code_realized) | set(code_unrealized):
        realized = code_realized.get(code, 0.0)
        unrealized = code_unrealized.get(code, 0.0)
        total = realized + unrealized
        leaderboard_entries.append(
            {
                "code": code,
                "name": code_name.get(code, ""),
                "realized_pnl": _round2(realized),
                "unrealized_pnl": _round2(unrealized),
                "total_pnl": _round2(total),
                "trade_count": code_count.get(code, 0),
            }
        )
    top_profit = sorted(
        (entry for entry in leaderboard_entries if (entry["total_pnl"] or 0) > 0),
        key=lambda entry: entry["total_pnl"],
        reverse=True,
    )[:10]
    top_loss = sorted(
        (entry for entry in leaderboard_entries if (entry["total_pnl"] or 0) < 0),
        key=lambda entry: entry["total_pnl"],
    )[:10]

    # ---- 风格初判（规则引擎） ----
    holding_style = (
        "短线"
        if avg_holding_days is not None and avg_holding_days <= 7
        else "波段"
        if avg_holding_days is None or avg_holding_days <= 30
        else "长线"
    )
    concentration_style = "集中" if top5_concentration >= 0.5 else "分散"
    aggressive = (
        max_pos_ratio >= 0.5
        or (capital_turnover_rate is not None and capital_turnover_rate >= 15)
        or (avg_holding_days is not None and avg_holding_days <= 3)
    )
    conservative = (
        max_pos_ratio <= 0.25
        and (avg_holding_days is None or avg_holding_days >= 15)
        and (capital_turnover_rate is None or capital_turnover_rate <= 5)
    )
    risk_style = "激进" if aggressive else ("稳健" if conservative else "均衡")
    style_label = f"{holding_style}·{concentration_style}·{risk_style}"

    return MetricsResult(
        {
            "meta": {
                "is_partial": abs(initial_balance) > _EPS
                or any(state.pre_qty > _EPS for state in stocks.values()),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "calendar_days": span_days + 1,
                "active_trading_days": active_days,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            },
            "account": {
                "initial_balance": _round2(initial_balance),
                "ending_balance": _round2(ending_balance),
                "net_transfer_in": _round2(net_transfer),
                "gross_deposit": _round2(gross_deposit),
                "gross_withdraw": _round2(gross_withdraw),
                "opening_asset_value": _round2(opening_asset_value),
                "total_return_rate": _round4(total_return_rate)
                if total_return_rate is not None
                else None,
                "total_return_rate_net": _round4(total_return_rate_net)
                if total_return_rate_net is not None
                else None,
                "annualized_return_rate": _round4(annualized_return_rate)
                if annualized_return_rate is not None
                else None,
                "realized_pnl": _round2(realized_total),
                "total_cost": _round2(total_cost),
                "total_cost_ratio": _round4(total_cost_ratio),
                "holding_market_value": _round2(holding_market_value),
                "holding_cost_value": _round2(holding_cost_value),
                "unrealized_pnl": _round2(holding_market_value - holding_cost_value),
                "market_value_source": market_value_source,
                "valuation_date": valuation_date,
            },
            "trading": {
                "total_amount": _round2(turnover["total"]),
                "total_count": total_count,
                "buy_count": counts["buy"],
                "buy_amount": _round2(turnover["buy"]),
                "sell_count": counts["sell"],
                "sell_amount": _round2(turnover["sell"]),
                "daily_avg_count": _round4(daily_avg_count),
                "daily_avg_amount": _round2(daily_avg_amount),
                "distinct_stock_count": len(
                    {code for code in code_count if code_count[code] > 0}
                ),
                "current_holding_count": len(held_codes),
                "avg_trade_amount": _round2(avg_trade_amount),
                "capital_turnover_rate": _round2(capital_turnover_rate)
                if capital_turnover_rate is not None
                else None,
                "avg_holding_period_days": _round2(avg_holding_days)
                if avg_holding_days is not None
                else None,
            },
            "pnl": {
                "realized_pnl": _round2(realized_total),
                "win_count": win_count,
                "loss_count": loss_count,
                "win_rate": _round4(win_rate) if win_rate is not None else None,
                "total_profit": _round2(total_profit),
                "total_loss": _round2(total_loss),
                "profit_loss_ratio": _round4(profit_loss_ratio)
                if profit_loss_ratio is not None
                else None,
                "max_single_profit": _round2(max_profit) if max_profit is not None else 0.0,
                "max_single_loss": _round2(max_loss) if max_loss is not None else 0.0,
                "double_count": double_count,
                "halved_count": halved_count,
                "unmatched_sell_amount": _round2(unmatched_sell_amount),
                "monthly_pnl": monthly_pnl,
                "equity_curve": equity_curve,
                "max_drawdown": _round4(max_drawdown),
                "stock_leaderboard": {
                    "top_profit": top_profit,
                    "top_loss": top_loss,
                },
            },
            "behavior": {
                "holding_period_distribution": dist,
                "monthly_activity": monthly_activity,
                "max_position": {
                    "ratio": _round4(max_pos_ratio),
                    "code": max_pos_code,
                    "name": max_pos_name,
                    "date": max_pos_date,
                },
                "top5_concentration": _round4(top5_concentration),
                "favorite_stocks_top10": favorite_stocks_top10,
                "style": {
                    "holding_style": holding_style,
                    "concentration": concentration_style,
                    "risk_style": risk_style,
                    "label": style_label,
                },
                "special_operations": {
                    "reverse_repo": {
                        "count": int(special[OP_REVERSE_REPO]["count"]),
                        "amount": _round2(special[OP_REVERSE_REPO]["amount"]),
                    },
                    "dividend": {
                        "count": int(special[OP_DIVIDEND]["count"]),
                        "amount": _round2(special[OP_DIVIDEND]["amount"]),
                    },
                    "bonus_share": {
                        "count": int(special[OP_BONUS_SHARE]["count"]),
                        "qty": _round2(special[OP_BONUS_SHARE]["amount"]),
                    },
                    "interest": {
                        "count": int(special[OP_INTEREST]["count"]),
                        "amount": _round2(special[OP_INTEREST]["amount"]),
                    },
                    "ipo": {
                        "count": int(special[OP_IPO]["count"]),
                        "amount": _round2(special[OP_IPO]["amount"]),
                    },
                    "other": {
                        "count": int(special[OP_OTHER]["count"]),
                        "amount": _round2(special[OP_OTHER]["amount"]),
                    },
                },
            },
        }
    )


__all__ = ["MetricsResult", "compute_metrics"]
