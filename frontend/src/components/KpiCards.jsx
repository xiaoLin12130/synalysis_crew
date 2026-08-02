import React from "react";
import { cnSource, fmtCny, fmtCount, fmtPct, fmtSignedCny, moneyClass } from "../format";

export default function KpiCards({ metrics }) {
  const account = metrics.account || {};
  const pnl = metrics.pnl || {};
  const basis =
    Number(account.initial_balance) > 0 || Number(pnl.unmatched_sell_amount) > 0 ? "期初资产基准" : "累计入金基准";

  const cards = [
    {
      label: "总收益率",
      value: fmtPct(account.total_return_rate, { signed: true, digits: 2 }),
      sub: `口径：${basis}${
        Number.isFinite(Number(account.total_return_rate_net))
          ? ` ｜ 纯现金口径 ${fmtPct(account.total_return_rate_net, { signed: true })}`
          : ""
      }`,
      cls: moneyClass(account.total_return_rate),
      big: true,
    },
    {
      label: "年化收益率",
      value: fmtPct(account.annualized_return_rate, { signed: true }),
      sub: "按自然日折算",
      cls: moneyClass(account.annualized_return_rate),
    },
    {
      label: "已实现盈亏",
      value: fmtSignedCny(account.realized_pnl),
      sub: "完整交易平仓合计",
      cls: moneyClass(account.realized_pnl),
    },
    {
      label: "胜率",
      value: fmtPct(pnl.win_rate),
      // M7：无完整交易时 win_count/loss_count/win_rate 为 null → 「—」
      sub: `${fmtCount(pnl.win_count)} 胜 / ${fmtCount(pnl.loss_count)} 负（按完整交易）`,
    },
    {
      label: "账户翻倍次数",
      value: `${pnl.double_count ?? 0} 次`,
      sub: "累计收益率达到 +100% 的独立事件次数",
      hl: (pnl.double_count || 0) > 0 ? "hl-accent" : "",
    },
    {
      label: "账户腰斩次数",
      value: `${pnl.halved_count ?? 0} 次`,
      sub: "（1+R）自运行高点回撤 ≥ 50% 的独立事件次数",
      hl: (pnl.halved_count || 0) > 0 ? "hl-danger" : "",
    },
    { label: "累计入金", value: fmtCny(account.gross_deposit) },
    { label: "累计出金", value: fmtCny(account.gross_withdraw) },
    {
      label: "净转入",
      value: fmtSignedCny(account.net_transfer_in),
      cls: moneyClass(account.net_transfer_in),
    },
    {
      label: "总成本",
      value: fmtCny(account.total_cost),
      sub: Number.isFinite(Number(account.total_cost_ratio))
        ? `占总成交额 ${fmtPct(account.total_cost_ratio)}`
        : "累计买入成本（含费用）",
    },
    {
      label: "持仓市值",
      value: fmtCny(account.holding_market_value),
      sub: `来源：${cnSource(account.market_value_source)}`,
    },
    {
      label: "浮动盈亏",
      value: fmtSignedCny(account.unrealized_pnl),
      sub: `持仓成本 ${fmtCny(account.holding_cost_value)}`,
      cls: moneyClass(account.unrealized_pnl),
    },
    {
      label: "期末资产",
      value: fmtCny((Number(account.ending_balance) || 0) + (Number(account.holding_market_value) || 0)),
      sub: `资金 ${fmtCny(account.ending_balance)} + 持仓 ${fmtCny(account.holding_market_value)}`,
    },
  ];

  return (
    <div className="kpi-grid">
      {cards.map((c) => (
        <div key={c.label} className={`kpi${c.big ? " big" : ""}${c.hl ? ` ${c.hl}` : ""}`}>
          <div className="kpi-label">{c.label}</div>
          <div className={`kpi-value${c.cls ? ` ${c.cls}` : ""}`}>{c.value}</div>
          {c.sub ? <div className="kpi-sub">{c.sub}</div> : null}
        </div>
      ))}
    </div>
  );
}
