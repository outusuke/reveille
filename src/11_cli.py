#: layer 11: command line, main(), the __main__ guard
def cmd_services():
    """Diagnostics: what the service picker sees."""
    print(f"running: {SELF}\ninstalled copy: {INSTALLED} ({'exists' if os.path.isfile(INSTALLED) else 'none'})")
    for d in (UNITS, f"{APPS}/systemd/user"):
        try: print(f"{d}: {sorted(os.listdir(d))}")
        except OSError as e: print(f"{d}: {e.strerror}")
    r = list_services(); print(f"\n{len(r)} services found:"); print("\n".join(r))
    return 0

def cmd_list():
    """Print every task with its schedule, next run and last result."""
    tasks = gather()["tasks"]
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
    sub.add_parser("list", help="print every task with its schedule, next run and last result")
    r = sub.add_parser("run", help="run a task or service now")
    r.add_argument("name", help="task name or unit name, as shown by 'list'")
    return ap

def main(argv=None):
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.cmd == "services": return cmd_services()
    if args.cmd == "list": return cmd_list()
    if args.cmd == "run": return cmd_run(args.name)
    if args.cmd in ("install", "uninstall"): return cmd_menu(args.cmd == "install")
    return cmd_gui()


if __name__ == "__main__":
    sys.exit(main())
