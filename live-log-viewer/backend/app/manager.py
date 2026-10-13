import asyncio
import datetime
import logging
import os
import time
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from . import config
from .discovery import discover, iter_log_files, DiscoveryResult
from .tailer import FileTailer
from .models import LogEntry

log = logging.getLogger("logviewer")

TIME_RANGE_SECONDS = {
    "5m": 5 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "6h": 6 * 60 * 60,
}

# How long a single websocket send may take before that client is skipped
# for this batch - one slow browser tab must not stall everyone else.
SEND_TIMEOUT_SECONDS = 5.0


class _DirtyHandler(FileSystemEventHandler):
    """Runs on the watchdog thread. Just records which paths changed -
    all real work happens on the asyncio loop to avoid cross-thread issues."""

    def __init__(self, manager: "LogManager"):
        self.manager = manager

    def _touch(self, path: str):
        if path.rsplit(".", 1)[-1].lower() in ("log", "txt"):
            # normalised so it matches the os.walk-built keys in `tailers`
            self.manager.dirty_paths.add(os.path.normpath(path))

    def on_modified(self, event):
        if not event.is_directory:
            self._touch(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._touch(event.src_path)
        else:
            self.manager.needs_rediscovery = True

    def on_moved(self, event):
        if not event.is_directory:
            self._touch(event.dest_path)


class LogManager:
    def __init__(self, root: str = None):
        self.root = os.path.abspath(root or config.LOG_ROOT)
        self.discovery: DiscoveryResult = DiscoveryResult()
        self.tailers: Dict[str, FileTailer] = {}          # abs path -> tailer
        self.file_service: Dict[str, str] = {}             # abs path -> service key
        self.buffers: Dict[str, deque] = {}                # service key -> ring buffer
        self.dirty_paths: Set[str] = set()
        self.needs_rediscovery = False
        self.observer: Optional[Observer] = None
        self.subscribers: List["Subscriber"] = []

    # ---------------------------------------------------------------- setup
    def start_watching(self):
        if not self.root or not os.path.isdir(self.root):
            return
        handler = _DirtyHandler(self)
        self.observer = Observer()
        self.observer.schedule(handler, self.root, recursive=True)
        self.observer.start()

    def stop_watching(self):
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=2)

    @property
    def buffered_count(self) -> int:
        return sum(len(b) for b in self.buffers.values())

    async def initial_scan(self):
        await self._rescan(broadcast=False)

    def _scan_disk(self) -> Tuple[DiscoveryResult, List[Tuple[str, str]]]:
        """Blocking filesystem walk - always run via asyncio.to_thread."""
        discovery = discover(self.root)
        files = [
            (path, service.key)
            for service in discovery.services.values()
            for path in iter_log_files(service)
        ]
        return discovery, files

    async def _rescan(self, broadcast: bool):
        """Re-discover services/files: start tailing new files (seeding them
        with a backfill), and drop tailers for files that no longer exist."""
        discovery, files = await asyncio.to_thread(self._scan_disk)
        self.discovery = discovery

        current: Set[str] = set()
        new_tailers: List[Tuple[str, str, FileTailer]] = []
        for path, service_key in files:
            current.add(path)
            self.file_service[path] = service_key
            if path not in self.tailers:
                tailer = FileTailer(path)
                self.tailers[path] = tailer
                new_tailers.append((path, service_key, tailer))

        for path in list(self.tailers):
            if path not in current:
                del self.tailers[path]
                self.file_service.pop(path, None)

        if not new_tailers:
            return
        seeded = await asyncio.to_thread(
            lambda: [(p, k, t.seed_from_end(config.BACKFILL_BYTES)) for p, k, t in new_tailers]
        )
        new_entries: List[LogEntry] = []
        for path, service_key, records in seeded:
            new_entries.extend(self._ingest(records, service_key, path))
        # Files that appear while running (new service, rotation, a new dated
        # folder) are part of the live stream; the startup backfill is not.
        if broadcast and new_entries:
            await self._broadcast(new_entries)

    def _ingest(self, records: List[dict], service_key: str, path: str) -> List[LogEntry]:
        service = self.discovery.services.get(service_key)
        if not service or not records:
            return []
        buf = self.buffers.get(service_key)
        if buf is None:
            buf = self.buffers[service_key] = deque(maxlen=config.MAX_BUFFER_SIZE)
        rel_file = os.path.relpath(path, self.root).replace(os.sep, "/")
        entries = []
        for r in records:
            entry = LogEntry(
                id=LogEntry.next_id(),
                timestamp=r["timestamp"],
                ts_epoch=r["ts_epoch"] or time.time(),
                group=service.group,
                service=service.name,
                service_key=service_key,
                level=r.get("level", "INFO"),
                logger=r.get("logger", ""),
                thread=r.get("thread", ""),
                message=r.get("message", ""),
                raw=r.get("raw", ""),
                file=rel_file,
            )
            entries.append(entry)
            buf.append(entry)
        return entries

    # ------------------------------------------------------------- runtime
    async def poll_loop(self):
        """Background task: drains dirty files marked by watchdog, tails
        them, appends new entries to the ring buffers and fans them out to
        connected websocket subscribers. Also periodically re-scans for
        brand-new services/files."""
        tick = 0
        while True:
            await asyncio.sleep(0.3)
            tick += 1
            try:
                await self._poll_once(tick)
            except Exception:
                # never let one bad file/tick kill live tailing for good
                log.exception("poll loop iteration failed")

    async def _poll_once(self, tick: int):
        if self.needs_rediscovery or tick % 100 == 0:  # ~every 30s, or on new dir/file
            self.needs_rediscovery = False
            await self._rescan(broadcast=True)

        new_entries: List[LogEntry] = []

        if self.dirty_paths:
            paths = list(self.dirty_paths)
            self.dirty_paths.clear()
            work = []
            for path in paths:
                tailer = self.tailers.get(path)
                service_key = self.file_service.get(path)
                if tailer is None or service_key is None:
                    # a file we don't know yet - pick it up on the next tick
                    # rather than waiting for the 30s periodic rescan
                    self.needs_rediscovery = True
                    continue
                work.append((path, service_key, tailer))
            if work:
                results = await asyncio.to_thread(
                    lambda: [(p, k, t.read_new()) for p, k, t in work]
                )
                for path, service_key, records in results:
                    new_entries.extend(self._ingest(records, service_key, path))

        for path, tailer in list(self.tailers.items()):
            if tailer.has_pending:
                records = tailer.flush_if_idle(config.FLUSH_IDLE_SECONDS)
                if records:
                    new_entries.extend(self._ingest(records, self.file_service[path], path))

        if new_entries:
            await self._broadcast(new_entries)

    async def _broadcast(self, entries: List[LogEntry]):
        subs = list(self.subscribers)
        if not subs:
            return
        await asyncio.gather(
            *(asyncio.wait_for(sub.send(entries), SEND_TIMEOUT_SECONDS) for sub in subs),
            return_exceptions=True,
        )

    # ------------------------------------------------------------- queries
    def get_logs(
        self,
        services: Optional[List[str]] = None,
        levels: Optional[List[str]] = None,
        search: Optional[str] = None,
        time_range: Optional[str] = None,
        since_epoch: Optional[float] = None,
        until_epoch: Optional[float] = None,
        limit: int = 1000,
        order: str = "desc",
    ) -> List[LogEntry]:
        if services:
            buffers = [self.buffers[k] for k in set(services) if k in self.buffers]
        else:
            buffers = list(self.buffers.values())
        items = [e for buf in buffers for e in buf]

        if levels:
            wanted_levels = {l.upper() for l in levels}
            items = [e for e in items if e.level in wanted_levels]
        if search:
            needle = search.lower()
            items = [
                e for e in items
                if needle in e.message.lower()
                or needle in e.raw.lower()
                or needle in e.logger.lower()
                or needle in e.service.lower()
            ]

        now = time.time()
        if time_range and time_range in TIME_RANGE_SECONDS:
            cutoff = now - TIME_RANGE_SECONDS[time_range]
            items = [e for e in items if e.ts_epoch >= cutoff]
        elif time_range == "today":
            start_of_day = datetime.datetime.combine(
                datetime.date.today(), datetime.time.min
            ).timestamp()
            items = [e for e in items if e.ts_epoch >= start_of_day]
        elif since_epoch or until_epoch:
            if since_epoch:
                items = [e for e in items if e.ts_epoch >= since_epoch]
            if until_epoch:
                items = [e for e in items if e.ts_epoch <= until_epoch]

        items.sort(key=lambda e: (e.ts_epoch, e.id), reverse=(order == "desc"))
        return items[:limit]

    def matches_filter(
        self, entry: LogEntry, services=None, levels=None, search=None
    ) -> bool:
        if services and entry.service_key not in services:
            return False
        if levels and entry.level not in levels:
            return False
        if search:
            needle = search.lower()
            haystack = f"{entry.message} {entry.raw} {entry.logger} {entry.service}".lower()
            if needle not in haystack:
                return False
        return True


class Subscriber:
    """Wraps a websocket connection plus its current filter settings.
    `services` holds service keys; `levels` is stored upper-cased."""

    def __init__(self, websocket, services=None, levels=None, search=None):
        self.ws = websocket
        self.services = set(services) if services else None
        self.levels = set(l.upper() for l in levels) if levels else None
        self.search = search

    async def send(self, entries: List[LogEntry]):
        matching = [
            e.model_dump()
            for e in entries
            if manager_instance.matches_filter(e, self.services, self.levels, self.search)
        ]
        if matching:
            try:
                await self.ws.send_json({"type": "logs", "entries": matching})
            except Exception:
                pass


manager_instance = LogManager()
