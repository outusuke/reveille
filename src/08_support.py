#: layer 08: calendar check, picker list, process runner, linger, journal, row text, gather
def bad_calendar(expr):
    """True if `expr` (one or several calendar expressions separated by |) is empty or rejected by
    systemd-analyze. If systemd-analyze is missing or too slow nothing can be checked, so it is not rejected."""
    parts = calendar_parts(expr)
    if not parts: return True
    for p in parts:
        r = sh("systemd-analyze", "calendar", p, timeout=5)
        if r is not None and r.returncode: return True
    return False

def pick_list(items, current):
    """(items, index) for a picker. A current value the list doesn't offer (an uninstalled app, a hidden
    service) is added at the top and selected, so saving without touching it can't silently switch it."""
    items = list(items)
    if current and current in items: return items, items.index(current)
    if current: items.insert(0, current); return items, 0
    return items, 0


def sh(*cmd, timeout=10):
    """Run a program; None if it is missing or too slow."""
    try: return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired): return None

def linger_state():
    """Whether systemd keeps this user's session (and so its timers) running while logged out:
    True, False, or None if it can't be told."""
    r = sh("loginctl", "show-user", str(os.getuid()), "-p", "Linger")
    m = re.search(r"^Linger=(\w+)", r.stdout, re.M) if r and r.returncode == 0 else None
    return m[1] == "yes" if m else None

def set_linger(on):
    """Turn lingering on or off for the current user. Returns an error text or None."""
    r = sh("loginctl", "enable-linger" if on else "disable-linger", timeout=30)
    if r is None: return "loginctl is not available"
    return (r.stderr.strip() or "loginctl failed") if r.returncode else None

LOG_HINT = ("No log entries for this service yet.\n\nIf it has run before, your system may not keep a per-user "
            "journal. Try: journalctl --user -u {unit}")

def read_log(service, lines=200):
    """The last lines of a service's journal: (text, None), or ("", error text)."""
    r = sh("journalctl", "--user", f"--unit={service}", "-n", str(int(lines)), "--no-pager", "-o", "short-iso",
           timeout=15)
    if r is None: return "", "journalctl is not available or took too long"
    if r.returncode: return "", r.stderr.strip() or "journalctl failed"
    text = r.stdout.strip()
    return (text, None) if text and not text.startswith("-- No entries") else (LOG_HINT.format(unit=service), None)

_CACHE = {}

def systemd_version():
    """The running systemd's major version (255, say), or None if it can't be told. Asked once."""
    if "v" not in _CACHE:
        r = sh("systemctl", "--version", timeout=5)
        m = re.match(r"systemd (\d+)", r.stdout) if r and r.returncode == 0 else None
        _CACHE["v"] = int(m[1]) if m else None
    return _CACHE["v"]

class FollowLog:
    """`journalctl -f` for a service. Lines are read in a thread and handed to on_line(text), which therefore
    runs off the main thread. start() returns an error text or None; stop() ends the follow."""
    def __init__(self, service, on_line, lines=200):
        self.service, self.on_line, self.lines = service, on_line, lines
        self.proc, self.stopped = None, False

    def start(self):
        try:
            self.proc = subprocess.Popen(
                ["journalctl", "--user", f"--unit={self.service}", "-n", str(int(self.lines)), "-f", "--no-pager",
                 "-o", "short-iso"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError:
            return "journalctl is not available"
        threading.Thread(target=self._read, daemon=True).start()
        return None

    def _read(self):
        proc = self.proc
        for line in proc.stdout:
            if self.stopped: break
            line = line.rstrip("\n")
            if not line.startswith("-- "): self.on_line(line)          # "-- No entries --" and friends
        proc.stdout.close(); proc.wait()

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None: self.proc.terminate()

def task_texts(m):
    """(subtitle, tooltip) of a task row, from what gather() collected."""
    lines = [describe(m["trigger"]) if m["trigger"] else "Custom schedule"]
    if m["enabled"]:
        lines.append("Next: " + (m["next_text"] or "when triggered"))
        if m["fstate"] and m["fstate"] not in BOOT_OK: lines.append("Not enabled: won't start again after a restart")
    else:
        lines.append("Stopped, starts again at next login" if m["fstate"] in BOOT_OK else "Disabled")
    last, status = m["last"], []
    if m.get("retrying"): status.append("Waiting to retry")
    elif m["running"]: status.append("Running now")
    if last: status.append(f"Last: {m['last_text']} " + ("OK" if last["rc"] == 0 else f"failed ({last['rc']})"))
    if status: lines.append(" · ".join(status))
    tip = [f"Next: {m['next']}" if m["enabled"] and m["next"] else "", f"Last: {last['time']}" if last else ""]
    return "\n".join(lines), "\n".join(x for x in tip if x)

def gather():
    """Everything the window lists, fetched with two systemctl calls however many tasks there are.
    The service list for the editor's pickers is not part of it (list_services is the costly one): the window
    fetches it when an editor opens. No GTK in here, so it can run off the main thread."""
    timers = user_timers()
    st = show_many(timers, "ActiveState", "UnitFileState", "NextElapseUSecRealtime", "NextElapseUSecMonotonic")
    tasks = [m for m in (load_task(t, st) for t in timers) if m]
    sv = show_many(sorted({m["service"] for m in tasks}), "ActiveState", "SubState", "Result", "ExecMainStatus",
                   "ExecMainExitTimestamp")
    now, mono = time.time(), time.monotonic()
    for m in tasks:
        kv, svc = st.get(m["timer"], {}), sv.get(m["service"], {})
        m["next"] = kv.get("NextElapseUSecRealtime", "").strip()
        ep = next_run_epoch(kv, now, mono)
        m["next_text"] = ("any moment" if ep <= now else relative(ep, now)) if ep else ""
        m["last"] = last_run_from(svc)
        lt = parse_ts(m["last"]["time"]) if m["last"] else None
        m["last_text"] = relative(lt, now) if lt else (m["last"] or {}).get("time", "")
        m["retrying"] = svc.get("SubState") == "auto-restart"          # failed, waiting for the next try
        m["running"] = svc.get("ActiveState") in ("activating", "active") and not m["retrying"]
    tasks.sort(key=lambda m: m["name"].lower())
    return {"tasks": tasks, "free": unscheduled_services(timers), "linger": linger_state(),
            "systemd": systemd_version()}


