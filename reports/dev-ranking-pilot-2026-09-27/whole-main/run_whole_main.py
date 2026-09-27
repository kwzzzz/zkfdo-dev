"""Run zkFuzz on a whole project entrypoint with timestamps and memory samples."""
import json, os, re, signal, subprocess, sys, threading, time

label, main, library, limit, out_dir = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5]
log_path = os.path.join(out_dir, f"{label}.log")
events = []
start = time.time()
process = subprocess.Popen(["/Users/miiz/.cargo/bin/zkfuzz", main, "-l", library],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)

def reader():
    buffer = b""
    with open(log_path, "w") as log:
        while True:
            chunk = process.stdout.read1(65536) if hasattr(process.stdout, "read1") else process.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk
            parts = re.split(rb"[\r\n]", buffer)
            buffer = parts.pop()
            for part in parts:
                text = re.sub(r"\x1b\[[0-9;]*m", "", part.decode(errors="replace")).strip()
                if text:
                    stamp = time.time() - start
                    events.append((stamp, text))
                    log.write(f"{stamp:9.2f} {text}\n")

thread = threading.Thread(target=reader, daemon=True)
thread.start()
max_rss_kb = 0
status = "finished"
while process.poll() is None:
    if time.time() - start > limit:
        os.killpg(process.pid, signal.SIGKILL)
        status = "killed-at-limit"
        break
    try:
        rss = subprocess.run(["ps", "-o", "rss=", "-g", str(process.pid)], capture_output=True, text=True).stdout
        max_rss_kb = max(max_rss_kb, sum(int(x) for x in rss.split() if x.isdigit()))
    except Exception:
        pass
    time.sleep(2)
process.wait()
thread.join(timeout=10)
generations = [(t, int(m.group(1))) for t, e in events for m in [re.search(r"Generation:\s*(\d+)/", e)] if m]
markers = {}
for t, e in events:
    for key in ("Loading", "Parsing Templates", "Parsing Function", "Gathering", "Mutation Settings",
                "Generation:", "Verification", "NOT SAFE", "No Counter Example", "panicked", "rror"):
        if key in e and key not in markers:
            markers[key] = round(t, 2)
summary = {"label": label, "status": status, "exit_code": process.returncode,
           "elapsed_seconds": round(time.time() - start, 1), "max_rss_mb": round(max_rss_kb / 1024),
           "first_marker_seconds": markers,
           "first_generation": generations[0] if generations else None,
           "last_generation": generations[-1] if generations else None,
           "verification": [e for _, e in events if "Verification" in e][-1:]}
json.dump(summary, open(os.path.join(out_dir, f"{label}.summary.json"), "w"), indent=1)
print(json.dumps(summary))
