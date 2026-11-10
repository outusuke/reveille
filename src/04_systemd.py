#: layer 04: systemctl access: ctl, props, show_many, unit status, last run
def ctl(*a):
    return subprocess.run(["systemctl", "--user", *a], capture_output=True, text=True)

def props(unit, *names):
    r = ctl("show", unit, *[x for n in names for x in ("-p", n)])
    return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)

def show_many(units, *names):
    """One `systemctl show` for many units instead of one process each: {unit: {property: value}}."""
    if not units: return {}
    r = ctl("show", *units, *[x for n in ("Id",) + names for x in ("-p", n)])
    out = {}
    for block in r.stdout.split("\n\n"):
        kv = dict(l.split("=", 1) for l in block.splitlines() if "=" in l)
        if "Id" in kv: out[kv["Id"]] = kv
    return out

def unit_status(unit):
    """(next run text or "", is_active) for a timer unit"""
    kv = props(unit, "ActiveState", "NextElapseUSecRealtime")
    return kv.get("NextElapseUSecRealtime", "").strip(), kv.get("ActiveState") == "active"

def last_run_from(kv):
    if not kv.get("ExecMainExitTimestamp"): return None
    rc = 0 if kv.get("Result") == "success" else (int(kv.get("ExecMainStatus") or 0) or 1)
    return {"time": kv["ExecMainExitTimestamp"], "rc": rc}

def last_run(service):
    """Last result of a service, straight from systemd: {"time", "rc"} or None."""
    return last_run_from(props(service, "Result", "ExecMainStatus", "ExecMainExitTimestamp"))


