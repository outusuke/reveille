#: layer 07: writing and removing units, enabling timers, starting services
# ---------------------------------------------------------------- writing units
def abs_path(path, what):
    """`path` with a leading ~ expanded (systemd only knows a bare ~), which must then be absolute.
    A leading ! (condition negation) is kept. Raises ValueError saying which field is wrong."""
    neg = path.startswith("!")
    full = os.path.expanduser(path[neg:])
    if not os.path.isabs(full): raise ValueError(f"{what} must be an absolute path (or start with ~)")
    return ("!" if neg else "") + full

def exec_setting(old_service, adv, key, advkey):
    """(new line or None, keep) for an Exec*= setting the editor holds as a command in adv[advkey]. A command that
    is the same as the one already in the file keeps that line exactly as the user wrote it (keep is True, no new
    line); without the advkey at all the existing lines are not ours to touch."""
    cmd = (adv.get(advkey) or "").strip()
    old = [xunesc(joined(g).split("=", 1)[1].strip()) for g in groups(old_service)
           if joined(g).strip().startswith(f"{key}=")]
    same = bool(cmd) and old == [cmd]
    return (f"{key}={exec_words(cmd)}" if cmd and not same else None), same or advkey not in adv

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
        if adv.get("path"): unit.append(f"ConditionPathExists={esc(abs_path(adv['path'], 'The path condition'))}")
        if adv.get("then"): unit.append(f"OnSuccess={adv['then']}")
        if adv.get("fail"): unit.append(f"OnFailure={adv['fail']}")
        retries = int(adv.get("retries") or 0)
        wait = max(1, int(adv.get("retry_wait") or 5))
        if retries: unit += [f"StartLimitIntervalSec={retry_window(retries, wait, adv.get('timeout') or 0)}",
                             f"StartLimitBurst={retries + 1}"]
        low = bool(adv.get("low"))
        svc = [] if old_service else ["Type=oneshot"]
        if adv.get("cwd"): svc.append(f"WorkingDirectory={esc(abs_path(adv['cwd'], 'The working directory'))}")
        for kv in shlex.split(adv.get("env", "")): svc.append(f"Environment={shlex.quote(esc(kv))}")   # no $ expansion here
        if adv.get("timeout"): svc.append(f"TimeoutStartSec={int(adv['timeout'])}min")
        if retries: svc += ["Restart=on-failure", f"RestartSec={wait}min"]
        if low: svc += ["Nice=19", "IOSchedulingClass=idle"]
        cond_line, keep_cond = exec_setting(old_service, adv, "ExecCondition", "condition")
        after_line, keep_after = exec_setting(old_service, adv, "ExecStopPost", "after")
        if cond_line: svc.append(cond_line)
        if adv.get("online"): svc.append(f"ExecStartPre={WAIT_NET}")
        if t["kind"] == "app": svc.append("KillMode=process")    # the launcher exits at once: don't kill the app it started
        if not keep_exec: svc.append(f"ExecStart={build_exec(t)}")
        if after_line: svc.append(after_line)
        def keep_svc(k, v):                # a Nice= or IOSchedulingClass= that isn't the low-priority preset stays
            if k == "ExecCondition": return keep_cond
            if k == "ExecStopPost": return keep_after
            if k == "ExecStartPre": return v != WAIT_NET             # the user's own ExecStartPre= lines stay
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
                  + timer_lines(tr, t.get("catchup", True), adv.get("delay", 0), adv.get("wake", False)), timer_keep(tr)),
        "Install": ({"WantedBy"}, ["WantedBy=timers.target"], lambda k, v: v != "timers.target")})
    return service, timer

def ensure_notify_helper():
    """Create ~/.config/systemd/user/reveille-notify@.service (a template: the instance is the failed unit) unless it
    is there already, so a user's own edits stay. Raises ValueError if notify-send is missing; returns None."""
    path = f"{UNITS}/reveille-notify@.service"
    if os.path.exists(path): return
    tool = shutil.which("notify-send")
    if not tool: raise ValueError("notify-send was not found (install libnotify) for the notification")
    os.makedirs(UNITS, exist_ok=True)
    write_atomic(path, "[Unit]\nDescription=Notify that %I failed (created by reveille)\n\n[Service]\nType=oneshot\n"
                       f"ExecStart={xesc(shlex.quote(tool))} --urgency=critical --app-name=reveille 'Task failed' %I\n")

def apply_task(t):
    """Write the units for a task and (de)activate its timer. Returns an error text or None."""
    base = f"{UNITS}/{t['unit']}"
    service, timer = unit_texts(t, read_text(base + ".service"), read_text(base + ".timer"))
    if service is not None and t.get("adv", {}).get("fail") == NOTIFY_UNIT:
        try: ensure_notify_helper()
        except OSError as e: raise ValueError(f"Could not create the notification helper: {e.strerror or e}")
    undo = []                                  # how to put each file back if a later write fails
    try:
        os.makedirs(UNITS, exist_ok=True)
        for ext, text in ((".service", service), (".timer", timer)):
            path, existed = base + ext, os.path.exists(base + ext)
            if text is None:                   # the task was switched to an existing service: keep a backup
                if existed:
                    try: os.replace(path, path + ".reveille-bak"); undo.append(lambda p=path: os.replace(p + ".reveille-bak", p))
                    except OSError: pass
                continue
            prev = read_text(path)
            write_atomic(path, text)
            undo.append((lambda p=path, v=prev: write_atomic(p, v)) if existed else (lambda p=path: os.unlink(p)))
    except OSError as e:
        for f in reversed(undo):
            try: f()
            except OSError: pass
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
        elif n.endswith(".service"):            # a deleted task must not keep running, or linger as "failed"
            ctl("stop", n); ctl("reset-failed", n)
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

