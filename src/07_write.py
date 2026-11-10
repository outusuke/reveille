#: layer 07: writing and removing units, enabling timers, starting services
# ---------------------------------------------------------------- writing units
def unit_texts(t, old_service="", old_timer=""):
    """(service text or None, timer text). A task that triggers an existing service has no service of its own.
    The old file texts are merged, so lines the editor doesn't manage (ExecCondition=, comments, ...) survive.
    t["old_name"] == name leaves Description= alone; t["keep_exec"] leaves ExecStart= exactly as written.
    Raises ValueError if the command or app can't be turned into an ExecStart."""
    name, tr, adv = t["name"].replace("\n", " "), t["trigger"], t.get("adv", {})
    desc = t.get("old_name") != name
    never = lambda k, v: False
    service = None
    if t["kind"] != "service":
        keep_exec = bool(t.get("keep_exec") and old_service)
        unit = [f"Description={esc(name)}"] if desc else []
        if adv.get("ac"): unit.append("ConditionACPower=true")
        if adv.get("online"): unit += [f"Wants={ONLINE}", f"After={ONLINE}"]
        if adv.get("path"): unit.append(f"ConditionPathExists={esc(adv['path'])}")
        if adv.get("then"): unit.append(f"OnSuccess={adv['then']}")
        if adv.get("fail"): unit.append(f"OnFailure={adv['fail']}")
        retries = int(adv.get("retries") or 0)
        wait = max(1, int(adv.get("retry_wait") or 5))
        if retries: unit += [f"StartLimitIntervalSec={retry_window(retries, wait, adv.get('timeout') or 0)}",
                             f"StartLimitBurst={retries + 1}"]
        low = bool(adv.get("low"))
        svc = [] if old_service else ["Type=oneshot"]
        if adv.get("cwd"): svc.append(f"WorkingDirectory={esc(adv['cwd'])}")
        for kv in shlex.split(adv.get("env", "")): svc.append(f"Environment={shlex.quote(esc(kv))}")   # no $ expansion here
        if adv.get("timeout"): svc.append(f"TimeoutStartSec={int(adv['timeout'])}min")
        if retries: svc += ["Restart=on-failure", f"RestartSec={wait}min"]
        if low: svc += ["Nice=19", "IOSchedulingClass=idle"]
        if t["kind"] == "app": svc.append("KillMode=process")    # the launcher exits at once: don't kill the app it started
        if not keep_exec: svc.append(f"ExecStart={build_exec(t)}")
        def keep_svc(k, v):                # a Nice= or IOSchedulingClass= that isn't the low-priority preset stays
            return not low and ((k == "Nice" and v != "19") or (k == "IOSchedulingClass" and v != "idle"))
        def keep_unit(k, v):               # keep dependencies and conditions that aren't ours
            if k == "ConditionACPower": return v != "true"
            if k in ("Wants", "After"): return set(v.split()) != {ONLINE}
            return False
        service = merge_unit(old_service, {
            "Unit": (UNIT_KEYS | ({"Description"} if desc else set()), unit, keep_unit),
            "Service": (SERVICE_KEYS | (set() if keep_exec else {"ExecStart"})
                        | ({"KillMode"} if t["kind"] == "app" else set()),
                        svc, keep_svc)})
    timer = merge_unit(old_timer, {
        "Unit": ({"Description"} if desc else set(), [f"Description={esc(name)}"] if desc else [], never),
        "Timer": (TIMER_KEYS | {"Unit"},
                  ([f"Unit={t['service']}"] if t["kind"] == "service" else [])
                  + timer_lines(tr, t.get("catchup", True), adv.get("delay", 0)), timer_keep(tr)),
        "Install": ({"WantedBy"}, ["WantedBy=timers.target"], lambda k, v: v != "timers.target")})
    return service, timer

def apply_task(t):
    """Write the units for a task and (de)activate its timer. Returns an error text or None."""
    base = f"{UNITS}/{t['unit']}"
    service, timer = unit_texts(t, read_text(base + ".service"), read_text(base + ".timer"))
    try:
        os.makedirs(UNITS, exist_ok=True)
        for ext, text in ((".service", service), (".timer", timer)):
            if text is None:                   # the task was switched to an existing service: keep a backup
                if os.path.exists(base + ext):
                    try: os.replace(base + ext, base + ext + ".reveille-bak")
                    except OSError: pass
                continue
            write_atomic(base + ext, text)
    except OSError as e:
        return f"Could not write the unit files: {e.strerror or e}"
    ctl("daemon-reload")
    unit = f"{t['unit']}.timer"
    r = ctl("enable", "--now", unit) if t.get("enabled", True) else ctl("disable", "--now", unit)
    return r.stderr.strip() if r.returncode else None

def delete_plan(name):
    """The unit files that deleting `name` (a timer or a service without a timer) removes, as names in the
    user unit folder. A timer takes its same-named service along, unless another timer still triggers it."""
    names = [name]
    if name.endswith(".timer"):
        svc = name[:-6] + ".service"
        if timer_target(name) == svc and not any(timer_target(t) == svc for t in user_timers() if t != name):
            names.append(svc)
    def is_unit_file(n):
        p = f"{UNITS}/{n}"
        return os.path.islink(p) or os.path.isfile(p)
    return [n for n in names if is_unit_file(n)]

def remove_units(names):
    """Stop timers and delete the files (a symlink is removed as a link). Returns a snapshot for restore_units."""
    snap = {"items": [], "enable": [], "failed": []}
    for n in names:
        p = f"{UNITS}/{n}"
        if n.endswith(".timer"):
            if unit_status(n)[1]: snap["enable"].append(n)
            ctl("disable", "--now", n)
        try:
            if os.path.islink(p):
                snap["items"].append(("link", p, os.readlink(p)))
            else:
                with open(p, "rb") as f: snap["items"].append(("file", p, f.read()))
            os.unlink(p)
        except OSError:
            snap["items"] = [i for i in snap["items"] if i[1] != p]; snap["failed"].append(n)
    ctl("daemon-reload")
    return snap

def restore_units(snap):
    os.makedirs(UNITS, exist_ok=True)
    for kind, p, payload in snap["items"]:
        try:
            if os.path.lexists(p): continue            # something new took its place meanwhile: don't overwrite it
            if kind == "link": os.symlink(payload, p)
            else:
                with open(p, "wb") as f: f.write(payload)
        except OSError: pass
    ctl("daemon-reload")
    for n in snap["enable"]: ctl("enable", "--now", n)

def set_timer(name, on):
    """Turn a timer on (enable and start) or off (disable and stop). A hand-written timer without an [Install]
    section can't be enabled, so plain start/stop is the fallback. Returns an error text or None."""
    r = ctl("enable" if on else "disable", "--now", name)
    err = r.stderr.strip() if r.returncode else ""
    if r.returncode or unit_status(name)[1] != on:
        r2 = ctl("start" if on else "stop", name)
        if r2.returncode: return r2.stderr.strip() or err or "systemctl failed"
        if unit_status(name)[1] != on: return err or "The timer did not change state"
    return None

def start_service(service):
    """Queue a service to run now. Returns an error text or None."""
    r = ctl("start", "--no-block", service)
    return (r.stderr.strip() or "systemctl failed") if r.returncode else None

def start_now(m):
    return start_service(m["service"])

