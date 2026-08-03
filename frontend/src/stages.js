// 分析任务阶段映射（进度条 + 侧栏指示器共用）
export const STAGES = [
  { key: "parse", label: "解析交割单" },
  { key: "metrics", label: "指标计算" },
  { key: "analyze", label: "分析师点评" },
  { key: "moderator", label: "主持人" },
  { key: "debate", label: "辩论" },
  { key: "report", label: "生成报告" },
  { key: "done", label: "完成" },
];

export function stageIndex(stage) {
  const s = String(stage || "").toLowerCase();
  // 后端 stage 枚举：parsing / metrics / profile / analysts / host / debate / report / done
  if (s.includes("pars") || s.includes("解析")) return 0; // parsing / parse_trades
  if (s.includes("metric") || s.includes("compute") || s.includes("指标")) return 1;
  if (s.includes("profile") || s.includes("analysts") || s.includes("点评")) return 2; // 必须匹配 analysts，不能用 analyz
  if (s.includes("host") || s.includes("moderator") || s.includes("主持")) return 3;
  if (s.includes("debat") || s.includes("辩论")) return 4;
  if (s.includes("report") || s.includes("生成")) return 5;
  if (s.includes("done") || s.includes("完成")) return 6;
  return 0;
}

export function stageLabel(stage) {
  const s = String(stage || "").toLowerCase();
  if (s === "queued" || s.includes("queue") || s.includes("提交")) return "排队等待";
  return STAGES[Math.min(stageIndex(stage), STAGES.length - 1)].label;
}
