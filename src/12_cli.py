#: layer 12: command line, main(), the __main__ guard
def cmd_services():
    """Diagnostics: what the service picker sees."""
    print(f"running: {SELF}\ninstalled copy: {INSTALLED} ({'exists' if os.path.isfile(INSTALLED) else 'none'})")
    for d in (UNITS, f"{APPS}/systemd/user"):
        try: print(f"{d}: {sorted(os.listdir(d))}")
        except OSError as e: print(f"{d}: {e.strerror}")
    r = list_services(); print(f"\n{len(r)} services found:"); print("\n".join(r))
    return 0

def cmd_list(as_json=False):
    """Print every task with its schedule, next run and last result (as JSON for scripts)."""
    tasks = gather()["tasks"]
    if as_json:
        print(json.dumps([{"unit": m["unit"], "name": m["name"], "schedule": describe(m["trigger"]) if m["trigger"] else None,
                           "enabled": m["enabled"], "wake": m.get("adv", {}).get("wake", False), "running": m["running"], "retrying": m.get("retrying", False),
                           "next": m["next"] or None, "last": m["last"]} for m in tasks], indent=2))
        return 0
    if not tasks: print("No tasks"); return 0
    for m in tasks:
        sub, _ = task_texts(m)
        print(f"{m['unit']}: {m['name']}"); print("  " + sub.replace("\n", "\n  "))
    return 0

def find_runnable(name, data):
    """The service a name refers to: a task's unit name, timer, or display name, or a service without a timer.
    Returns (service, None) or (None, error text)."""
    key = name.lower()
    for m in data["tasks"]:
        if key in (m["unit"].lower(), m["timer"].lower(), m["name"].lower(), m["service"].lower()):
            return m["service"], None
    for sv in data["free"]:
        if key in (sv.lower(), sv[:-8].lower()): return sv, None
    return None, f"No task or service named {name!r}. Try: reveille list"

def cmd_run(name):
    service, err = find_runnable(name, gather())
    if err: print(err, file=sys.stderr); return 1
    err = start_service(service)
    print(f"Could not start {service}: {err}" if err else f"Started {service}", file=sys.stderr if err else sys.stdout)
    return 1 if err else 0

def find_task(name, data):
    """The task a name refers to (unit name, timer, service or display name). Returns (task, None) or (None, error text)."""
    key = name.lower()
    for m in data["tasks"]:
        if key in (m["unit"].lower(), m["timer"].lower(), m["name"].lower(), m["service"].lower()): return m, None
    return None, f"No task named {name!r}. Try: reveille list"

def cmd_switch(name, on):
    """Turn a task's timer on or off, as the switch in the window does."""
    m, err = find_task(name, gather())
    if not err: err = set_timer(m["timer"], on)
    if err: print(err, file=sys.stderr); return 1
    print(f"{'Enabled' if on else 'Disabled'} {m['timer']}")
    return 0

def cmd_logs(name, lines):
    """Print the last lines of a task's (or a service's) journal."""
    service, err = find_runnable(name, gather())
    text = ""
    if not err: text, err = read_log(service, lines)
    if err: print(err, file=sys.stderr); return 1
    print(text)
    return 0

def schedule_from_args(a):
    """(trigger, None) from the `new` options, or (None, error text)."""
    if a.login: return {"type": "login", "login_sec": 10}, None
    if a.every:
        secs = exact_span(a.every); step = split_interval(secs) if secs else None
        if not step: return None, f"--every {a.every!r} is not a time span the editor can show (try 15min, 2h, 1d)"
        return {"type": "interval", "every": step[0], "unit": step[1]}, None
    if a.calendar: return from_calendar(a.calendar), None
    times = parse_times(a.at or "")
    if not times: return None, "--at needs clock times like 09:00 or 08:00,12:30"
    if a.days:
        days = parse_days(a.days)
        if not days or len(times) > 1: return None, "--days takes days like Mon,Wed or Mon..Fri, and only one --at time"
        return from_calendar(f"{a.days} {times[0]}"), None
    return ({"type": "times", "times": times} if len(times) > 1 else from_calendar(times[0])), None

def cmd_new(a):
    """Create a command task from the command line, the way the editor would."""
    tr, err = schedule_from_args(a)
    cal = on_calendar(tr) if tr else None
    if not err and cal and bad_calendar(cal): err = f"systemd rejected the schedule {cal!r}"
    if err: print(err, file=sys.stderr); return 1
    t = {"name": a.name, "kind": "command", "command": a.command, "trigger": {**DEFAULT_TR, **tr}, "catchup": True,
         "enabled": not a.disabled, "adv": {"wake": a.wake}}
    try:
        t["unit"] = unique_base(a.name)
        if a.dry_run:                                   # show exactly what would be written, write nothing
            service, timer = unit_texts(t)
            print(f"# {UNITS}/{t['unit']}.service\n{service}\n# {UNITS}/{t['unit']}.timer\n{timer}", end="")
            return 0
        err = apply_task(t)
    except ValueError as x: err = str(x)
    if err: print(err, file=sys.stderr); return 1
    print(f"Created {t['unit']}.timer: {describe(t['trigger'])}" + (" (switched off)" if a.disabled else ""))
    return 0

def cmd_import_cron(path, apply, disabled):
    """Preview, or with --apply create, tasks from a crontab. The crontab itself is never changed."""
    text, err = read_crontab(path)
    if err: print(err, file=sys.stderr); return 1
    plan = crontab_plan(text)
    if not plan: print("No cron entries found"); return 0
    print(crontab_report(plan))
    new = sum(it["status"] == "new" for it in plan)
    if not apply:
        print(f"\nPreview only, nothing was written. {new} of {len(plan)} can be imported" + ("; add --apply to create them." if new else "."))
        return 0
    if not new: print("\nNothing to import."); return 0
    failed = 0
    print()
    for it, unit, err in import_crontab(plan, enabled=not disabled):
        failed += bool(err)
        print(f"Problem with {it['name']!r} ({unit}): {err}" if err else f"Created {unit}.timer: {it['name']}")
    print("\nYour crontab was not changed. " + ("The new timers are off: turn each on in reveille when you remove its cron line."
          if disabled else "Remove the imported lines (crontab -e) or those jobs will run twice."))
    return 1 if failed else 0

def cmd_menu(install):
    err = install_menu() if install else uninstall_menu()
    print(err or ("Added to the app menu" if install else "Removed from the app menu"))
    return 1 if err else 0

def cmd_gui():
    try:
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
    except (ImportError, ValueError) as e:
        print(f"reveille needs PyGObject, GTK 4 and libadwaita 1.5 or newer ({e}).\n"
              "The command-line options still work: see reveille --help.", file=sys.stderr)
        return 1
    return gui()

def build_parser():
    ap = argparse.ArgumentParser(prog="reveille", description="GTK4/libadwaita front end for systemd user timers.")
    ap.add_argument("--version", action="version", version=f"reveille {VERSION}")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND", title="commands (none opens the window)")
    sub.add_parser("install", help="add reveille to the app menu")
    sub.add_parser("uninstall", help="remove reveille from the app menu")
    sub.add_parser("services", help="list the services the picker finds (troubleshooting)")
    ls = sub.add_parser("list", help="print every task with its schedule, next run and last result")
    ls.add_argument("--json", action="store_true", help="print machine-readable JSON instead")
    r = sub.add_parser("run", help="run a task or service now")
    r.add_argument("name", help="task name or unit name, as shown by 'list'")
    for word, text in (("enable", "turn a task's timer on"), ("disable", "turn a task's timer off")):
        sub.add_parser(word, help=text).add_argument("name", help="task name or unit name, as shown by 'list'")
    lg = sub.add_parser("logs", help="print the last lines of a task's journal")
    lg.add_argument("name", help="task name or unit name, as shown by 'list'")
    lg.add_argument("-n", "--lines", type=int, default=200, metavar="N", help="how many lines (default 200)")
    nw = sub.add_parser("new", help="create a command task")
    nw.add_argument("name", help="the task's name")
    nw.add_argument("--command", required=True, help="the command to run (use sh -c '...' for pipes)")
    when = nw.add_mutually_exclusive_group(required=True)
    when.add_argument("--at", metavar="TIMES", help="every day at 09:00 (or several: 08:00,12:30)")
    when.add_argument("--every", metavar="SPAN", help="at an interval, such as 15min, 2h or 1d")
    when.add_argument("--calendar", metavar="EXPR", help="a systemd calendar expression, such as 'Mon..Fri 09:00'")
    when.add_argument("--login", action="store_true", help="shortly after login")
    nw.add_argument("--days", metavar="DAYS", help="with --at: only these days (Mon,Wed or Mon..Fri)")
    nw.add_argument("--disabled", action="store_true", help="create the timer switched off")
    nw.add_argument("--wake", action="store_true", help="wake the computer from suspend when the timer is due (WakeSystem=true)")
    nw.add_argument("--dry-run", action="store_true", help="print the unit files that would be written and change nothing")
    c = sub.add_parser("import-cron", help="turn crontab entries into tasks (preview unless --apply)")
    c.add_argument("--file", metavar="FILE", help="read this crontab file instead of 'crontab -l' (- for standard input)")
    c.add_argument("--apply", action="store_true", help="create the tasks (the default only shows what would happen)")
    c.add_argument("--disabled", action="store_true", help="with --apply: create the timers switched off")
    return ap

def main(argv=None):
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.cmd == "services": return cmd_services()
    if args.cmd == "list": return cmd_list(args.json)
    if args.cmd == "run": return cmd_run(args.name)
    if args.cmd in ("enable", "disable"): return cmd_switch(args.name, args.cmd == "enable")
    if args.cmd == "logs": return cmd_logs(args.name, args.lines)
    if args.cmd == "new": return cmd_new(args)
    if args.cmd == "import-cron": return cmd_import_cron(args.file, args.apply, args.disabled)
    if args.cmd in ("install", "uninstall"): return cmd_menu(args.cmd == "install")
    return cmd_gui()


if __name__ == "__main__":
    sys.exit(main())
