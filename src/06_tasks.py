#: layer 06: reading tasks back from unit files: ExecStart, service settings, drop-ins, listing
# ---------------------------------------------------------------- tasks, read from the units themselves
def build_exec(t):
    """The ExecStart= value for an app or command task. Raises ValueError with a readable reason."""
    if t["kind"] == "app":
        from gi.repository import Gio
        info = Gio.DesktopAppInfo.new(t["app"])
        path = info.get_filename() if info else None
        if not path: raise ValueError(f"{t['app']} is not installed")
        gio, gtk = shutil.which("gio"), shutil.which("gtk-launch")
        if gio: tokens = [gio, "launch", path]
        elif gtk: tokens = [gtk, t["app"]]
        else: raise ValueError("Neither gio nor gtk-launch was found")
    else:
        tokens = shlex.split(t["command"])
        if not tokens: raise ValueError("Enter a valid command")
        if not os.path.isabs(tokens[0]):
            found = shutil.which(tokens[0])
            if not found: raise ValueError(f"{tokens[0]} was not found in PATH")
            tokens[0] = found
    return " ".join(xesc(shlex.quote(x)) for x in tokens)

def parse_service(name):
    """Read the settings the editor manages from a service file. Every other line is left alone when saving.
    Returns {"why": reason} if a managed setting is in a form the editor can't represent."""
    u = read_unit(unit_path(name))
    if u is None: return {"why": "the service file can't be read"}
    un, sv = u.get("Unit", {}), u.get("Service", {})
    if len(sv.get("ExecStart", [])) != 1: return {"why": "the service doesn't have exactly one ExecStart= line"}
    cmd = xunesc(sv["ExecStart"][0])
    if not cmd or cmd[0] in "-@:+!|": return {"why": "ExecStart= starts with a special prefix (- @ + ! :)"}
    try: tokens = shlex.split(cmd)
    except ValueError: return {"why": "ExecStart= can't be split into words"}
    deps = [x for v in un.get("Wants", []) + un.get("After", []) for x in v.split()]
    timeout = 0
    if "TimeoutStartSec" in sv:
        m = re.fullmatch(r"(\d+)min", sv["TimeoutStartSec"][-1])
        if not m: return {"why": "TimeoutStartSec= isn't a whole number of minutes"}
        timeout = int(m[1])
    env = []
    for v in sv.get("Environment", []):
        try: env += [unesc(x) for x in shlex.split(v)]
        except ValueError: return {"why": "Environment= has an unclosed quote"}
    retries, wait = 0, 5
    mode = sv.get("Restart", ["no"])[-1]
    if mode not in ("no", "on-failure"): return {"why": "Restart= is something other than on-failure"}
    if mode == "on-failure":
        burst = (un.get("StartLimitBurst") or [""])[-1]
        if not re.fullmatch(r"\d+", burst) or not 2 <= int(burst) <= 11:
            return {"why": "Restart=on-failure has no StartLimitBurst= between 2 and 11"}
        retries = int(burst) - 1
        m = re.fullmatch(r"([1-9]\d*)min", (sv.get("RestartSec") or [""])[-1])
        if not m or int(m[1]) > 1440: return {"why": "RestartSec= isn't a whole number of minutes (1 to 1440)"}
        wait = int(m[1])
    paths = un.get("ConditionPathExists", [])
    if len(paths) > 1: return {"why": "there are several ConditionPathExists= lines"}
    then = [x for v in un.get("OnSuccess", []) for x in v.split()]
    if len(then) > 1: return {"why": "OnSuccess= lists more than one unit"}
    fail = [x for v in un.get("OnFailure", []) for x in v.split()]
    if len(fail) > 1: return {"why": "OnFailure= lists more than one unit"}
    adv = {"cwd": unesc(sv.get("WorkingDirectory", [""])[-1]), "env": " ".join(shlex.quote(x) for x in env),
           "timeout": timeout, "ac": "true" in un.get("ConditionACPower", []), "online": ONLINE in deps,
           "retries": retries, "retry_wait": wait,
           "low": sv.get("Nice") == ["19"] and sv.get("IOSchedulingClass") == ["idle"],
           "path": unesc(paths[0]) if paths else "", "then": then[0] if then else "",
           "fail": fail[0] if fail else ""}
    s = {"adv": adv, "kind": "command", "command": cmd}
    if len(tokens) == 3 and os.path.basename(tokens[0]) == "gio" and tokens[1] == "launch":
        s.update(kind="app", app=os.path.basename(tokens[2]))
    elif len(tokens) == 2 and os.path.basename(tokens[0]) == "gtk-launch":
        s.update(kind="app", app=tokens[1] if tokens[1].endswith(".desktop") else tokens[1] + ".desktop")
    return s

def retry_window(retries, wait_min, timeout_min=0):
    """Seconds of systemd's start-limit window for a task that retries `retries` times. It has to be long enough
    to hold every try, or the count is never reached and a failing task would retry forever. How long a run takes
    is only known when there is a timeout, so one hour is assumed otherwise."""
    return (retries + 1) * (wait_min + (timeout_min or 60)) * 60 + 60

def then_cycle(service, then):
    """True if starting `then` after `service` succeeds (OnSuccess=) or fails (OnFailure=) would lead back to
    `service` through such links. Either kind of link can close the loop, so both are followed."""
    seen, todo = set(), [then]
    while todo:
        cur = todo.pop()
        if cur == service: return True
        if cur in seen or not cur: continue
        seen.add(cur)
        u = read_unit(unit_path(cur)) or {}
        todo += [x for k in ("OnSuccess", "OnFailure") for v in u.get("Unit", {}).get(k, []) for x in v.split()]
    return False

def dropin_info(unit, watched):
    """The drop-in files of `unit` ("NAME.service.d/x.conf", from the user unit folder) and, if one of them sets a key
    in `watched` ({section: keys}), a reason saying which; "" if none does. Such a key is one the editor shows,
    so what it shows would no longer be what systemd runs."""
    folder = f"{UNITS}/{unit}.d"
    try: names = sorted(n for n in os.listdir(folder) if n.endswith(".conf") and os.path.isfile(f"{folder}/{n}"))
    except OSError: return [], ""
    why = []
    for n in names:
        u = read_unit(f"{folder}/{n}") or {}
        hit = []
        for sect, keys in watched.items():
            for k, vals in u.get(sect, {}).items():
                if k not in keys: continue
                if k in ("Wants", "After") and not any(ONLINE in v.split() for v in vals): continue   # only the network one is ours
                hit.append(f"{k}=")
        if hit: why.append(f"the drop-in {unit}.d/{n} also sets {', '.join(sorted(hit))}")
    return [f"{unit}.d/{n}" for n in names], "; ".join(why)

def load_task(timer, status=None):
    """Build a task from a timer file (and the service it starts). "full" means the editor can rewrite it."""
    u = read_unit(unit_path(timer))
    if u is None: return None
    tk, base = u.get("Timer", {}), timer[:-6]
    target = (tk.get("Unit") or [base + ".service"])[0]
    files, why = dropin_info(timer, TIMER_DROPIN_KEYS)
    sched = None if why else parse_schedule(tk)         # a drop-in that changes the schedule: the file isn't the whole truth
    desc = unesc((u.get("Unit", {}).get("Description") or [""])[0])
    m = {"timer": timer, "unit": base, "service": target, "name": desc or base, "kind": "service", "full": False,
         "trigger": sched[0] if sched else None, "catchup": sched[1] if sched else True,
         "adv": {"delay": sched[2] if sched else 0}, "dropins": files,
         # "enabled" means the timer is active (will fire); "fstate" says whether it also survives a restart
         "enabled": (status[timer].get("ActiveState") == "active" if status is not None and timer in status
                     else unit_status(timer)[1]),
         "fstate": status[timer].get("UnitFileState", "") if status is not None and timer in status else ""}
    if why: m["why"] = why
    if not sched: return m
    if target == base + ".service" and os.path.isfile(f"{UNITS}/{target}"):
        sfiles, swhy = dropin_info(target, SERVICE_DROPIN_KEYS)
        m["dropins"] = files + sfiles
        s = parse_service(target)
        if swhy or "why" in s: m["why"] = swhy or s["why"]; return m
        m.update(kind=s["kind"], app=s.get("app", ""), command=s.get("command", ""),
                 adv={**s["adv"], "delay": sched[2]})
    m["full"] = True
    return m

def user_timers():
    try: files = sorted(os.listdir(UNITS))
    except OSError: return []
    return [n for n in files if n.endswith(".timer") and "@." not in n and os.path.isfile(f"{UNITS}/{n}")]

def timer_target(timer):
    u = read_unit(unit_path(timer)) or {}
    return (u.get("Timer", {}).get("Unit") or [timer[:-6] + ".service"])[0]

def unscheduled_services(timers):
    """Services in the user unit folder that no timer triggers."""
    used = {timer_target(t) for t in timers}
    try: files = sorted(os.listdir(UNITS))
    except OSError: return []
    return [n for n in files if n.endswith(".service") and "@." not in n and n not in used
            and os.path.isfile(f"{UNITS}/{n}")]

def list_services():
    """Names of the user's existing service units (not templates, not masked).
    Merges what systemd reports with the unit folders, so one source missing a unit doesn't hide it."""
    names = set()
    def add(n):
        if n.endswith(".service") and "@." not in n: names.add(n)
    for cmd in (("list-unit-files", "--type=service"), ("list-units", "--type=service", "--all")):
        for l in ctl(*cmd, "--no-legend", "--no-pager").stdout.splitlines():
            parts = l.replace("●", " ").replace("*", " ").split()
            if parts: add(parts[0])
    dirs = [UNITS, f"{APPS}/systemd/user", "/etc/systemd/user", "/usr/local/lib/systemd/user", "/usr/lib/systemd/user"]
    dirs += [f"{d}/systemd/user" for d in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":") if d]
    for d in dirs:
        try: entries = os.listdir(d)
        except OSError: continue
        for n in entries:
            p = f"{d}/{n}"
            if os.path.isdir(p) and not os.path.islink(p): continue
            if os.path.realpath(p) == "/dev/null": continue      # masked
            add(n)
    return sorted(names)

def unique_base(name):
    """A unit name derived from the task name that clashes with no existing file or service."""
    stem = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "task"
    taken = set(list_services())
    base, i = stem, 2
    while (f"{base}.service" in taken or any(os.path.exists(f"{UNITS}/{base}{e}") for e in (".service", ".timer"))):
        base = f"{stem}-{i}"; i += 1
    return base


