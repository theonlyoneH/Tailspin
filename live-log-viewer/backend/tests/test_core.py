"""
Unit tests for the parser, tailer and manager. Run from backend/:

    pip install -r requirements-dev.txt
    python -m pytest -q
"""
import asyncio
import os
import time

from app import config
from app.manager import LogManager
from app.parser import StreamParser
from app.tailer import FileTailer


def write(path, text, mode="a"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, encoding="utf-8", newline="") as f:
        f.write(text)


# ------------------------------------------------------------------ parser
def test_stack_trace_is_one_record():
    p = StreamParser(time.time())
    out = p.feed(
        "2026-07-17 10:12:09,694 ERROR com.acme.Api - boom\n"
        "java.lang.IllegalStateException: bad\n"
        "    at com.acme.Api.run(Api.java:42)\n"
        "2026-07-17 10:12:10,000 INFO com.acme.Api - next\n"
    )
    assert len(out) == 1
    assert out[0]["level"] == "ERROR"
    assert out[0]["logger"] == "com.acme.Api"
    assert "Api.java:42" in out[0]["raw"]
    assert p.has_pending  # "next" waits for its terminator
    assert p.flush()[0]["message"].endswith("next")


def test_json_line_and_numeric_epoch():
    p = StreamParser(time.time())
    out = p.feed('{"time": 1752746529, "level": "warning", "msg": "hi"}\n')
    assert out[0]["level"] == "WARN"
    assert out[0]["ts_epoch"] == 1752746529
    assert out[0]["message"] == "hi"


def test_timezone_aware_timestamps():
    p = StreamParser(0)
    recs = p.feed("2026-07-17T10:12:09.694Z INFO a\n2026-07-17T15:42:09.694+05:30 INFO b\n") + p.flush()
    assert len(recs) == 2
    # both lines are the same instant in different zones
    assert abs(recs[0]["ts_epoch"] - recs[1]["ts_epoch"]) < 1e-6
    assert recs[0]["message"] == "INFO a"


# ------------------------------------------------------------------ tailer
def test_tailer_reads_only_appended_bytes_and_flushes_when_idle(tmp_path):
    f = str(tmp_path / "svc.log")
    write(f, "2026-07-17 10:00:00 INFO old line\n")
    t = FileTailer(f)
    assert [r["message"] for r in t.seed_from_end(1024)] == ["INFO old line"]

    write(f, "2026-07-17 10:00:01 ERROR newest line\n")
    assert t.read_new() == []          # held back: no next record yet
    assert t.flush_if_idle(60) == []   # not idle long enough
    flushed = t.flush_if_idle(0)
    assert [r["message"] for r in flushed] == ["ERROR newest line"]


def test_tailer_handles_utf8_split_across_writes(tmp_path):
    f = str(tmp_path / "svc.log")
    write(f, "")
    t = FileTailer(f)
    t.seed_from_end(1024)
    data = "2026-07-17 10:00:00 INFO héllo ✓\n".encode("utf-8")
    cut = data.index("✓".encode("utf-8")) + 1  # split inside the 3-byte char
    with open(f, "ab") as fh:
        fh.write(data[:cut])
    t.read_new()
    with open(f, "ab") as fh:
        fh.write(data[cut:])
    t.read_new()
    assert t.flush_if_idle(0)[0]["message"] == "INFO héllo ✓"


def test_tailer_detects_truncation(tmp_path):
    f = str(tmp_path / "svc.log")
    write(f, "2026-07-17 10:00:00 INFO " + "x" * 200 + "\n")
    t = FileTailer(f)
    t.seed_from_end(1024)
    write(f, "2026-07-17 11:00:00 INFO after rotate\n", mode="w")
    t.read_new()
    assert t.flush_if_idle(0)[0]["message"] == "INFO after rotate"


# ----------------------------------------------------------------- manager
def test_same_service_name_in_two_groups_is_kept_separate(tmp_path):
    root = str(tmp_path)
    write(os.path.join(root, "platform", "Api", "a.log"), "2026-07-17 10:00:00 INFO from platform\n")
    write(os.path.join(root, "bots", "Api", "a.log"), "2026-07-17 10:00:00 INFO from bots\n")
    m = LogManager(root)
    asyncio.run(m.initial_scan())

    api = m.discovery.to_api()
    assert api["Platform"] == [{"key": "platform/Api", "name": "Api"}]
    assert api["Bots"] == [{"key": "bots/Api", "name": "Api"}]
    msgs = [e.message for e in m.get_logs(services=["bots/Api"])]
    assert msgs == ["INFO from bots"]


def test_chatty_service_does_not_evict_quiet_one(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_BUFFER_SIZE", 10)
    root = str(tmp_path)
    write(os.path.join(root, "g", "Quiet", "q.log"), "2026-07-17 10:00:00 INFO only line\n")
    write(
        os.path.join(root, "g", "Zchatty", "c.log"),
        "".join(f"2026-07-17 10:00:{i % 60:02d} INFO spam {i}\n" for i in range(100)),
    )
    m = LogManager(root)
    asyncio.run(m.initial_scan())
    assert [e.message for e in m.get_logs(services=["g/Quiet"])] == ["INFO only line"]
    assert len(m.get_logs(services=["g/Zchatty"])) == 10


def test_rescan_picks_up_new_files_and_prunes_deleted(tmp_path):
    root = str(tmp_path)
    old = os.path.join(root, "g", "Svc", "old.log")
    write(old, "2026-07-17 10:00:00 INFO a\n")
    m = LogManager(root)

    async def scenario():
        await m.initial_scan()
        assert os.path.normpath(old) in m.tailers
        os.remove(old)
        new = os.path.join(root, "g", "Svc", "new.log")
        write(new, "2026-07-17 10:00:01 INFO b\n")
        await m._rescan(broadcast=True)
        return new

    new = asyncio.run(scenario())
    assert list(m.tailers) == [os.path.normpath(new)]
    assert "INFO b" in [e.message for e in m.get_logs()]
