import React, { useEffect, useMemo, useRef } from "react";
import * as echarts from "echarts";
import { fmtMonth, fmtSignedMoney, num } from "../format";
import { buildPnlDistribution } from "../pnlUtils";

const ACCENT = "#10A37F";
const DANGER = "#e5484d";
// v2.3 红涨绿跌：正收益红、负收益绿、零值中性灰
const UP_RED = "#e03131";
const DOWN_GREEN = "#0ca678";
const NEUTRAL = "#adb5bd";
const TEXT2 = "#7a7f87";
const pnlBarColor = (v) => (v > 0 ? UP_RED : v < 0 ? DOWN_GREEN : NEUTRAL);

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

export function ReturnCurveChart({ curve, events }) {
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
  const doubleEvents = useMemo(
    () => (events && Array.isArray(events.doubleEvents) ? events.doubleEvents : []),
    [events]
  );
  const halvedEvents = useMemo(
    () => (events && Array.isArray(events.halvedEvents) ? events.halvedEvents : []),
    [events]
  );
  const drawdown = useMemo(() => {
    let peak = -Infinity;
    return rows.map((d) => {
      peak = Math.max(peak, 1 + d.r);
      return (1 + d.r) / peak - 1;
    });
  }, [rows]);

  // 事件日期为实际触发日（可能与月末曲线点不同）：就近对齐到曲线点
  const nearestIndex = (date) => {
    if (!date) return -1;
    const t = Date.parse(String(date));
    if (!Number.isFinite(t)) return -1;
    let best = -1;
    let bestDist = Infinity;
    rows.forEach((r, i) => {
      const rt = Date.parse(r.date || "");
      if (!Number.isFinite(rt)) return;
      const d = Math.abs(rt - t);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    return best;
  };

  const doublePts = useMemo(
    () =>
      doubleEvents
        .map((e) => ({ e, index: nearestIndex(e.date) }))
        .filter((p) => p.index >= 0 && Number.isFinite(Number(p.e.return_rate)))
        .map((p) => ({ ...p, y: num((Number(p.e.return_rate) * 100).toFixed(3)) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [doubleEvents, rows]
  );
  const halvedPts = useMemo(
    () =>
      halvedEvents
        .map((e) => ({ e, index: nearestIndex(e.date) }))
        .filter((p) => p.index >= 0 && Number.isFinite(Number(p.e.return_rate)))
        .map((p) => ({ ...p, y: num((Number(p.e.return_rate) * 100).toFixed(3)) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [halvedEvents, rows]
  );

  const option = useMemo(() => {
    if (!rows.length) return { series: [] };
    const legend = ["累计收益率", "回撤"];
    if (doublePts.length) legend.push("翻倍事件");
    if (halvedPts.length) legend.push("腰斩事件");
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
      legend: { data: legend, top: 4, textStyle: { color: TEXT2, fontSize: 12 } },
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
        ...(doublePts.length
          ? [
              {
                name: "翻倍事件",
                type: "scatter",
                data: doublePts.map((p) => [p.index, p.y]),
                symbol: "diamond",
                symbolSize: 15,
                itemStyle: { color: UP_RED, borderColor: "#fff", borderWidth: 2 },
                label: { show: true, formatter: "翻倍", position: "top", color: UP_RED, fontSize: 11, fontWeight: 700 },
                z: 20,
                tooltip: {
                  trigger: "item",
                  formatter(params) {
                    const p = doublePts[params.dataIndex];
                    return `<b style="color:${UP_RED}">翻倍事件</b><br/>日期：${p.e.date}<br/>累计收益率：${(Number(p.e.return_rate) * 100).toFixed(2)}%`;
                  },
                },
              },
            ]
          : []),
        ...(halvedPts.length
          ? [
              {
                name: "腰斩事件",
                type: "scatter",
                data: halvedPts.map((p) => [p.index, p.y]),
                symbol: "triangle",
                symbolSize: 15,
                itemStyle: { color: DOWN_GREEN, borderColor: "#fff", borderWidth: 2 },
                label: { show: true, formatter: "腰斩", position: "top", color: DOWN_GREEN, fontSize: 11, fontWeight: 700 },
                z: 20,
                tooltip: {
                  trigger: "item",
                  formatter(params) {
                    const p = halvedPts[params.dataIndex];
                    return `<b style="color:${DOWN_GREEN}">腰斩事件</b><br/>日期：${p.e.date}<br/>累计收益率：${(Number(p.e.return_rate) * 100).toFixed(2)}%`;
                  },
                },
              },
            ]
          : []),
      ],
    };
  }, [rows, drawdown, doublePts, halvedPts]);

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
          return `<b>${rows[i].month}</b><br/>盈亏：<b style="color:${pnlBarColor(v)}">${fmtSignedMoney(v)}</b>`;
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
              color: pnlBarColor(d.pnl),
              borderRadius: d.pnl >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3],
            },
          })),
        },
      ],
    };
  }, [rows]);
  return <Chart option={option} height={340} emptyText="暂无月度盈亏数据" />;
}

export function PnlDistributionChart({ trades }) {
  // v2.3：500 元步长分箱（超出 ±10000 合并开区间），柱色红涨绿跌
  const rows = useMemo(() => buildPnlDistribution(trades), [trades]);

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
        axisLabel: { color: TEXT2, fontSize: 10, rotate: 45 },
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
            itemStyle: {
              color: r.positive ? UP_RED : r.zero ? NEUTRAL : DOWN_GREEN,
              borderRadius: [3, 3, 0, 0],
            },
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
