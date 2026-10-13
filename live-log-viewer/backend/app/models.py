import itertools
from pydantic import BaseModel

_id_counter = itertools.count(1)


class LogEntry(BaseModel):
    id: int
    timestamp: str          # ISO-ish string, best-effort parsed from the log line
    ts_epoch: float          # epoch seconds, used for fast time-range filtering/sorting
    group: str
    service: str            # display name (not unique across groups)
    service_key: str        # stable unique id, e.g. "platform/AdminPanel" - used for filtering
    level: str
    logger: str = ""
    thread: str = ""
    message: str = ""
    raw: str = ""
    file: str = ""            # file the entry came from (relative, for debugging)

    @staticmethod
    def next_id() -> int:
        return next(_id_counter)
