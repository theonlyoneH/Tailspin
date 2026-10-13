"""
Tails a single file, tail -f style: never re-reads bytes it has already
processed, and copes with log rotation (file truncated in place, or
replaced/recreated with the same name).

The file is read in binary mode so `_offset` is a true byte offset that can
be compared against `st_size`; bytes are decoded with an incremental UTF-8
decoder so a multi-byte character split across two writes is not mangled.
"""
import codecs
import os
import time
from .parser import StreamParser


def _new_decoder():
    return codecs.getincrementaldecoder("utf-8")(errors="replace")


class FileTailer:
    def __init__(self, path: str):
        self.path = path
        self._offset = 0
        self._inode = None
        self._decoder = _new_decoder()
        self._last_data = time.monotonic()
        self.parser: StreamParser = None  # created lazily once we know mtime

    def _stat(self):
        try:
            st = os.stat(self.path)
            return st.st_size, st.st_ino, st.st_mtime
        except OSError:
            return None, None, None

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def seed_from_end(self, backfill_bytes: int):
        """Startup / newly-discovered-file behaviour: don't read the whole
        (possibly huge) file - just grab the last `backfill_bytes` so the
        viewer has *some* recent history, then position the offset at EOF
        so subsequent reads are pure tail -f appends."""
        size, inode, mtime = self._stat()
        if size is None:
            return []
        self._inode = inode
        self.parser = StreamParser(mtime)
        self._decoder = _new_decoder()

        start = max(0, size - backfill_bytes)
        records = []
        try:
            with open(self.path, "rb") as f:
                f.seek(start)
                if start > 0:
                    # we very likely landed mid-line; discard the partial
                    # fragment so the first parsed record starts cleanly.
                    f.readline()
                data = f.read()
                self._offset = f.tell()
            records = self.parser.feed(self._decoder.decode(data))
            records += self.parser.flush()
        except OSError:
            pass
        return records

    def read_new(self):
        """Read whatever has been appended since the last call. Returns a
        list of newly completed structured records (possibly empty)."""
        size, inode, mtime = self._stat()
        if size is None:
            return []

        if self.parser is None:
            self.parser = StreamParser(mtime)

        rotated = (inode is not None and self._inode is not None and inode != self._inode) or (
            size < self._offset
        )
        if rotated:
            self._offset = 0
            self.parser = StreamParser(mtime)
            self._decoder = _new_decoder()
        self._inode = inode

        if size <= self._offset:
            return []

        records = []
        try:
            with open(self.path, "rb") as f:
                f.seek(self._offset)
                data = f.read()
                self._offset = f.tell()
            if data:
                self._last_data = time.monotonic()
                self.parser.file_mtime = mtime
                records = self.parser.feed(self._decoder.decode(data))
        except OSError:
            pass
        return records

    @property
    def has_pending(self) -> bool:
        return self.parser is not None and self.parser.has_pending

    def flush_if_idle(self, idle_seconds: float):
        """Plain-text records are only emitted when the *next* record starts,
        so the newest line of a file would otherwise stay invisible until the
        service logs again. Once the file has been quiet for `idle_seconds`,
        assume the buffered record is complete and emit it."""
        if not self.has_pending or time.monotonic() - self._last_data < idle_seconds:
            return []
        return self.parser.flush()
