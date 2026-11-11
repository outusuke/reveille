#: layer 09: importing a crontab: read the lines, convert the schedules, plan and create the tasks
# ---------------------------------------------------------------- crontab
CRON_FIELDS = (("minute", 0, 59, {}), ("hour", 0, 23, {}), ("day of month", 1, 31, {}),
               ("month", 1, 12, {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}),
               ("day of week", 0, 7, {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())}))
CRON_MACROS = {"@yearly": "*-01-01 00:00:00", "@annually": "*-01-01 00:00:00", "@monthly": "*-*-01 00:00:00",
               "@weekly": "Sun *-*-* 00:00:00",            # systemd's own "weekly" is Monday, cron's is Sunday
               "@daily": "*-*-* 00:00:00", "@midnight": "*-*-* 00:00:00", "@hourly": "*-*-* *:00:00"}
CRON_NO_ENV = {"MAILTO", "MAILFROM", "SHELL", "CRON_TZ", "LOGNAME"}      # cron settings, not variables for the command
CRON_NOISE = re.compile(r"m\s+h\s+dom|DO NOT EDIT|\(.* installed on|\(Cron version", re.I)   # comments crontab adds itself
CRON_BUILTINS = {"cd", "export", "exit", "source", ".", "exec", "set", "unset", "umask", "ulimit", "alias", "eval",
                 "read", "trap", "wait"}

def cron_field(text, lo, hi, names, label):
    """The values one cron field selects, as a set. Raises ValueError saying what is wrong."""
    def val(x, item):
        if x.isdigit(): return int(x)
        if x.lower() in names: return names[x.lower()]
        raise ValueError(f"{label}: {item!r} is not understood")
    out = set()
    for item in text.split(","):
        rng, slash, step = item.partition("/")
        if slash:
            if not step.isdigit() or int(step) < 1: raise ValueError(f"{label}: bad step in {item!r}")
            if rng != "*" and "-" not in rng:
                raise ValueError(f"{label}: {item!r} means different things to different crons; write */N or A-B/N")
        if rng == "*": a, b = lo, hi
        elif "-" in rng:
            p, _, q = rng.partition("-"); a, b = val(p, item), val(q, item)
        else: a = b = val(rng, item)
        if not lo <= a <= b <= hi: raise ValueError(f"{label}: {item!r} is out of range ({lo} to {hi})")
        out |= set(range(a, b + 1, int(step) if slash else 1))
    return out

def cron_list(vals, lo, hi, lab, steps=0):
    """A set as systemd writes it: * for all, A/N for an even run from the start, A..B for 3 or more in a row,
    else a comma list. `steps` is the fewest values worth writing as A/N (0: never)."""
    vals = sorted(vals)
    if vals == list(range(lo, hi + 1)): return "*"
    st = vals[1] - vals[0] if len(vals) > 1 else 0
    if steps and len(vals) >= steps and 2 <= st > vals[0] and vals == list(range(vals[0], hi + 1, st)):
        return f"{vals[0]}/{st}"
    out, i = [], 0
    while i < len(vals):
        j = i
        while j + 1 < len(vals) and vals[j + 1] == vals[j] + 1: j += 1
        out += [f"{lab(vals[i])}..{lab(vals[j])}"] if j - i >= 2 else [lab(v) for v in vals[i:j + 1]]
        i = j + 1
    return ",".join(out)

def cron_schedule(spec):
    """(trigger, warnings) for the five schedule fields of a cron line, or an @macro. Raises ValueError.
    Cron fires on the wall clock, so even "*/15" is a calendar expression here, never an interval."""
    if spec.startswith("@"):
        if spec == "@reboot":
            return {"type": "login", "login_sec": 10}, ["@reboot becomes 'At login': it runs when your session starts, "
                                                      "not when the machine boots (turn on lingering for that)"]
        if spec not in CRON_MACROS: raise ValueError(f"{spec} is not a cron schedule")
        return from_calendar(CRON_MACROS[spec]), []
    parts = spec.split()
    if len(parts) != 5: raise ValueError("a cron line needs five schedule fields")
    minute, hour, dom, mon, dow = (cron_field(p, lo, hi, names, label) for p, (label, lo, hi, names) in zip(parts, CRON_FIELDS))
    dow = {d % 7 for d in dow}                              # 0 and 7 are both Sunday
    # cron: if day of month and weekday both start with a digit or name, a day matches either; otherwise both must
    either = not parts[2].startswith("*") and not parts[4].startswith("*")
    if either and (len(dom) == 31 or len(dow) == 7): dom, dow = set(range(1, 32)), set(range(7))   # "either" with "any day"
    two = either and len(dom) < 31 and len(dow) < 7
    pad = "{:02d}".format
    time = f"{cron_list(hour, 0, 23, pad, 5)}:{cron_list(minute, 0, 59, pad, 3)}:00"
    days = cron_list([(d - 1) % 7 for d in dow], 0, 6, DAYS.__getitem__)       # Monday is 0 here
    d, m = cron_list(dom, 1, 31, pad, 3), cron_list(mon, 1, 12, pad, 3)
    if two:
        exprs = [f"{days} *-{m}-* {time}", f"*-{m}-{d} {time}"]
        warn = ["day of month and weekday are both set, so cron runs on either; written as two schedules"]
    else:
        exprs, warn = [f"{days + ' ' if days != '*' else ''}*-{m}-{d} {time}"], []
    return (from_calendar(exprs[0]) if len(exprs) == 1 else {"type": "custom", "expr": " | ".join(exprs)}), warn

def parse_crontab(text):
    """The entries of a crontab as dicts: line, raw, hint (the comment just above), env (the VAR=value lines above it),
    and spec + command, or error for a line that isn't an entry. Comments and blank lines are skipped."""
    env, hint, out = {}, "", []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line: hint = ""; continue
        if line.startswith("#"):
            c = line.lstrip("#").strip()
            hint = "" if CRON_NOISE.search(c) or re.match(r"[\d*@]", c) else c
            continue
        m = re.fullmatch(r"([A-Za-z_]\w*)\s*=\s*(.*)", line)
        if m:
            v = m[2].strip()
            env[m[1]] = v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v
            hint = ""; continue
        macro = line.startswith("@")
        parts = line.split(None, 1 if macro else 5)
        item = {"line": n, "raw": line, "hint": hint, "env": dict(env)}
        if len(parts) < (2 if macro else 6): item["error"] = "not a valid cron line"
        else: item["spec"], item["command"] = " ".join(parts[:-1]), parts[-1].strip()
        out.append(item); hint = ""
    return out

def cron_task_command(cmd, shell="/bin/sh"):
    """The command as the editor holds it. cron hands every line to a shell; a unit runs its command directly, so
    anything that needs a shell (pipes, redirects, variables, quotes, cd) is wrapped in `SHELL -c '...'`."""
    cmd = cmd.replace("\\%", "%")
    first = cmd.split()[0]
    plain = (re.fullmatch(r"[\w@+:,./-]+(?: [\w@+=:,./-]+)*", cmd) and first not in CRON_BUILTINS
             and (first.startswith("/") or "/" not in first))
    return cmd if plain else f"{shell} -c {shlex.quote(cmd)}"

def cron_name(e, cmd):
    words = [w for w in cmd.split() if not re.match(r"\w+=", w)]
    base = os.path.basename(words[0]) if words and words[0] not in CRON_BUILTINS else ""
    return e["hint"] or base or f"Cron job (line {e['line']})"

def existing_cron_keys():
    """(command, schedule) of every command task already there, to tell what an import would duplicate."""
    keys = set()
    for t in user_timers():
        m = load_task(t)
        if m and m.get("full") and m["kind"] == "command" and m["trigger"]:
            keys.add((m["command"], on_calendar(m["trigger"]) or m["trigger"]["type"]))
    return keys

def crontab_plan(text, known=None):
    """What importing a crontab would do, one dict per entry: line, raw, name, schedule (in words), warnings, task,
    general (notes about the whole file, such as MAILTO, which are shown once), next (when a new task would run next),
    and status: "new", "duplicate" (a task with the same command and schedule exists) or "skip" (reason says why).
    Writes nothing. A task is only planned if its command can be run and systemd accepts its schedule."""
    known = existing_cron_keys() if known is None else known
    plan = []
    for e in parse_crontab(text):
        it = {"line": e["line"], "raw": e["raw"], "status": "skip", "reason": "", "warnings": [], "general": [], "next": "", "name": "",
              "schedule": "", "task": None}
        plan.append(it)
        if "error" in e: it["reason"] = e["error"]; continue
        try: tr, it["warnings"] = cron_schedule(e["spec"])
        except ValueError as x: it["reason"] = str(x); continue
        if re.search(r"(?<!\\)%", e["command"]):
            it["reason"] = "the command has a bare %, which cron turns into a newline and input; write \\% or rewrite it"
            continue
        env = e["env"]
        shell = env["SHELL"] if os.path.isabs(env.get("SHELL", "")) else "/bin/sh"
        if env.get("MAILTO"): it["general"].append("MAILTO is not carried over: output goes to the journal "
                                                   "(use 'If it fails, run' to get notified)")
        if env.get("CRON_TZ"): it["general"].append("CRON_TZ is not applied: times follow the system time zone")
        cmd = cron_task_command(e["command"], shell)
        t = {"name": cron_name(e, e["command"]), "kind": "command", "command": cmd, "trigger": tr, "catchup": False,
             "enabled": True, "adv": {"delay": 0, "env": " ".join(shlex.quote(f"{k}={v}") for k, v in env.items()
                                                                   if k not in CRON_NO_ENV)}}
        it["name"], it["schedule"] = t["name"], describe(tr)
        try: run = xunesc(build_exec(t))
        except ValueError as x: it["reason"] = str(x); continue
        cal = on_calendar(tr)
        if cal and bad_calendar(cal): it["reason"] = f"systemd rejected the converted schedule ({cal})"; continue
        key = (run, cal or tr["type"])
        it["task"], it["status"] = t, "duplicate" if key in known else "new"
        if key in known: it["reason"] = "a task with this command and schedule already exists"
        if it["status"] == "new": it["next"] = next_elapse(tr).splitlines()[0]
        known.add(key)
    return plan

def cron_notes(plan):
    """Notes about the whole crontab (MAILTO, CRON_TZ), each once."""
    return sorted({g for it in plan for g in it["general"]})

def cron_row_texts(it):
    """(title, subtitle) of one entry for a list: what will happen to it, the original line, then any warnings."""
    first = {"new": f"{it['schedule']} · next {it['next']}",
             "duplicate": "Already a task with this command and schedule",
             "skip": f"Can't import: {it['reason']}"}[it["status"]]
    return it["name"] or f"Line {it['line']}", "\n".join([first, f"cron: {it['raw']}"] + [f"• {w}" for w in it["warnings"]])

def crontab_report(plan):
    """The plan as text for the command line."""
    out = []
    for it in plan:
        label = {"new": "will import", "duplicate": "already imported", "skip": "can't import"}[it["status"]]
        out.append(f"Line {it['line']}: {it['name'] or it['raw']}  [{label}]")
        out.append(f"  cron      {it['raw']}")
        if it["status"] != "skip":
            out.append(f"  schedule  {it['schedule']}")
            if it["status"] == "new": out.append(f"  next      {it['next']}")
        if it["reason"]: out.append(f"  {'why' if it['status'] == 'skip' else 'note'}       {it['reason']}")
        out += [f"  note      {w}" for w in it["warnings"]]
        out.append("")
    return "\n".join(out + [f"Note: {g}" for g in cron_notes(plan)]).rstrip()

def import_summary(results, enabled):
    """One line for a toast: what import_crontab did."""
    bad = [err for _it, _unit, err in results if err]
    n = len(results) - len(bad)
    msg = f"Imported {n} task{'' if n == 1 else 's'}" + ("" if enabled else " (switched off)")
    return msg + (f"; {len(bad)} had a problem: {bad[0]}" if bad else "")

def import_crontab(plan, enabled=True):
    """Create the planned tasks. Returns [(entry, unit name, error text or None)]. Each unit name is picked just before
    its task is written, so two entries with the same name can't collide."""
    done = []
    for it in plan:
        if it["status"] != "new": continue
        t = {**it["task"], "unit": unique_base(it["task"]["name"]), "enabled": enabled}
        try: err = apply_task(t)
        except ValueError as x: err = str(x)
        done.append((it, t["unit"], err))
    return done

def read_crontab(path=None):
    """(text, None) from a file ("-" is standard input) or from `crontab -l`; ("", error text) if that fails.
    A user without a crontab gives ("", None)."""
    if path:
        try:
            if path == "-": return sys.stdin.read(), None
            with open(path, encoding="utf-8", errors="replace") as f: return f.read(), None
        except OSError as e: return "", f"Could not read {path}: {e.strerror or e}"
    r = sh("crontab", "-l")
    if r is None: return "", "crontab is not available here (--file reads a saved one)"
    if r.returncode:
        return ("", None) if "no crontab" in r.stderr.lower() else ("", r.stderr.strip() or "crontab -l failed")
    return r.stdout, None
