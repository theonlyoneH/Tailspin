import React, { useState } from "react";

// `groups` is { groupName: [{ key, name }, ...] }. Selection is tracked by
// service key, since display names can repeat across groups.
export default function Sidebar({ groups, selectedServices, onToggleService, onToggleGroup }) {
  // track collapsed (not expanded) groups so groups discovered after mount
  // start out open
  const [collapsed, setCollapsed] = useState(() => new Set());

  const toggleExpand = (group) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(group) ? next.delete(group) : next.add(group);
      return next;
    });
  };

  const groupNames = Object.keys(groups);

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-title">Groups</span>
      </div>
      <div className="sidebar-scroll">
        {groupNames.length === 0 && (
          <div className="sidebar-empty">No log sources discovered yet.</div>
        )}
        {groupNames.map((group) => {
          const services = groups[group];
          const keys = services.map((s) => s.key);
          const isOpen = !collapsed.has(group);
          const allSelected = keys.every((k) => selectedServices.has(k));
          const someSelected = keys.some((k) => selectedServices.has(k));
          return (
            <div className="group-block" key={group}>
              <div className="group-row">
                <button className="disclosure" onClick={() => toggleExpand(group)} aria-label="toggle group">
                  <span className={`chevron ${isOpen ? "open" : ""}`}>▶</span>
                </button>
                <label className="group-label">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    ref={(el) => el && (el.indeterminate = someSelected && !allSelected)}
                    onChange={() => onToggleGroup(group, keys, !allSelected)}
                  />
                  {group}
                </label>
                <span className="count-pill">{services.length}</span>
              </div>
              {isOpen && (
                <div className="service-list">
                  {services.map((svc) => (
                    <label className="service-row" key={svc.key} title={svc.key}>
                      <input
                        type="checkbox"
                        checked={selectedServices.has(svc.key)}
                        onChange={() => onToggleService(svc.key)}
                      />
                      <span>{svc.name}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
