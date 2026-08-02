"""估算各开发 agent 的进度百分比（基于目标文件落盘情况，非运行时真实进度）。"""

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 每个 agent 的目标文件 + 权重（合计 100）
AGENTS = [
    {
        "id": "A1",
        "name": "解析器",
        "files": [
            ("src/synalysis_crew/__init__.py", 5),
            ("src/synalysis_crew/parser.py", 60),
            ("tests/fixtures/synthetic_trades.py", 15),
            ("tests/test_parser.py", 20),
        ],
    },
    {
        "id": "A2",
        "name": "指标引擎",
        "files": [
            ("src/synalysis_crew/metrics.py", 70),
            ("tests/test_metrics.py", 30),
        ],
    },
    {
        "id": "A3",
        "name": "AI/LangGraph",
        "files": [
            ("src/synalysis_crew/llm.py", 15),
            ("src/synalysis_crew/analyst.py", 25),
            ("src/synalysis_crew/state.py", 10),
            ("src/synalysis_crew/graph.py", 30),
            ("tests/test_analyst.py", 20),
        ],
    },
    {
        "id": "A4",
        "name": "前端",
        "files": [
            ("src/synalysis_crew/storage.py", 25),
            ("src/synalysis_crew/ui.py", 45),
            ("app.py", 30),
        ],
    },
]


def main() -> None:
    now = datetime.now().timestamp()
    rows = []
    total = 0
    for a in AGENTS:
        pct = 0
        active = False
        newest = 0.0
        for rel, weight in a["files"]:
            p = ROOT / rel
            if p.exists() and p.stat().st_size > 30:
                pct += weight
                newest = max(newest, p.stat().st_mtime)
                if now - p.stat().st_mtime < 180:
                    active = True
        rows.append({"id": a["id"], "name": a["name"], "pct": pct, "active": active})
        total += pct

    out = {
        "overall": round(total / len(AGENTS)),
        "checked_at": datetime.now().strftime("%H:%M:%S"),
        "agents": rows,
    }
    if "--json" in sys.argv:
        print(json.dumps(out, ensure_ascii=False))
    else:
        parts = [
            f"{r['id']} {r['name']} {r['pct']}%{'（活跃中）' if r['active'] else ''}"
            for r in rows
        ]
        print(f"总进度 {out['overall']}%（{out['checked_at']}） | " + " | ".join(parts))


if __name__ == "__main__":
    main()
