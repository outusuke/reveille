#: layer 03: time spans and timestamps: parsing and wording, no I/O
SPAN_UNITS = {"us": 1e-6, "usec": 1e-6, "ms": 1e-3, "msec": 1e-3, "": 1, "s": 1, "sec": 1, "second": 1, "seconds": 1,
              "m": 60, "min": 60, "minute": 60, "minutes": 60, "h": 3600, "hr": 3600, "hour": 3600, "hours": 3600,
              "d": 86400, "day": 86400, "days": 86400, "w": 604800, "week": 604800, "weeks": 604800}

def parse_span(text):
    """A systemd time span (\"90\", \"5min\", \"1h 30min\") as whole seconds, or None if it isn't one."""
    text = text.strip()
    if not re.fullmatch(r"(?:\d+\s*[a-z]*\s*)+", text): return None
    total = 0
    for n, u in re.findall(r"(\d+)\s*([a-z]*)", text):
        if u not in SPAN_UNITS: return None
        total += int(n) * SPAN_UNITS[u]
    return int(total)

def parse_span_f(text):
    """Like parse_span, for the fractional spans systemctl prints ("1h 2min 3.5s"): seconds as a float, or None."""
    text = text.strip()
    if not re.fullmatch(r"(?:\d+(?:\.\d+)?\s*[a-z]*\s*)+", text): return None
    total = 0.0
    for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*([a-z]*)", text):
        if u not in SPAN_UNITS: return None
        total += float(n) * SPAN_UNITS[u]
    return total

def exact_span(text):
    """A time span as whole seconds, or None if it isn't one or has a fraction of a second (parse_span would
    quietly round that down, and a saved schedule must mean what was written)."""
    f = parse_span_f(text)
    return int(f) if f is not None and f == int(f) else None

def fmt_span(secs):
    """Whole seconds as the shortest exact systemd span: 7200 -> "2h", 5400 -> "90min", 45 -> "45s"."""
    if secs == 0: return "0"
    for suffix, size in (("d", 86400), ("h", 3600), ("min", 60)):
        if secs % size == 0: return f"{secs // size}{suffix}"
    return f"{secs}s"

def split_interval(secs):
    """(n, unit) with the largest unit that divides `secs` evenly, or None if that doesn't fit the editor."""
    for unit in ("d", "h", "min", "s"):
        if secs % INTERVAL_UNITS[unit] == 0:
            n = secs // INTERVAL_UNITS[unit]
            return (n, unit) if 1 <= n <= MAX_EVERY else None
    return None

def interval_seconds(tr):
    return int(tr.get("every", 1)) * INTERVAL_UNITS.get(tr.get("unit"), 60)

def human_span(secs):
    """"90 s", "5 min", "2 h", "3 days" """
    n, unit = split_interval(secs) or (secs, "s")
    return f"{n} " + ({"s": "s", "min": "min", "h": "h"}.get(unit) or ("day" if n == 1 else "days"))

def ordinal(n):
    return f"{n}" + ("th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))

def parse_times(text):
    """"8:00, 12:30 18:00" -> ["08:00", "12:30", "18:00"] (sorted, no repeats), or None if it is empty or
    anything in it isn't a clock time."""
    out = set()
    for p in (x for x in re.split(r"[,;|\s]+", text.strip()) if x):
        m = re.fullmatch(r"(\d{1,2}):(\d\d)", p)
        if not m or int(m[1]) > 23 or int(m[2]) > 59: return None
        out.add(f"{int(m[1]):02d}:{m[2]}")
    return sorted(out) or None

def parse_ts(text):
    """A timestamp as systemctl prints it ("Tue 2026-11-10 03:00:00 -03", local time) as epoch seconds, or None."""
    m = re.search(r"(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)", text or "")
    return time.mktime((*map(int, m.groups()), 0, 0, -1)) if m else None

def next_run_epoch(kv, now=None, mono=None):
    """When a timer fires next, from its properties. Calendar timers carry a wall-clock time; interval and login
    timers only a monotonic one, which is turned into wall-clock time with the same clock Python uses."""
    t = parse_ts(kv.get("NextElapseUSecRealtime", ""))
    if t: return t
    span = parse_span_f(kv.get("NextElapseUSecMonotonic", ""))
    if not span: return None                    # 0, "infinity" or unreadable: nothing is scheduled
    now = time.time() if now is None else now
    mono = time.monotonic() if mono is None else mono
    return now + (span - mono)

def relative(epoch, now=None):
    """A moment as people say it: "in 12 min", "tomorrow 03:00", "yesterday 03:00", "3 days ago"."""
    now = time.time() if now is None else now
    d = epoch - now; a = abs(d); fut = d > 0
    if a < 60: return "in less than a minute" if fut else "just now"
    if a < 3600: n = round(a / 60); return f"in {n} min" if fut else f"{n} min ago"
    days = (datetime.date.fromtimestamp(epoch) - datetime.date.fromtimestamp(now)).days
    clock = time.strftime("%H:%M", time.localtime(epoch))
    if days == 0 and a < 6 * 3600:
        h, m = divmod(round(a / 60), 60); span = f"{h} h" + (f" {m} min" if m else "")
        return f"in {span}" if fut else f"{span} ago"
    if days == 0: return f"today {clock}"
    if days == 1: return f"tomorrow {clock}"
    if days == -1: return f"yesterday {clock}"
    if -7 < days < 0: return f"{-days} days ago"
    return time.strftime("%a %d %b %H:%M", time.localtime(epoch))

