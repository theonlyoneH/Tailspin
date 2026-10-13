import React, { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import FilterBar from "./components/FilterBar.jsx";
import LogTable from "./components/LogTable.jsx";
import LogDetailDrawer from "./components/LogDetailDrawer.jsx";
import { fetchGroups, fetchLogs, connectLiveSocket, updateSocketFilters } from "./api.js";

const MAX_CLIENT_ENTRIES = 5000;

// Combine two entry lists, dropping duplicate ids, sorted the same way the
// backend sorts (timestamp, then arrival id) and capped to MAX_CLIENT_ENTRIES.
function mergeEntries(base, extra, order) {
  if (extra.length === 0) return base;
  const seen = new Set(base.map((e) => e.id));
  const merged = base.concat(extra.filter((e) => !seen.has(e.id)));
  const dir = order === "desc" ? -1 : 1;
  merged.sort((a, b) => dir * (a.ts_epoch - b.ts_epoch || a.id - b.id));
  return merged.length > MAX_CLIENT_ENTRIES ? merged.slice(0, MAX_CLIENT_ENTRIES) : merged;
}

export default function App() {
  const [groups, setGroups] = useState({});
  const [selectedServices, setSelectedServices] = useState(new Set());
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [levels, setLevels] = useState(new Set());
  const [timeRange, setTimeRange] = useState("");
  const [order, setOrder] = useState("desc");
  const [live, setLive] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const [entries, setEntries] = useState([]);
  const [selectedEntry, setSelectedEntry] = useState(null);
  const [connectionState, setConnectionState] = useState("idle");
  const [loading, setLoading] = useState(false);

  const wsRef = useRef(null);
  const orderRef = useRef(order);
  orderRef.current = order;
  // While a snapshot request is in flight, live entries are parked here and
  // merged into the snapshot when it lands - otherwise the snapshot response
  // would overwrite anything streamed in the meantime.
  const snapshotPendingRef = useRef(false);
  const liveBufferRef = useRef([]);
  const requestIdRef = useRef(0);

  // discover groups/services, refresh periodically to pick up new services
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const g = await fetchGroups();
        if (!cancelled) setGroups(g);
      } catch (e) {
        // backend not reachable yet - fine, will retry
      }
    }
    load();
    const interval = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // debounce search input
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  const servicesArr = Array.from(selectedServices);
  const levelsArr = Array.from(levels);

  // fetch a fresh snapshot whenever filters change
  const refreshSnapshot = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    snapshotPendingRef.current = true;
    liveBufferRef.current = [];
    setLoading(true);
    let snapshot = null;
    try {
      const data = await fetchLogs({
        services: servicesArr,
        levels: levelsArr,
        search: debouncedSearch,
        timeRange,
        order,
        limit: 1000,
      });
      snapshot = data.entries;
    } catch (e) {
      // ignore transient errors - keep what's on screen
    }
    if (requestId !== requestIdRef.current) return; // a newer request superseded this one
    const buffered = liveBufferRef.current;
    snapshotPendingRef.current = false;
    liveBufferRef.current = [];
    setEntries((prev) => mergeEntries(snapshot ?? prev, buffered, order));
    setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(servicesArr), JSON.stringify(levelsArr), debouncedSearch, timeRange, order]);

  useEffect(() => {
    refreshSnapshot();
  }, [refreshSnapshot]);

  // manage the live websocket connection
  useEffect(() => {
    if (!live) {
      wsRef.current?.close();
      wsRef.current = null;
      setConnectionState("paused");
      return;
    }

    setConnectionState("connecting");
    const ws = connectLiveSocket({
      services: servicesArr,
      levels: levelsArr,
      search: debouncedSearch,
      onOpen: () => setConnectionState("live"),
      onClose: () => setConnectionState("disconnected"),
      onEntries: (newOnes) => {
        if (snapshotPendingRef.current) {
          liveBufferRef.current.push(...newOnes);
          return;
        }
        setEntries((prev) => mergeEntries(prev, newOnes, orderRef.current));
      },
    });
    wsRef.current = ws;
    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, JSON.stringify(servicesArr), JSON.stringify(levelsArr), debouncedSearch]);

  const toggleService = (svc) => {
    setSelectedServices((prev) => {
      const next = new Set(prev);
      next.has(svc) ? next.delete(svc) : next.add(svc);
      return next;
    });
  };

  // `services` here are service keys (unique), not display names
  const toggleGroup = (_group, services, select) => {
    setSelectedServices((prev) => {
      const next = new Set(prev);
      services.forEach((s) => (select ? next.add(s) : next.delete(s)));
      return next;
    });
  };

  const toggleLevel = (lvl) => {
    setLevels((prev) => {
      const next = new Set(prev);
      next.has(lvl) ? next.delete(lvl) : next.add(lvl);
      return next;
    });
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">▣</span>
          <span className="brand-name">Live Log Viewer</span>
        </div>
        <div className="topbar-meta">
          {loading ? "Refreshing…" : `${entries.length.toLocaleString()} entries in view`}
        </div>
      </header>

      <div className="app-body">
        <Sidebar
          groups={groups}
          selectedServices={selectedServices}
          onToggleService={toggleService}
          onToggleGroup={toggleGroup}
        />

        <main className="main-panel">
          <FilterBar
            search={search}
            onSearchChange={setSearch}
            levels={levels}
            onToggleLevel={toggleLevel}
            timeRange={timeRange}
            onTimeRangeChange={setTimeRange}
            live={live}
            onToggleLive={() => setLive((v) => !v)}
            autoScroll={autoScroll}
            onToggleAutoScroll={() => setAutoScroll((v) => !v)}
            order={order}
            onToggleOrder={() => setOrder((o) => (o === "desc" ? "asc" : "desc"))}
            connectionState={connectionState}
          />

          <LogTable
            entries={entries}
            onSelect={setSelectedEntry}
            selectedId={selectedEntry?.id}
            autoScroll={autoScroll}
            order={order}
          />
        </main>
      </div>

      <LogDetailDrawer entry={selectedEntry} onClose={() => setSelectedEntry(null)} />
    </div>
  );
}
