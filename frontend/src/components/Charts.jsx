import React, { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import { fmtMonth, fmtSignedMoney, num } from "../format";

const ACCENT = "#10A37F";
const DANGER = "#e5484d";
const TEXT2 = "#7a7f87";

const baseTooltip = {
  backgroundColor: "#fff",
  borderColor: "#e7e8eb",
  textStyle: { color: "#17181d", fontSize: 12 },
  extraCssText: "box-shadow:0 4px 14px rgba(0,0,0,.08);border-radius:8px;",
};

export function Chart({ option, height = 320, emptyText = "暂无数据" }) {
  const ref = useRef(null);
  const inst = useRef(null);

  useEffect(() => {
    if (!ref.current) return undefined;
    const chart = echarts.init(ref.current);
    inst.current = chart;
    let ro = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(() => chart.resize());
      ro.observe(ref.current);
    }
    return () => {
      if (ro) ro.disconnect();
      chart.dispose();
      inst.current = null;
    };
  }, []);

  useEffect(() => {
    if (inst.current && option) inst.current.setOption(option, true);
  }, [option]);

  if (!option || !option.series || !option.series.length) {
    return <div className="chart-empty" style={{ height }}>{emptyText}</div>;
  }
  return <div ref={ref} style={{ width: "100%", height }} />;
}

export function ReturnCurveChart({ curve }) {
  const rows = useMemo(
    () =>
      (Array.isArray(curve) ? curve : [])
        .map((p) => ({
          month: fmtMonth(p.month),
          date: p.date || p.month || "",
          r: num(p.return_rate, NaN),
        }))
        .filter((p) => Number.isFinite(p.r)), // null 收益率不伪造为 0
    [curve]
  );
  const drawdown = useMemo(() => {
    let peak = -Infinity;
    return rows.map((d) => {
      peak = Math.max(peak, 1 + d.r);
      return (1 + d.r) / peak - 1;
    });
  }, [rows]);

  const option = useMemo(() => {
    if (!rows.length) return { series: [] };
    return {
      color: [ACCENT, DANGER],
      tooltip: {
        ...baseTooltip,
        trigger: "axis",
        formatter(params) {
          const i = params[0].dataIndex;
          const r = rows[i];
          const dd = drawdown[i];
          return `<b>${r.month}</b>（${r.date}）<br/>累计收益率：<b>${(r.r * 100).toFixed(2)}%</b><br/>回撤：${(dd * 100).toFixed(2)}%`;
        },
      },
      legend: { data: ["累计收益率", "回撤"], top: 4, textStyle: { color: TEXT2, fontSize: 12 } },
      grid: { left: 58, right: 58, top: 44, bottom: 30 },
      xAxis: {
        type: "category",
        data: rows.map((d) => d.month),
        boundaryGap: false,
        axisLine: { lineStyle: { color: "#d8dad5" } },
        axisLabel: { color: TEXT2, fontSize: 11 },
      },
      yAxis: [
        {
          type: "value",
          name: "收益率",
          nameTextStyle: { color: TEXT2, fontSize: 11 },
          axisLabel: { color: TEXT2, formatter: "{value}%" },
          splitLine: { lineStyle: { color: "#eef0ec" } },
        },
        {
          type: "value",
          name: "回撤",
          nameTextStyle: { color: TEXT2, fontSize: 11 },
          axisLabel: { color: TEXT2, formatter: "{value}%" },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "累计收益率",
          type: "line",
          data: rows.map((d) => num((d.r * 100).toFixed(3))),
          smooth: 0.35,
          symbol: "circle",
          symbolSize: 6,
          lineStyle: { width: 2.5, color: ACCENT },
          itemStyle: { color: ACCENT, borderColor: "#fff", borderWidth: 1 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(16,163,127,.22)" },
                { offset: 1, color: "rgba(16,163,127,0)" },
              ],
            },
          },
        },
        {
          name: "回撤",
          type: "line",
          yAxisIndex: 1,
          data: drawdown.map((v) => num((v * 100).toFixed(3))),
          smooth: 0.35,
          symbol: "none",
          lineStyle: { width: 1.5, color: DANGER, type: "dashed" },
          itemStyle: { color: DANGER },
          areaStyle: { opacity: 0.06 },
        },
      ],
    };
  }, [rows, drawdown]);

  return <Chart option={option} height={340} emptyText="暂无收益率数据" />;
}

export function MonthlyPnlChart({ monthly }) {
  const rows = useMemo(
    () => (Array.isArray(monthly) ? monthly : []).map((p) => ({ month: fmtMonth(p.month), pnl: num(p.pnl) })),
    [monthly]
  );
  const option = useMemo(() => {
    if (!rows.length) return { series: [] };
    return {
      tooltip: {
        ...baseTooltip,
        trigger: "axis",
        formatter(params) {
          const i = params[0].dataIndex;
          const v = rows[i].pnl;
          return `<b>${rows[i].month}</b><br/>盈亏：<b style="color:${v >= 0 ? ACCENT : DANGER}">${fmtSignedMoney(v)}</b>`;
        },
      },
      grid: { left: 70, right: 18, top: 24, bottom: 30 },
      xAxis: {
        type: "category",
        data: rows.map((d) => d.month),
        axisLine: { lineStyle: { color: "#d8dad5" } },
        axisLabel: { color: TEXT2, fontSize: 11 },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: TEXT2,
          formatter: (v) => (Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(1)}万` : String(v)),
        },
        splitLine: { lineStyle: { color: "#eef0ec" } },
      },
      series: [
        {
          name: "月度盈亏",
          type: "bar",
          barMaxWidth: 26,
          data: rows.map((d) => ({
            value: num(d.pnl.toFixed(2)),
            itemStyle: {
              color: d.pnl >= 0 ? ACCENT : DANGER,
              borderRadius: d.pnl >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3],
            },
          })),
        },
      ],
    };
  }, [rows]);
  return <Chart option={option} height={340} emptyText="暂无月度盈亏数据" />;
}

const PNL_BUCKETS = [
  { min: -Infinity, max: -10000, label: "亏损 ≥ 1万" },
  { min: -10000, max: -3000, label: "亏损 3千–1万" },
  { min: -3000, max: -1000, label: "亏损 1千–3千" },
  { min: -1000, max: 0, label: "亏损 0–1千" },
  { min: 0, max: 1000, label: "盈利 0–1千" },
  { min: 1000, max: 3000, label: "盈利 1千–3千" },
  { min: 3000, max: 10000, label: "盈利 3千–1万" },
  { min: 10000, max: Infinity, label: "盈利 ≥ 1万" },
];

export function PnlDistributionChart({ trades }) {
  const rows = useMemo(() => {
    const list = (Array.isArray(trades) ? trades : []).filter(
      (t) => t.pnl != null && Number.isFinite(Number(t.pnl))
    );
    return PNL_BUCKETS.map((b, bi) => ({
      label: b.label,
      count: list.filter((t) => Number(t.pnl) >= b.min && Number(t.pnl) < b.max).length,
      negative: bi < 4,
    }));
  }, [trades]);

  const option = useMemo(() => {
    if (!rows.some((r) => r.count > 0)) return { series: [] };
    return {
      tooltip: {
        ...baseTooltip,
        trigger: "axis",
        formatter(params) {
          const i = params[0].dataIndex;
          return `<b>${rows[i].label}</b><br/>交易笔数：<b>${rows[i].count}</b>`;
        },
      },
      grid: { left: 52, right: 20, top: 30, bottom: 36 },
      xAxis: {
        type: "category",
        data: rows.map((r) => r.label),
        axisLine: { lineStyle: { color: "#d8dad5" } },
        axisLabel: { color: TEXT2, fontSize: 11, interval: 0, rotate: 24 },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: TEXT2 },
        splitLine: { lineStyle: { color: "#eef0ec" } },
      },
      series: [
        {
          name: "笔数",
          type: "bar",
          barMaxWidth: 26,
          label: { show: true, position: "top", fontSize: 11, color: TEXT2 },
          data: rows.map((r) => ({
            value: r.count,
            itemStyle: { color: r.negative ? DANGER : ACCENT, borderRadius: [3, 3, 0, 0] },
          })),
        },
      ],
    };
  }, [rows]);
  return <Chart option={option} height={300} emptyText="暂无盈亏分布数据" />;
}

export function HoldingPeriodChart({ distribution }) {
  const rows = useMemo(
    () => (Array.isArray(distribution) ? distribution : []).map((d) => ({
      label: (d && (d.label || d.range)) || "—",
      count: num(d && (d.count ?? d.value)),
    })),
    [distribution]
  );
  const option = useMemo(() => {
    if (!rows.length) return { series: [] };
    return {
      tooltip: {
        ...baseTooltip,
        trigger: "axis",
        formatter(params) {
          const i = params[0].dataIndex;
          return `<b>${rows[i].label}</b><br/>交易笔数：<b>${rows[i].count}</b>`;
        },
      },
      grid: { left: 48, right: 20, top: 30, bottom: 30 },
      xAxis: {
        type: "category",
        data: rows.map((r) => r.label),
        axisLine: { lineStyle: { color: "#d8dad5" } },
        axisLabel: { color: TEXT2, fontSize: 11 },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: TEXT2 },
        splitLine: { lineStyle: { color: "#eef0ec" } },
      },
      series: [
        {
          name: "交易笔数",
          type: "bar",
          barMaxWidth: 26,
          label: { show: true, position: "top", fontSize: 11, color: TEXT2 },
          data: rows.map((r) => ({
            value: r.count,
            itemStyle: { color: ACCENT, borderRadius: [3, 3, 0, 0] },
          })),
        },
      ],
    };
  }, [rows]);
  return <Chart option={option} height={300} emptyText="暂无持仓周期数据" />;
}

export function MonthlyActivityChart({ activity }) {
  const rows = useMemo(
    () =>
      (Array.isArray(activity) ? activity : []).map((p) => ({
        month: fmtMonth(p.month),
        count: num(p.count ?? p.trade_count),
        buy: num(p.buy_count),
        sell: num(p.sell_count),
      })),
    [activity]
  );
  const hasPair = rows.some((r) => r.buy > 0 || r.sell > 0);
  const option = useMemo(() => {
    if (!rows.length) return { series: [] };
    return {
      tooltip: {
        ...baseTooltip,
        trigger: "axis",
      },
      legend: hasPair ? { data: ["买入", "卖出"], top: 4, textStyle: { color: TEXT2, fontSize: 12 } } : undefined,
      grid: { left: 48, right: 20, top: 34, bottom: 30 },
      xAxis: {
        type: "category",
        data: rows.map((r) => r.month),
        axisLine: { lineStyle: { color: "#d8dad5" } },
        axisLabel: { color: TEXT2, fontSize: 11 },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: TEXT2 },
        splitLine: { lineStyle: { color: "#eef0ec" } },
      },
      series: hasPair
        ? [
            { name: "买入", type: "bar", stack: "a", barMaxWidth: 22, data: rows.map((r) => r.buy), itemStyle: { color: ACCENT, borderRadius: [0, 0, 0, 0] } },
            { name: "卖出", type: "bar", stack: "a", barMaxWidth: 22, data: rows.map((r) => r.sell), itemStyle: { color: "#9aa1ad", borderRadius: [3, 3, 0, 0] } },
          ]
        : [
            {
              name: "交易次数",
              type: "bar",
              barMaxWidth: 26,
              label: { show: true, position: "top", fontSize: 11, color: TEXT2 },
              data: rows.map((r) => ({ value: r.count, itemStyle: { color: ACCENT, borderRadius: [3, 3, 0, 0] } })),
            },
          ],
    };
  }, [rows, hasPair]);
  return <Chart option={option} height={300} emptyText="暂无月度活跃度数据" />;
}
