"""
Writes realistic demo logs into a Group/Service tree, forever - handy for
trying the viewer without real logs. Stop it with Ctrl+C.

    python demo/demo_logs.py demo/logs
    # then point the backend at it:  LOGVIEWER_ROOT=<full path to>/demo/logs
"""
import json, os, random, sys, time
from datetime import datetime

root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
today = datetime.now().strftime("%Y-%m-%d")
SERVICES = {
    "platform/AdminPanel": ("java", f"Logs/{today}/AdminPanel.0.log"),
    "platform/Api":        ("java", "api.log"),
    "bots/Api":            ("json", "bot.log"),
    "bots/notifier_bot":   ("json", "notifier.log"),
    "queryfic_platform/QueryEngine": ("java", f"logs/{today}/Queryfic.0.log"),
}
MSGS = ["Request handled in {} ms", "User {} logged in", "Cache miss for key session:{}",
        "Processed batch of {} records", "Scheduled job finished ({} items)", "Health check OK ({} ms)"]
WARN = ["Slow query took {} ms", "Retrying upstream call (attempt {})", "Connection pool at {}% capacity"]
ERR = ["Payment failed for order #{}", "Timeout calling inventory service after {} ms", "NullPointerException in handler {}"]

def line(kind, svc):
    lvl = random.choices(["DEBUG", "INFO", "WARN", "ERROR"], [2, 12, 3, 1])[0]
    pool = ERR if lvl == "ERROR" else WARN if lvl == "WARN" else MSGS
    msg = random.choice(pool).format(random.randint(1, 9999))
    now = datetime.now()
    if kind == "json":
        return json.dumps({"asctime": now.strftime("%Y-%m-%d %H:%M:%S,") + f"{now.microsecond//1000:03d}",
                           "levelname": "WARNING" if lvl == "WARN" else lvl,
                           "module": svc.split("/")[-1], "process": random.randint(1, 8), "message": msg}) + "\n"
    cls = "com.acme." + svc.split("/")[-1]
    out = f"{now.strftime('%Y-%m-%d %H:%M:%S,')}{now.microsecond//1000:03d} {lvl} [http-nio-{random.randint(1,9)}] {cls} - {msg}\n"
    if lvl == "ERROR":
        out += (f"java.lang.IllegalStateException: {msg}\n"
                f"    at {cls}.handle({svc.split('/')[-1]}.java:{random.randint(20,300)})\n"
                f"    at org.springframework.web.servlet.DispatcherServlet.doDispatch(DispatcherServlet.java:1072)\n")
    return out

paths = {}
for svc, (kind, rel) in SERVICES.items():
    p = os.path.join(root, *svc.split("/"), *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    paths[svc] = (kind, p)
    with open(p, "a", encoding="utf-8") as f:
        for _ in range(40):
            f.write(line(kind, svc))

print("demo logs in", root, flush=True)
try:
    while True:
        svc = random.choice(list(paths))
        kind, p = paths[svc]
        with open(p, "a", encoding="utf-8") as f:
            f.write(line(kind, svc))
        time.sleep(random.uniform(0.2, 1.2))
except KeyboardInterrupt:
    print("stopped")
