import os

try:
    from dotenv import load_dotenv
    # Loads backend/.env if present. Explicit `export`s in the shell still win.
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except ImportError:
    pass

# Root directory containing the "Group / Service / *.log" hierarchy.
# Override with:  LOGVIEWER_ROOT=/path/to/logs uvicorn app.main:app
LOG_ROOT = os.environ.get("LOGVIEWER_ROOT", os.path.join(os.getcwd(), "logs"))

# File extensions considered "log files" during discovery.
LOG_EXTENSIONS = {".log", ".txt"}

# Directory names (case-insensitive) that mark a "logs container" for rule #2
# discovery (see discovery.py) e.g. Service/Logs/2026-07-17/Service.0.log
LOG_DIR_NAMES = {"log", "logs"}

# How many entries to keep in memory *per service*. Each service gets its own
# ring buffer so one chatty service can't evict every other service's history.
# No database, no disk persistence.
MAX_BUFFER_SIZE = int(os.environ.get("LOGVIEWER_MAX_BUFFER", "5000"))

# Plain-text records are emitted when the next record starts. If a file goes
# quiet for this many seconds, the last buffered record is emitted anyway.
FLUSH_IDLE_SECONDS = float(os.environ.get("LOGVIEWER_FLUSH_IDLE_SECONDS", "1.0"))

# On startup / when a brand-new file is discovered, how many trailing bytes
# to read to seed the buffer (keeps startup cheap - we never read a whole
# multi-GB log file).
BACKFILL_BYTES = int(os.environ.get("LOGVIEWER_BACKFILL_BYTES", str(256 * 1024)))

# Max directory depth to search (per group) when looking for service roots.
MAX_DISCOVERY_DEPTH = int(os.environ.get("LOGVIEWER_MAX_DEPTH", "6"))

# CORS origins allowed to hit the API (Vite dev server default).
CORS_ORIGINS = os.environ.get(
    "LOGVIEWER_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")
