import React from "react";

function Field({ label, value, mono }) {
  if (!value) return null;
  return (
    <div className="field-row">
      <div className="field-label">{label}</div>
      <div className={`field-value ${mono ? "mono" : ""}`}>{value}</div>
    </div>
  );
}

export default function LogDetailDrawer({ entry, onClose }) {
  if (!entry) return null;
  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <span className={`level-badge level-${entry.level}`}>{entry.level}</span>
          <span className="drawer-title">{entry.service}</span>
          <button className="drawer-close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="drawer-body">
          <Field label="Timestamp" value={entry.timestamp} mono />
          <Field label="Group" value={entry.group} />
          <Field label="Service" value={entry.service} />
          <Field label="Logger" value={entry.logger} mono />
          <Field label="Thread" value={entry.thread} mono />
          <Field label="Source file" value={entry.file} mono />

          <div className="field-row column">
            <div className="field-label">Message</div>
            <pre className="field-block">{entry.message}</pre>
          </div>

          <div className="field-row column">
            <div className="field-label">Raw log</div>
            <pre className="field-block raw">{entry.raw}</pre>
          </div>
        </div>
      </div>
    </div>
  );
}
