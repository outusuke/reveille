#: layer 05: what a timer's schedule means: calendar, intervals, rewrite of a hand-written timer
# ---------------------------------------------------------------- schedules
def on_calendar(tr):
    h, m = int(tr.get("hour", 0)), int(tr.get("minute", 0))
    t = tr["type"]
    if t == "daily":
        return f"*-*-* {h:02d}:{m:02d}:00"
    if t == "weekdays":
        return f"{','.join(WEEKDAYS)} *-*-* {h:02d}:{m:02d}:00"
    if t == "weekly":
        days = ",".join(d for d in DAYS if d in tr.get("days", []))
        return f"{days} *-*-* {h:02d}:{m:02d}:00"
    if t == "monthly":
        return f"*-*-{int(tr.get('dom', 1)):02d} {h:02d}:{m:02d}:00"
    if t == "lastday":
        return f"*-*~01 {h:02d}:{m:02d}:00"
    if t == "times":                                    # one OnCalendar= line each, so the minutes can differ
        return " | ".join(f"*-*-* {x}:00" for x in tr.get("times") or []) or None
    if t == "custom":
        return tr.get("expr", "").strip() or None
    return None

def describe(tr):
    t, hm = tr["type"], f"{int(tr.get('hour', 0)):02d}:{int(tr.get('minute', 0)):02d}"
    if t == "daily": return f"Every day at {hm}"
    if t == "weekdays": return f"Weekdays at {hm}"
    if t == "weekly":
        days = [d for d in DAYS if d in tr.get("days", [])]
        who = ("Every day" if len(days) == 7 else "Weekdays" if days == WEEKDAYS else
               "Weekends" if days == DAYS[5:] else ", ".join(days))
        return f"{who} at {hm}"
    if t == "monthly": return f"On the {ordinal(int(tr.get('dom', 1)))} of every month at {hm}"
    if t == "lastday": return f"Last day of every month at {hm}"
    if t == "times": return "Every day at " + ", ".join(tr.get("times") or [hm])
    if t == "custom": return tr.get("expr", "custom schedule")
    if t == "interval":
        one, many = EVERY_NAMES.get(tr.get("unit"), EVERY_NAMES["min"]); n = int(tr.get("every", 1))
        text = f"Every {one}" if n == 1 else f"Every {n} {many}"
        first = tr.get("first_sec")
        return text if first is None or first == interval_seconds(tr) else f"{text}, first run {human_span(first)} after login"
    sec = int(tr.get("login_sec", 10))
    return "At login" if sec in (0, 10) else f"At login, after {human_span(sec)}"

def calendar_parts(expr):
    """A custom schedule may hold several calendar expressions separated by | (one OnCalendar= line each)."""
    return [p.strip() for p in expr.split("|") if p.strip()]

def next_elapse(tr):
    """Text for the live preview in the editor."""
    cal = on_calendar(tr)
    if cal:
        res = []
        for part in calendar_parts(cal):
            try:
                out = subprocess.run(["systemd-analyze", "calendar", part], capture_output=True, text=True, timeout=5).stdout
            except (OSError, subprocess.TimeoutExpired):
                return "Preview unavailable"
            nxt = re.search(r"Next elapse:\s*(.+)", out)
            left = re.search(r"From now:\s*(.+)", out)
            if not nxt: return "Not a valid schedule"
            res.append(nxt.group(1).strip() + (f"  ({left.group(1).strip()})" if left else ""))
        return "\n".join(res) if res else "Not a valid schedule"
    if tr["type"] == "interval":
        first = tr.get("first_sec")
        every = interval_seconds(tr)
        return f"First run {human_span(every if first is None else first)} after login, then every {human_span(every)}"
    sec = int(tr.get("login_sec", 10))
    return "Shortly after you log in" if sec <= 60 else f"{human_span(sec)} after you log in"

def needs_precision(secs):
    """systemd lets a timer fire up to a minute late (AccuracySec=1min) so wake-ups can be shared. An interval
    that isn't a whole number of minutes would be off by a large share of its length."""
    return secs < 60 or secs % 60 != 0

def timer_lines(tr, catchup, delay):
    """The schedule lines of a timer. Raises ValueError if the schedule is empty, so nothing is half-written."""
    out, cal = [], on_calendar(tr)
    if tr["type"] in CALENDAR_TYPES:
        if not cal: raise ValueError("The schedule is empty")
        out += [f"OnCalendar={p}" for p in calendar_parts(cal)]
        if catchup: out.append("Persistent=true")
    elif tr["type"] == "interval":
        secs = interval_seconds(tr)
        if secs < 1: raise ValueError("The interval must be at least one second")
        first = tr.get("first_sec")
        if first is not None and first < 0: raise ValueError("The first run can't be negative")
        key = tr.get("first_key") or "OnStartupSec"      # keep the key a hand-written timer used (OnBootSec= counts from boot)
        out += [f"{key}={fmt_span(secs if first is None else first)}", f"OnUnitActiveSec={fmt_span(secs)}"]
        if needs_precision(secs): out.append("AccuracySec=1s")
    else:
        out.append(f"OnStartupSec={fmt_span(int(tr.get('login_sec', 10)))}")
    if delay: out.append(f"RandomizedDelaySec={int(delay)}")
    return out

def timer_keep(tr):
    """keep(key, value) for the [Timer] section: AccuracySec= is the user's own, except for an interval that
    needs the precise one, where the editor writes it itself."""
    precise = tr["type"] == "interval" and needs_precision(interval_seconds(tr))
    return lambda k, v: k == "AccuracySec" and not precise

DAY_RE = "|".join(DAYS)

def parse_days(spec):
    """"Mon,Wed" or "Mon..Fri,Sun" as a list of days in week order, or None if it isn't that."""
    days = set()
    for part in spec.split(","):
        m = re.fullmatch(rf"({DAY_RE})(?:\.\.({DAY_RE}))?", part)
        if not m: return None
        a = DAYS.index(m[1]); b = DAYS.index(m[2]) if m[2] else a
        if b < a: return None
        days.update(DAYS[a:b + 1])
    return [d for d in DAYS if d in days]

def times_of(tr):
    """The clock times of a daily or several-times trigger as ["HH:MM", ...], else None."""
    if tr["type"] == "daily": return [f"{tr['hour']:02d}:{tr['minute']:02d}"]
    if tr["type"] == "times": return tr["times"]
    return None

def from_calendar(expr):
    e = expr.strip()
    if e == "daily": return {"type": "daily", "hour": 0, "minute": 0}
    date, clock = r"(?:\*-\*-\* )?", r"(\d\d?(?:,\d\d?)*):(\d\d)(?::00)?"
    def at(hours, minute):                              # "8,12", "30" -> ([8, 12], 30), or None if out of range
        hs = sorted({int(x) for x in hours.split(",")})
        return (hs, int(minute)) if hs[-1] < 24 and int(minute) < 60 else None
    m = re.fullmatch(rf"{date}{clock}", e)
    t = at(m[1], m[2]) if m else None
    if t:
        (hs, mi) = t
        if len(hs) == 1: return {"type": "daily", "hour": hs[0], "minute": mi}
        return {"type": "times", "times": [f"{h:02d}:{mi:02d}" for h in hs]}
    m = re.fullmatch(rf"([A-Za-z.,]+) {date}{clock}", e)
    days, t = (parse_days(m[1]), at(m[2], m[3])) if m else (None, None)
    if days and t and len(t[0]) == 1:
        return {"type": "weekdays" if days == WEEKDAYS else "weekly", "days": days, "hour": t[0][0], "minute": t[1]}
    m = re.fullmatch(rf"\*-\*-(\d\d?) {clock}", e)
    t = at(m[2], m[3]) if m else None
    if t and len(t[0]) == 1 and 1 <= int(m[1]) <= 28:
        return {"type": "monthly", "dom": int(m[1]), "hour": t[0][0], "minute": t[1]}
    m = re.fullmatch(rf"\*-\*~0?1 {clock}", e)
    t = at(m[1], m[2]) if m else None
    if t and len(t[0]) == 1: return {"type": "lastday", "hour": t[0][0], "minute": t[1]}
    return {"type": "custom", "expr": e}

def parse_schedule(kv):
    """Read the [Timer] keys as (trigger, catchup, delay), or None if they use something the editor would lose."""
    if any(k in kv for k in ("OnActiveSec", "OnUnitInactiveSec")): return None
    catchup = kv.get("Persistent", ["false"])[-1].lower() in ("true", "yes", "1", "on")
    delay = 0
    if "RandomizedDelaySec" in kv:
        delay = parse_span(kv["RandomizedDelaySec"][-1])
        if delay is None: return None
    cals, start = kv.get("OnCalendar", []), kv.get("OnStartupSec", []) + kv.get("OnBootSec", [])
    active = kv.get("OnUnitActiveSec", [])
    if len(cals) == 1 and not start and not active:
        tr = from_calendar(cals[0])
    elif len(cals) > 1 and not start and not active:
        parts = [from_calendar(c) for c in cals]
        lists = [times_of(p) for p in parts]
        if all(lists):                                  # several clock times: one OnCalendar= line each
            ts = sorted({x for l in lists for x in l})
            tr = ({"type": "times", "times": ts} if len(ts) > 1 else
                  {"type": "daily", "hour": int(ts[0][:2]), "minute": int(ts[0][3:])})
        else:
            tr = {"type": "custom", "expr": " | ".join(cals)}
    elif not cals and len(active) == 1 and len(start) <= 1:
        total = exact_span(active[0])
        if not total: return None
        step = split_interval(total)
        if not step: return None
        tr = {"type": "interval", "every": step[0], "unit": step[1]}
        if start:                                       # a first run that differs from the interval is shown, not refused
            first = exact_span(start[0])
            if first is None: return None
            if first != total: tr["first_sec"] = first
            if "OnBootSec" in kv: tr["first_key"] = "OnBootSec"
    elif not cals and not active and len(start) == 1:
        sec = exact_span(start[0])
        if sec is None: return None
        tr = {"type": "login", "login_sec": sec}
    else:
        return None
    return {**DEFAULT_TR, **tr}, catchup, delay

def rewrite_timer(unit, tr, catchup, delay):
    """Replace only the schedule lines of a hand-written timer; everything else in the file is kept."""
    path = unit_path(unit)
    lines = timer_lines(tr, catchup, delay)             # before anything is written: it can refuse
    try:
        with open(path) as f: text = f.read()
        if not os.path.exists(path + ".reveille-bak"):          # one-time backup of the original
            write_atomic(path + ".reveille-bak", text)
        write_atomic(path, merge_unit(text, {"Timer": (TIMER_KEYS, lines, timer_keep(tr))}))
    except OSError as e:
        return e.strerror or str(e)
    ctl("daemon-reload")
    if unit_status(unit)[1]: ctl("restart", unit)
    return None


