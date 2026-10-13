import React, { memo, useEffect, useRef } from "react";

function formatTime(ts) {
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleTimeString(undefined, { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
  } catch {
    return ts;
  }
}

// Memoised: entry objects keep their identity across live merges, so on each
// new batch only the new rows (and a changed selection) re-render.
const LogRow = memo(function LogRow({ entry: e, selected, onSelect }) {
  return (
    <div
      className={`log-row level-row-${e.level} ${selected ? "selected" : ""}`}
      onClick={() => onSelect(e)}
    >
      <div className="col col-time mono">{formatTime(e.timestamp)}</div>
      <div className="col col-service" title={e.group}>{e.service}</div>
      <div className="col col-level">
        <span className={`level-badge level-${e.level}`}>{e.level}</span>
      </div>
      <div className="col col-logger mono">{e.logger || "—"}</div>
      <div className="col col-message">{e.message}</div>
    </div>
  );
});

export default function LogTable({ entries, onSelect, selectedId, autoScroll, order }) {
  const bottomRef = useRef(null);
  const topRef = useRef(null);

  useEffect(() => {
    if (!autoScroll) return;
    const target = order === "desc" ? topRef.current : bottomRef.current;
    target?.scrollIntoView({ block: "nearest" });
  }, [entries, autoScroll, order]);

  if (entries.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">▤</div>
        <div className="empty-title">No log entries match your filters</div>
        <div className="empty-sub">Select a service on the left, or widen your search / time range.</div>
      </div>
    );
  }

  return (
    <div className="log-table-wrap">
      <div className="log-table-header">
        <div className="col col-time">Timestamp</div>
        <div className="col col-service">Service</div>
        <div className="col col-level">Level</div>
        <div className="col col-logger">Logger</div>
        <div className="col col-message">Message</div>
      </div>
      <div className="log-table-body">
        <div ref={topRef} />
        {entries.map((e) => (
          <LogRow key={e.id} entry={e} selected={selectedId === e.id} onSelect={onSelect} />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
