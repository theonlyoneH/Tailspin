import React, { useState, useRef, useEffect } from "react";

const LEVELS = ["TRACE", "DEBUG", "INFO", "WARN", "ERROR"];
const TIME_OPTIONS = [
  { value: "", label: "All time" },
  { value: "5m", label: "Last 5 minutes" },
  { value: "30m", label: "Last 30 minutes" },
  { value: "1h", label: "Last hour" },
  { value: "6h", label: "Last 6 hours" },
  { value: "today", label: "Today" },
];

export default function FilterBar({
  search,
  onSearchChange,
  levels,
  onToggleLevel,
  timeRange,
  onTimeRangeChange,
  live,
  onToggleLive,
  autoScroll,
  onToggleAutoScroll,
  order,
  onToggleOrder,
  connectionState,
}) {
  const [levelOpen, setLevelOpen] = useState(false);
  const levelRef = useRef(null);

  useEffect(() => {
    function onDocClick(e) {
      if (levelRef.current && !levelRef.current.contains(e.target)) setLevelOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  return (
    <div className="filter-bar">
      <div className="search-wrap">
        <span className="search-icon">⌕</span>
        <input
          className="search-input"
          placeholder="Search message, logger, service…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
        {search && (
          <button className="search-clear" onClick={() => onSearchChange("")}>
            ✕
          </button>
        )}
      </div>

      <div className="level-dropdown" ref={levelRef}>
        <button className="filter-chip" onClick={() => setLevelOpen((o) => !o)}>
          Level {levels.size > 0 ? `(${levels.size})` : ""} <span className="caret">▾</span>
        </button>
        {levelOpen && (
          <div className="level-menu">
            {LEVELS.map((lvl) => (
              <label className="level-item" key={lvl}>
                <input
                  type="checkbox"
                  checked={levels.has(lvl)}
                  onChange={() => onToggleLevel(lvl)}
                />
                <span className={`level-dot level-${lvl}`} />
                {lvl}
              </label>
            ))}
          </div>
        )}
      </div>

      <select
        className="filter-chip select"
        value={timeRange}
        onChange={(e) => onTimeRangeChange(e.target.value)}
      >
        {TIME_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <button className="filter-chip" onClick={onToggleOrder} title="Toggle sort order">
        {order === "desc" ? "Newest first" : "Oldest first"}
      </button>

      <div className="spacer" />

      <label className="toggle">
        <input type="checkbox" checked={live} onChange={onToggleLive} />
        <span className={`toggle-track ${live ? "on" : ""}`}>
          <span className="toggle-thumb" />
        </span>
        Live
        <span className={`conn-dot conn-${connectionState}`} title={connectionState} />
      </label>

      <label className="toggle">
        <input type="checkbox" checked={autoScroll} onChange={onToggleAutoScroll} />
        <span className={`toggle-track ${autoScroll ? "on" : ""}`}>
          <span className="toggle-thumb" />
        </span>
        Auto-scroll
      </label>
    </div>
  );
}
