"""
Best-effort, format-agnostic log line parser.

Handles two broad families seen in the wild:
  1. JSON-lines, e.g.
     {"asctime": "2026-07-17 10:12:09,694", "levelname": "INFO", "module": "x",
      "funcName": "y", "process": 8, "message": "..."}
     -> always a single complete record, no buffering needed.

  2. Plain-text logs where a record starts with a timestamp and may span
     multiple physical lines (stack traces, Spring/Tomcat banners, etc).
     Continuation lines (anything not starting with a recognised timestamp)
     are appended to the message/raw of the currently buffered record.

Records are only emitted once we know they're complete - i.e. when the next
start-line arrives, or when flush() is explicitly called (end of stream / a
long quiet period). This keeps stack traces intact instead of splitting them
into one "log entry" per line.
"""
import json
import re
from datetime import datetime
from typing import List, Optional

LEVELS = ("TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL")
LEVEL_RE = re.compile(r"\b(" + "|".join(LEVELS) + r")\b")
LOGGER_RE = re.compile(r"\b((?:[a-zA-Z_][\w]*\.){1,}[A-Za-z_][\w$]*)\b")

# A handful of common timestamp formats found at the start of a log line.
_TZ = r"(?:Z|[+-]\d{2}:?\d{2})?"

TS_PATTERNS = [
    # 2026-07-17 10:12:09,694  |  2026-07-17 10:12:09.694  | with optional 'T' / timezone
    re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[.,]\d{1,6}" + _TZ + ")"),
    # 2026-07-17 10:12:09  (optional timezone)
    re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}" + _TZ + ")"),
    # 17/Jul/2026:10:12:09  (access-log style)
    re.compile(r"^\[?(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2})"),
    # 15-Jul-2026 17:44:29.183  (catalina/tomcat style)
    re.compile(r"^(\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2}:\d{2}\.\d+)"),
]

_DT_TRY_FORMATS = [
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S,%f",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S,%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    # timezone-aware variants (%z accepts "Z", "+0530" and "+05:30")
    "%Y-%m-%d %H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S,%f%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S,%f%z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%d/%b/%Y:%H:%M:%S",
    "%d-%b-%Y %H:%M:%S.%f",
]


def _parse_ts(raw_ts: str, fallback_epoch: float):
    for fmt in _DT_TRY_FORMATS:
        try:
            dt = datetime.strptime(raw_ts, fmt)
            return dt.isoformat(), dt.timestamp()
        except ValueError:
            continue
    # Timezone-aware ISO-8601 (e.g. "...T10:12:09.694Z" or "...+05:30").
    # Naive timestamps above are interpreted as server-local time.
    try:
        dt = datetime.fromisoformat(raw_ts.replace(",", ".").replace("Z", "+00:00"))
        return dt.isoformat(), dt.timestamp()
    except ValueError:
        pass
    return raw_ts, fallback_epoch


def _match_start(line: str):
    for pat in TS_PATTERNS:
        m = pat.match(line)
        if m:
            return m.group(1)
    return None


class RecordBuilder:
    """Accumulates physical lines belonging to a single logical record."""

    def __init__(self, first_line: str, ts_token: Optional[str], file_mtime: float):
        self.lines: List[str] = [first_line]
        self.ts_token = ts_token
        self.file_mtime = file_mtime

    def add(self, line: str):
        self.lines.append(line)

    def build(self) -> dict:
        raw = "\n".join(self.lines).strip("\n")
        first = self.lines[0]

        if self.ts_token:
            timestamp, ts_epoch = _parse_ts(self.ts_token, self.file_mtime)
        else:
            timestamp, ts_epoch = datetime.fromtimestamp(self.file_mtime).isoformat(), self.file_mtime

        level_match = LEVEL_RE.search(raw)
        level = level_match.group(1).upper() if level_match else "INFO"
        if level == "WARNING":
            level = "WARN"

        logger_match = LOGGER_RE.search(raw)
        logger = logger_match.group(1) if logger_match else ""

        # message: everything after the timestamp (and level token) on the
        # remaining lines, collapsed. Good enough for a viewer - full detail
        # is always available via `raw`.
        body_lines = list(self.lines)
        if self.ts_token:
            body_lines[0] = body_lines[0].split(self.ts_token, 1)[-1].lstrip(" -:|")
        message = " ".join(l.strip() for l in body_lines if l.strip())
        if len(message) > 2000:
            message = message[:2000] + " ... (truncated, see raw)"

        return {
            "timestamp": timestamp,
            "ts_epoch": ts_epoch,
            "level": level,
            "logger": logger,
            "message": message,
            "raw": raw,
        }


class StreamParser:
    """Stateful parser bound to a single log file. Feed it raw new bytes as
    they're read from disk; it yields completed structured records.
    A partially-built record is retained across calls until its terminator
    (the next start-line) arrives, so stack traces spanning read boundaries
    stay intact."""

    def __init__(self, file_mtime: float):
        self._pending: Optional[RecordBuilder] = None
        self._leftover = ""  # partial last physical line, no trailing \n yet
        self.file_mtime = file_mtime

    @property
    def has_pending(self) -> bool:
        """True while a record is buffered waiting for its terminator."""
        return self._pending is not None

    def feed(self, chunk: str) -> List[dict]:
        text = self._leftover + chunk
        lines = text.split("\n")
        # last element may be an incomplete line (no trailing newline yet)
        self._leftover = lines.pop()

        out: List[dict] = []
        for line in lines:
            if not line.strip():
                continue

            json_record = self._try_json(line)
            if json_record is not None:
                flushed = self._flush_pending()
                if flushed:
                    out.append(flushed)
                out.append(json_record)
                continue

            ts_token = _match_start(line)
            if ts_token or self._pending is None:
                flushed = self._flush_pending()
                if flushed:
                    out.append(flushed)
                self._pending = RecordBuilder(line, ts_token, self.file_mtime)
            else:
                self._pending.add(line)
        return out

    def flush(self) -> List[dict]:
        """Force-emit any buffered (incomplete) record. Call sparingly -
        e.g. at startup backfill end, or after a period of file inactivity."""
        out = []
        flushed = self._flush_pending()
        if flushed:
            out.append(flushed)
        return out

    def _flush_pending(self) -> Optional[dict]:
        if self._pending is None:
            return None
        rec = self._pending.build()
        self._pending = None
        return rec

    @staticmethod
    def _try_json(line: str) -> Optional[dict]:
        s = line.strip()
        if not (s.startswith("{") and s.endswith("}")):
            return None
        try:
            obj = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(obj, dict):
            return None

        raw_ts = obj.get("asctime") or obj.get("timestamp") or obj.get("time") or ""
        if isinstance(raw_ts, (int, float)) and not isinstance(raw_ts, bool):
            # epoch seconds (or milliseconds, if implausibly large)
            epoch = raw_ts / 1000 if raw_ts > 1e11 else raw_ts
            timestamp, ts_epoch = datetime.fromtimestamp(epoch).isoformat(), float(epoch)
        else:
            timestamp, ts_epoch = (_parse_ts(str(raw_ts), 0) if raw_ts else (None, None))
        if timestamp is None:
            timestamp, ts_epoch = datetime.now().isoformat(), datetime.now().timestamp()

        level = str(obj.get("levelname") or obj.get("level") or "INFO").upper()
        if level == "WARNING":
            level = "WARN"

        logger = str(obj.get("module") or obj.get("logger") or obj.get("logger_name") or "")
        thread = str(obj.get("process") or obj.get("thread") or obj.get("threadName") or "")
        message = str(obj.get("message") or obj.get("msg") or "")

        return {
            "timestamp": timestamp,
            "ts_epoch": ts_epoch,
            "level": level,
            "logger": logger,
            "thread": thread,
            "message": message,
            "raw": s,
        }
