import React, { useRef, useState } from "react";

export default function UploadView({ onUpload, onDemo, busy }) {
  const [drag, setDrag] = useState(false);
  const [file, setFile] = useState(null);
  const [error, setError] = useState("");
  const inputRef = useRef(null);

  const pick = (f) => {
    setError("");
    if (!f) return;
    const name = f.name || "";
    if (!/\.(xlsx|xls)$/i.test(name)) {
      setError("文件格式不支持：请选择券商导出的 .xlsx 交割单文件");
      setFile(null);
      return;
    }
    if (f.size > 100 * 1024 * 1024) {
      setError("文件过大：请选择 100MB 以内的交割单文件");
      setFile(null);
      return;
    }
    setFile(f);
  };

  const submit = () => {
    if (!file) {
      setError("请先选择交割单文件");
      return;
    }
    onUpload(file);
  };

  return (
    <div className="upload-wrap">
      <div
        className={`dropzone${drag ? " drag" : ""}`}
        onClick={() => inputRef.current && inputRef.current.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          pick(e.dataTransfer.files && e.dataTransfer.files[0]);
        }}
      >
        <div className="dz-icon">📊</div>
        <div className="dz-title">{file ? "已选择文件，点击可重新选择" : "点击选择或拖拽交割单到此处"}</div>
        <div className="dz-sub">
          支持券商导出的 Excel 交割单（.xlsx / .xls）
          <br />
          文件仅用于本次分析，不保存原始数据
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xls"
          style={{ display: "none" }}
          onChange={(e) => pick(e.target.files && e.target.files[0])}
        />
      </div>

      {file ? (
        <div className="file-chip">
          <span className="file-icon">📄</span>
          <span className="fname">{file.name}</span>
          <span className="fsize">{(file.size / 1024 / 1024).toFixed(2)} MB</span>
          <button className="btn btn-outline btn-sm" onClick={() => { setFile(null); setError(""); }}>
            移除
          </button>
        </div>
      ) : null}

      {error ? <div className="upload-error">⚠️ {error}</div> : null}

      <div className="upload-actions">
        <button className="btn btn-accent" disabled={busy || !file} onClick={submit}>
          {busy ? "正在提交…" : "开始分析"}
        </button>
        <button className="btn btn-ghost" disabled={busy} onClick={onDemo}>
          载入演示数据（离线预览）
        </button>
      </div>

      <div className="divider">分析流程</div>
      <div className="upload-notes">
        <b>分四步完成：</b>① 解析交割单（识别完整交易闭环）→ ② 指标计算（收益率曲线 / 胜率 / 回撤 / 翻倍腰斩）→ ③ 5 位 AI 分析师点评与辩论 → ④ 生成最终报告。
        <br />
        <b>口径说明：</b>完整交易 = 个股首次买入至清仓的闭环；分红、红股、逆回购、利息、打新等操作独立统计，不计入交易明细；收益率按「时间加权 TWR（逐日模拟）」计算，比率一律以小数存储、前端 ×100 展示。
      </div>
    </div>
  );
}
