export async function fetchGroups() {
  const res = await fetch("/groups");
  if (!res.ok) throw new Error("Failed to load groups");
  return res.json();
}

export async function fetchLogs({ services, levels, search, timeRange, order = "desc", limit = 1000 }) {
  const params = new URLSearchParams();
  (services || []).forEach((s) => params.append("services", s));
  (levels || []).forEach((l) => params.append("levels", l));
  if (search) params.append("search", search);
  if (timeRange && timeRange !== "custom") params.append("time_range", timeRange);
  params.append("order", order);
  params.append("limit", String(limit));

  const res = await fetch(`/logs?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to load logs");
  return res.json();
}

export function connectLiveSocket({ services, levels, search, onEntries, onOpen, onClose }) {
  const params = new URLSearchParams();
  (services || []).forEach((s) => params.append("services", s));
  (levels || []).forEach((l) => params.append("levels", l));
  if (search) params.append("search", search);

  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${window.location.host}/ws/logs?${params.toString()}`;
  const ws = new WebSocket(url);

  ws.onopen = () => onOpen && onOpen();
  ws.onclose = () => onClose && onClose();
  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      if (data.type === "logs" && Array.isArray(data.entries)) {
        onEntries(data.entries);
      }
    } catch (e) {
      // ignore malformed frames
    }
  };

  return ws;
}

export function updateSocketFilters(ws, { services, levels, search }) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(
    JSON.stringify({
      type: "update_filters",
      services: services || [],
      levels: levels || [],
      search: search || "",
    })
  );
}
