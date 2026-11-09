#!/usr/bin/env python3
"""Tests for reveille's unit-file logic. No systemd, GTK or network needed: systemctl calls are stubbed
and everything is written to a temporary XDG_CONFIG_HOME.   Run: python3 test_reveille.py"""
import importlib.machinery, importlib.util, os, shutil, tempfile, time, unittest

TMP = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = TMP
HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("rv", os.path.join(HERE, "reveille"))
_spec = importlib.util.spec_from_loader("rv", _loader)
rv = importlib.util.module_from_spec(_spec)
_loader.exec_module(rv)

CALLS = []
def fake_ctl(*a):
    CALLS.append(a)
    return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()
rv.ctl = fake_ctl

WEEKLY = {**rv.DEFAULT_TR, "type": "weekly", "days": ["Mon", "Fri"], "hour": 7, "minute": 30}

def task(**kw):
    t = {"name": "Backup", "kind": "command", "command": 'sh -c "echo $HOME | cat"', "trigger": WEEKLY,
         "catchup": True, "enabled": True, "adv": {}}
    t.update(kw)
    t.setdefault("unit", rv.unique_base(t["name"]))
    return t

def read(path):
    with open(path) as f: return f.read()

def write(name, text):
    os.makedirs(rv.UNITS, exist_ok=True)
    with open(f"{rv.UNITS}/{name}", "w") as f: f.write(text)

SIMPLE_SERVICE = "[Unit]\nDescription=x\n\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n"
SIMPLE_TIMER = "[Unit]\nDescription=x\n\n[Timer]\nOnCalendar=*-*-* 03:00:00\n\n[Install]\nWantedBy=timers.target\n"


class Base(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(f"{TMP}/systemd", ignore_errors=True)
        shutil.rmtree(f"{TMP}/reveille", ignore_errors=True)
        CALLS.clear()


class RoundTrip(Base):
    def test_command_task_survives_write_and_read(self):
        adv = {"cwd": "/tmp", "env": 'A=1 B="x y"', "timeout": 5, "ac": True, "online": True, "delay": 60}
        t = task(name="Backup 100%", adv=adv)
        self.assertEqual(t["unit"], "backup-100")
        self.assertIsNone(rv.apply_task(t))
        m = rv.load_task("backup-100.timer")
        self.assertTrue(m["full"])
        self.assertEqual(m["name"], "Backup 100%")
        self.assertEqual(m["kind"], "command")
        self.assertEqual(m["trigger"]["days"], ["Mon", "Fri"])
        self.assertEqual((m["trigger"]["hour"], m["trigger"]["minute"]), (7, 30))
        self.assertEqual(m["adv"], {"cwd": "/tmp", "env": "A=1 'B=x y'", "timeout": 5, "ac": True,
                                    "online": True, "delay": 60})
        self.assertIn("echo $HOME | cat", m["command"])

    def test_percent_and_dollar_are_escaped_in_the_files(self):
        rv.apply_task(task(name="Backup 100%"))
        svc = read(f"{rv.UNITS}/backup-100.service")
        self.assertIn("Description=Backup 100%%", svc)
        self.assertIn("$$HOME", svc)

    def test_timer_runs_the_command_directly(self):
        rv.apply_task(task(command="true"))
        svc = read(f"{rv.UNITS}/backup.service")
        self.assertIn("ExecStart=/", svc)
        self.assertNotIn("run-task", svc)
        self.assertNotIn("reveille", svc.split("ExecStart=")[1])

    def test_existing_service_task_has_only_a_timer(self):
        rv.apply_task(task(name="Nightly", kind="service", service="foo.service"))
        self.assertFalse(os.path.exists(f"{rv.UNITS}/nightly.service"))
        self.assertIn("Unit=foo.service", read(f"{rv.UNITS}/nightly.timer"))
        m = rv.load_task("nightly.timer")
        self.assertTrue(m["full"]); self.assertEqual((m["kind"], m["service"]), ("service", "foo.service"))

    def test_disabled_task_is_disabled_not_enabled(self):
        rv.apply_task(task(enabled=False))
        self.assertIn(("disable", "--now", "backup.timer"), CALLS)
        self.assertNotIn(("enable", "--now", "backup.timer"), CALLS)

    def test_unknown_command_is_refused_before_anything_is_written(self):
        with self.assertRaises(ValueError):
            rv.apply_task(task(command="definitely-not-a-real-binary-xyz"))
        self.assertFalse(os.path.exists(rv.UNITS) and os.listdir(rv.UNITS))


GPODDER_TIMER = """[Unit]
Description=Run gpodder-update.service every 2 hours

[Timer]
OnCalendar=0/2:00:00
Persistent=true

[Install]
WantedBy=timers.target
"""
GPODDER_SERVICE = """[Unit]
Description=Run gpodder update and download

[Service]
SyslogIdentifier=gpodder update
Type=oneshot
ExecCondition=/bin/sh -c 'nmcli -g METERED general status | grep -qv "yes"'
ExecStart=/usr/bin/systemd-inhibit --what=sleep:idle --mode=block --who="gpodder update" --why="Downloading" /bin/sh -c "flatpak run --command=gpo org.gpodder.gpodder-adaptive update && flatpak run --command=gpo org.gpodder.gpodder-adaptive download"
"""


class Editable(Base):
    """Existing units are editable unless a managed setting can't be represented; unmanaged lines survive saves."""
    def load(self, svc, tim=SIMPLE_TIMER):
        write("x.service", svc); write("x.timer", tim)
        return rv.load_task("x.timer")

    def save(self, m, **changes):
        """What the editor does on Save: the loaded task, changed, with old_name/keep_exec set."""
        t = {k: m[k] for k in ("unit", "name", "kind", "trigger", "catchup", "enabled", "adv", "service")}
        t.update(app=m.get("app"), command=m.get("command"), old_name=m["name"], keep_exec=True)
        t.update(changes)
        self.assertIsNone(rv.apply_task(t))
        return rv.read_text(f"{rv.UNITS}/{m['unit']}.service"), rv.read_text(f"{rv.UNITS}/{m['unit']}.timer")

    def test_plain_unit_is_editable(self):
        self.assertTrue(self.load(SIMPLE_SERVICE)["full"])

    def test_unknown_keys_and_sections_no_longer_lock(self):
        svc = SIMPLE_SERVICE.replace("Type=oneshot", "Type=oneshot\nUser=nobody") + "\n[Install]\nWantedBy=default.target\n"
        self.assertTrue(self.load(svc)["full"])
        self.assertTrue(self.load(SIMPLE_SERVICE, SIMPLE_TIMER.replace("[Timer]\n", "[Timer]\nAccuracySec=1s\n"))["full"])
        self.assertTrue(self.load(SIMPLE_SERVICE.replace("Type=oneshot\n", ""))["full"])
        self.assertTrue(self.load(SIMPLE_SERVICE.replace("oneshot", "simple"))["full"])
        self.assertTrue(self.load(SIMPLE_SERVICE.replace("[Service]", "After=mnt-data.mount\n\n[Service]"))["full"])

    def lock_reason(self, svc):
        m = self.load(svc)
        self.assertFalse(m["full"]); return m["why"]

    def test_still_locked_when_a_managed_setting_cant_be_shown(self):
        self.assertIn("prefix", self.lock_reason(SIMPLE_SERVICE.replace("=/usr/bin/true", "=-/usr/bin/true")))
        self.assertIn("exactly one", self.lock_reason(SIMPLE_SERVICE + "ExecStart=/usr/bin/false\n"))
        self.assertIn("minutes", self.lock_reason(SIMPLE_SERVICE.replace("[Service]\n", "[Service]\nTimeoutStartSec=90\n")))
        self.assertIn("quote", self.lock_reason(SIMPLE_SERVICE.replace("[Service]\n", "[Service]\nEnvironment=\"A=1\n")))

    def test_timer_pointing_at_other_service_is_a_service_task(self):
        write("x.timer", SIMPLE_TIMER.replace("[Timer]\n", "[Timer]\nUnit=other.service\n"))
        m = rv.load_task("x.timer")
        self.assertEqual((m["full"], m["kind"], m["service"]), (True, "service", "other.service"))

    def test_unsupported_schedule_has_no_trigger(self):
        write("x.timer", SIMPLE_TIMER.replace("OnCalendar=*-*-* 03:00:00", "OnActiveSec=5min"))
        m = rv.load_task("x.timer")
        self.assertFalse(m["full"]); self.assertIsNone(m["trigger"])

    def test_gpodder_unit_is_fully_editable(self):
        m = self.load(GPODDER_SERVICE, GPODDER_TIMER)
        self.assertTrue(m["full"]); self.assertEqual(m["kind"], "command")
        self.assertEqual(m["trigger"]["type"], "custom")

    def test_new_schedule_keeps_everything_else_verbatim(self):
        m = self.load(GPODDER_SERVICE, GPODDER_TIMER)
        svc, tim = self.save(m, trigger={**WEEKLY})
        self.assertEqual(svc, GPODDER_SERVICE)                     # untouched byte for byte
        self.assertIn("OnCalendar=Mon,Fri *-*-* 07:30:00", tim)
        self.assertNotIn("0/2:00:00", tim)
        self.assertIn("Description=Run gpodder-update.service every 2 hours", tim)

    def test_changed_command_replaces_only_exec_start(self):
        m = self.load(GPODDER_SERVICE, GPODDER_TIMER)
        svc, _ = self.save(m, command="true", keep_exec=False)
        self.assertIn("ExecCondition=/bin/sh -c 'nmcli -g METERED general status | grep -qv \"yes\"'", svc)
        self.assertIn("SyslogIdentifier=gpodder update", svc)
        self.assertIn("Description=Run gpodder update and download", svc)
        self.assertEqual(svc.count("ExecStart="), 1)
        self.assertIn("ExecStart=/", svc); self.assertNotIn("flatpak", svc)

    def test_new_options_are_added_and_old_ones_removed(self):
        m = self.load(GPODDER_SERVICE, GPODDER_TIMER)
        adv = {"cwd": "/tmp", "env": "A=1", "timeout": 5, "ac": True, "online": True, "delay": 0}
        svc, _ = self.save(m, adv=adv)
        for line in ("WorkingDirectory=/tmp", "Environment=A=1", "TimeoutStartSec=5min", "ConditionACPower=true",
                     "Wants=network-online.target", "ExecCondition="):
            self.assertIn(line, svc)
        write("x.service", svc)
        s2 = rv.parse_service("x.service")
        self.assertEqual(s2["adv"], {"cwd": "/tmp", "env": "A=1", "timeout": 5, "ac": True, "online": True})
        svc3, _ = self.save(m, adv={"cwd": "", "env": "", "timeout": 0, "ac": False, "online": False, "delay": 0})
        self.assertEqual(svc3, GPODDER_SERVICE)

    def test_rename_changes_both_descriptions(self):
        m = self.load(GPODDER_SERVICE, GPODDER_TIMER)
        svc, tim = self.save(m, name="Podcasts")
        self.assertIn("Description=Podcasts", svc); self.assertIn("Description=Podcasts", tim)

    def test_foreign_dependencies_and_conditions_are_kept(self):
        svc = SIMPLE_SERVICE.replace("[Service]", "After=mnt-data.mount network-online.target\nConditionPathExists=/x\n\n[Service]")
        m = self.load(svc)
        out, _ = self.save(m, adv={"cwd": "", "env": "", "timeout": 0, "ac": False, "online": False, "delay": 0})
        self.assertIn("After=mnt-data.mount network-online.target", out)
        self.assertIn("ConditionPathExists=/x", out)

    def test_comments_and_continuation_lines(self):
        svc = ("[Unit]\nDescription=x\n# keep me\n\n[Service]\nType=oneshot\n"
               "ExecStart=/usr/bin/echo one \\\n  two\nExecStartPost=/usr/bin/true\n")
        m = self.load(svc)
        self.assertEqual(m["command"], "/usr/bin/echo one two")
        out, _ = self.save(m, command="/usr/bin/true", keep_exec=False)
        self.assertIn("# keep me", out); self.assertIn("ExecStartPost=/usr/bin/true", out)
        self.assertNotIn("two", out)                               # the continuation line went with its ExecStart

    def test_switching_to_existing_service_backs_up_own_service_file(self):
        m = self.load(GPODDER_SERVICE, GPODDER_TIMER)
        self.save(m, kind="service", service="foo.service", keep_exec=False)
        self.assertFalse(os.path.exists(f"{rv.UNITS}/x.service"))
        self.assertEqual(rv.read_text(f"{rv.UNITS}/x.service.reveille-bak"), GPODDER_SERVICE)
        self.assertIn("Unit=foo.service", rv.read_text(f"{rv.UNITS}/x.timer"))

    def test_timer_without_install_section_gets_one(self):
        m = self.load(SIMPLE_SERVICE, "[Timer]\nOnCalendar=daily\n")
        _, tim = self.save(m)
        self.assertIn("[Install]\nWantedBy=timers.target", tim)


class AppTasks(Base):
    def test_app_task_keeps_the_app_alive_after_the_launcher_exits(self):
        write("x.service", SIMPLE_SERVICE.replace("/usr/bin/true", "/usr/bin/gio launch /usr/share/applications/conky.desktop"))
        write("x.timer", SIMPLE_TIMER)
        m = rv.load_task("x.timer"); self.assertEqual((m["kind"], m["app"]), ("app", "conky.desktop"))
        t = {k: m[k] for k in ("unit", "name", "kind", "trigger", "catchup", "enabled", "adv", "service")}
        t.update(app=m["app"], old_name=m["name"], keep_exec=True)
        svc, _ = rv.unit_texts(t, rv.read_text(f"{rv.UNITS}/x.service"), rv.read_text(f"{rv.UNITS}/x.timer"))
        self.assertEqual(svc.count("KillMode=process"), 1)
        self.assertIn("ExecStart=/usr/bin/gio launch /usr/share/applications/conky.desktop", svc)
        again, _ = rv.unit_texts(t, svc, "")
        self.assertEqual(again.count("KillMode=process"), 1)       # saving twice doesn't duplicate it

    def test_command_task_has_no_kill_mode(self):
        svc, _ = rv.unit_texts(task(command="true"))
        self.assertNotIn("KillMode", svc)


class MergeUnit(unittest.TestCase):
    def test_new_file_layout(self):
        out = rv.merge_unit("", {"Unit": ({"Description"}, ["Description=x"], lambda k, v: False),
                                 "Service": (set(), ["ExecStart=/bin/true"], lambda k, v: False)})
        self.assertEqual(out, "[Unit]\nDescription=x\n\n[Service]\nExecStart=/bin/true\n")

    def test_empty_spec_changes_nothing(self):
        text = "[Unit]\nA=1\n\n[Service]\nB=2\n"
        self.assertEqual(rv.merge_unit(text, {"Unit": (set(), [], lambda k, v: False)}), text)


class Schedules(unittest.TestCase):
    def parse(self, **kv):
        return rv.parse_schedule({k: v if isinstance(v, list) else [v] for k, v in kv.items()})

    def test_daily(self):
        tr, catchup, delay = self.parse(OnCalendar="*-*-* 07:10:00", Persistent="true")
        self.assertEqual((tr["type"], tr["hour"], tr["minute"], catchup, delay), ("daily", 7, 10, True, 0))

    def test_weekly_and_monthly(self):
        self.assertEqual(self.parse(OnCalendar="Mon,Wed *-*-* 09:00:00")[0]["days"], ["Mon", "Wed"])
        self.assertEqual(self.parse(OnCalendar="*-*-15 09:00:00")[0]["dom"], 15)

    def test_monthly_day_29_is_custom(self):
        self.assertEqual(self.parse(OnCalendar="*-*-29 09:00:00")[0]["type"], "custom")

    def test_two_calendar_lines_become_one_custom_expression(self):
        tr = self.parse(OnCalendar=["*-*-* 07:10:00", "*-*-* 18:00:00"])[0]
        self.assertEqual((tr["type"], tr["expr"]), ("custom", "*-*-* 07:10:00 | *-*-* 18:00:00"))

    def test_interval_and_login(self):
        tr = self.parse(OnStartupSec="30min", OnUnitActiveSec="30min")[0]
        self.assertEqual((tr["type"], tr["every"], tr["unit"]), ("interval", 30, "min"))
        self.assertEqual(self.parse(OnStartupSec="10s")[0]["type"], "login")

    def test_unsupported_keys_return_none(self):
        self.assertIsNone(self.parse(OnActiveSec="5min"))
        self.assertIsNone(self.parse(OnCalendar="daily", RandomizedDelaySec="soon"))

    def test_timer_lines_roundtrip(self):
        for tr in (WEEKLY, {**rv.DEFAULT_TR, "type": "interval", "every": 2, "unit": "h"}, {**rv.DEFAULT_TR, "type": "login"}):
            lines = rv.timer_lines(tr, True, 30)
            kv = {}
            for l in lines: k, v = l.split("=", 1); kv.setdefault(k, []).append(v)
            back, catchup, delay = rv.parse_schedule(kv)
            self.assertEqual(back["type"], tr["type"]); self.assertEqual(delay, 30)


class Delete(Base):
    def delete(self, name):
        return rv.remove_units(rv.delete_plan(name))

    def test_timer_takes_its_own_service_along(self):
        rv.apply_task(task(command="true"))
        self.assertEqual(rv.delete_plan("backup.timer"), ["backup.timer", "backup.service"])
        snap = self.delete("backup.timer")
        self.assertEqual(os.listdir(rv.UNITS), [])
        self.assertIn(("disable", "--now", "backup.timer"), CALLS)
        rv.restore_units(snap)
        self.assertEqual(sorted(os.listdir(rv.UNITS)), ["backup.service", "backup.timer"])

    def test_locked_timer_can_be_deleted_too(self):
        write("x.service", SIMPLE_SERVICE + "ExecStart=/usr/bin/false\n"); write("x.timer", SIMPLE_TIMER)
        self.assertFalse(rv.load_task("x.timer")["full"])
        self.assertEqual(rv.delete_plan("x.timer"), ["x.timer", "x.service"])

    def test_shared_service_is_kept(self):
        write("a.service", SIMPLE_SERVICE); write("a.timer", SIMPLE_TIMER)
        write("b.timer", SIMPLE_TIMER.replace("[Timer]\n", "[Timer]\nUnit=a.service\n"))
        self.assertEqual(rv.delete_plan("a.timer"), ["a.timer"])        # b.timer still triggers a.service
        self.assertEqual(rv.delete_plan("b.timer"), ["b.timer"])        # a.service isn't b's own
        self.delete("b.timer")
        self.assertEqual(rv.delete_plan("a.timer"), ["a.timer", "a.service"])

    def test_timer_for_a_system_service_only_removes_the_timer(self):
        write("x.timer", SIMPLE_TIMER.replace("[Timer]\n", "[Timer]\nUnit=other.service\n"))
        self.assertEqual(rv.delete_plan("x.timer"), ["x.timer"])

    def test_unscheduled_service_is_deleted_alone(self):
        write("s.service", SIMPLE_SERVICE); write("t.timer", SIMPLE_TIMER)
        self.assertEqual(rv.delete_plan("s.service"), ["s.service"])
        self.delete("s.service")
        self.assertEqual(os.listdir(rv.UNITS), ["t.timer"])

    def test_symlink_is_removed_as_a_link_and_restored_as_one(self):
        real = os.path.join(TMP, "dotfiles"); os.makedirs(real, exist_ok=True)
        with open(f"{real}/s.service", "w") as f: f.write(SIMPLE_SERVICE)
        os.makedirs(rv.UNITS, exist_ok=True); os.symlink(f"{real}/s.service", f"{rv.UNITS}/s.service")
        snap = self.delete("s.service")
        self.assertFalse(os.path.lexists(f"{rv.UNITS}/s.service"))
        self.assertTrue(os.path.exists(f"{real}/s.service"))              # the target is untouched
        rv.restore_units(snap)
        self.assertTrue(os.path.islink(f"{rv.UNITS}/s.service"))
        self.assertEqual(os.readlink(f"{rv.UNITS}/s.service"), f"{real}/s.service")

    def test_undo_re_enables_only_timers_that_were_active(self):
        real = rv.unit_status
        try:
            for active in (True, False):
                rv.apply_task(task(command="true"))
                rv.unit_status = lambda unit, a=active: ("", a)
                snap = self.delete("backup.timer")
                CALLS.clear(); rv.restore_units(snap)
                self.assertEqual(("enable", "--now", "backup.timer") in CALLS, active)
                self.delete("backup.timer")
        finally:
            rv.unit_status = real

    def test_backups_and_override_folders_are_never_touched(self):
        write("x.service", SIMPLE_SERVICE); write("x.timer", SIMPLE_TIMER)
        write("x.timer.reveille-bak", SIMPLE_TIMER); os.makedirs(f"{rv.UNITS}/x.service.d")
        self.delete("x.timer")
        self.assertEqual(sorted(os.listdir(rv.UNITS)), ["x.service.d", "x.timer.reveille-bak"])

    def test_restore_does_not_overwrite_a_file_created_meanwhile(self):
        write("x.timer", SIMPLE_TIMER)
        snap = self.delete("x.timer")
        write("x.timer", "[Timer]\nOnCalendar=hourly\n")
        rv.restore_units(snap)
        self.assertIn("hourly", rv.read_text(f"{rv.UNITS}/x.timer"))

    def test_nothing_to_delete(self):
        self.assertEqual(rv.delete_plan("missing.timer"), [])


class Naming(Base):
    def test_unique_base_avoids_existing_files(self):
        self.assertEqual(rv.unique_base("Backup Photos!"), "backup-photos")
        write("backup-photos.timer", SIMPLE_TIMER)
        self.assertEqual(rv.unique_base("Backup Photos!"), "backup-photos-2")
        self.assertEqual(rv.unique_base("???"), "task")

    def test_unscheduled_services_exclude_triggered_ones(self):
        write("a.service", SIMPLE_SERVICE); write("b.service", SIMPLE_SERVICE); write("a.timer", SIMPLE_TIMER)
        self.assertEqual(rv.unscheduled_services(rv.user_timers()), ["b.service"])


class Fixes(Editable):
    """Regressions found in review."""
    def test_graphical_session_dependency_survives_a_save(self):
        svc = SIMPLE_SERVICE.replace("[Unit]\n", "[Unit]\nAfter=graphical-session.target\n")
        m = self.load(svc)
        out, _ = self.save(m, adv={**m["adv"], "online": True})
        self.assertIn("After=graphical-session.target", out)
        self.assertIn("After=network-online.target", out)

    def test_dollar_is_not_doubled_in_environment(self):
        rv.apply_task(task(adv={"env": "A=p$q B=100%"}))
        svc = read(f"{rv.UNITS}/backup.service")
        self.assertIn("A=p$q", svc); self.assertNotIn("$$q", svc)
        self.assertIn("B=100%%", svc)
        self.assertEqual(rv.load_task("backup.timer")["adv"]["env"], "'A=p$q' B=100%")

    def test_time_spans(self):
        for text, secs in (("90", 90), ("30s", 30), ("5min", 300), ("1h", 3600), ("1h 30min", 5400), ("2d", 172800)):
            self.assertEqual(rv.parse_span(text), secs, text)
        for bad in ("", "soon", "5 parsecs", "min"): self.assertIsNone(rv.parse_span(bad), bad)

    def test_randomized_delay_in_minutes_is_editable(self):
        tim = SIMPLE_TIMER.replace("[Install]", "RandomizedDelaySec=5min\n\n[Install]")
        m = self.load(SIMPLE_SERVICE, tim)
        self.assertTrue(m["full"]); self.assertEqual(m["adv"]["delay"], 300)

    def test_schedule_only_rewrite_handles_continuation_lines(self):
        tim = "[Timer]\nOnCalendar=Mon \\\n  *-*-* 03:00:00\nAccuracySec=1s\n[Install]\nWantedBy=timers.target\n"
        write("x.timer", tim)
        self.assertIsNone(rv.rewrite_timer("x.timer", {**rv.DEFAULT_TR, "hour": 5}, True, 0))
        out = rv.read_text(f"{rv.UNITS}/x.timer")
        self.assertIn("OnCalendar=*-*-* 05:00:00", out)
        self.assertNotIn("Mon", out); self.assertIn("AccuracySec=1s", out)
        self.assertEqual(rv.read_text(f"{rv.UNITS}/x.timer.reveille-bak"), tim)

    def test_write_error_is_reported_not_raised(self):
        write("x.service", SIMPLE_SERVICE); write("x.timer", SIMPLE_TIMER)
        m = rv.load_task("x.timer")
        os.chmod(rv.UNITS, 0o500)
        try:
            if os.access(rv.UNITS, os.W_OK): self.skipTest("running as root")
            t = {k: m[k] for k in ("unit", "name", "kind", "trigger", "catchup", "enabled", "adv", "service")}
            t.update(command=m["command"], app="", keep_exec=True)
            self.assertIn("Could not write", rv.apply_task(t))
        finally: os.chmod(rv.UNITS, 0o700)

    def test_write_is_atomic_and_follows_symlinks(self):
        os.makedirs(rv.UNITS, exist_ok=True)
        real = os.path.join(TMP, "real.timer")
        with open(real, "w") as f: f.write("old")
        os.symlink(real, f"{rv.UNITS}/l.timer")
        rv.write_atomic(f"{rv.UNITS}/l.timer", "new")
        self.assertTrue(os.path.islink(f"{rv.UNITS}/l.timer")); self.assertEqual(read(real), "new")
        self.assertEqual([n for n in os.listdir(rv.UNITS) if n.startswith(".reveille-")], [])

    def test_failed_delete_is_reported(self):
        write("x.service", SIMPLE_SERVICE)
        os.chmod(rv.UNITS, 0o500)
        try:
            if os.access(rv.UNITS, os.W_OK): self.skipTest("running as root")
            snap = rv.remove_units(["x.service"])
        finally: os.chmod(rv.UNITS, 0o700)
        self.assertEqual(snap["failed"], ["x.service"]); self.assertEqual(snap["items"], [])


class Proc:
    """A stand-in for subprocess.CompletedProcess."""
    def __init__(self, stdout="", stderr="", returncode=0): self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class Helpers(unittest.TestCase):
    """loginctl and journalctl, with the process runner stubbed."""
    def setUp(self):
        self.calls, self._sh, self.reply = [], rv.sh, Proc()
        def fake(*cmd, **kw): self.calls.append(cmd); return self.reply
        rv.sh = fake

    def tearDown(self): rv.sh = self._sh

    def test_linger_state(self):
        for out, want in (("Linger=yes\n", True), ("Linger=no\n", False), ("", None), ("Name=x\n", None)):
            self.reply = Proc(stdout=out); self.assertIs(rv.linger_state(), want, out)
        self.assertEqual(self.calls[-1][:2], ("loginctl", "show-user"))
        self.reply = Proc(stderr="no such user", returncode=1); self.assertIsNone(rv.linger_state())
        rv.sh = lambda *a, **k: None; self.assertIsNone(rv.linger_state())       # loginctl missing

    def test_set_linger(self):
        self.assertIsNone(rv.set_linger(True)); self.assertEqual(self.calls[-1][:2], ("loginctl", "enable-linger"))
        self.assertIsNone(rv.set_linger(False)); self.assertEqual(self.calls[-1][:2], ("loginctl", "disable-linger"))
        self.reply = Proc(stderr="Access denied\n", returncode=1); self.assertEqual(rv.set_linger(True), "Access denied")
        rv.sh = lambda *a, **k: None; self.assertEqual(rv.set_linger(True), "loginctl is not available")

    def test_read_log_returns_the_journal_text(self):
        self.reply = Proc(stdout="2026-11-09T03:00:01-0300 host x[1]: hello\n")
        self.assertEqual(rv.read_log("x.service"), ("2026-11-09T03:00:01-0300 host x[1]: hello", None))
        cmd = self.calls[-1]
        self.assertEqual(cmd[:2], ("journalctl", "--user")); self.assertIn("--unit=x.service", cmd)
        self.assertEqual(cmd[cmd.index("-n") + 1], "200")

    def test_read_log_is_safe_for_odd_unit_names(self):
        rv.read_log("-n.service")
        self.assertIn("--unit=-n.service", self.calls[-1])                      # never a loose option

    def test_empty_log_explains_itself(self):
        for out in ("", "  \n", "-- No entries --\n"):
            self.reply = Proc(stdout=out); text, err = rv.read_log("x.service")
            self.assertIsNone(err); self.assertIn("journalctl --user -u x.service", text)

    def test_log_errors_are_returned_not_raised(self):
        self.reply = Proc(stderr="Failed to open journal", returncode=1)
        self.assertEqual(rv.read_log("x.service"), ("", "Failed to open journal"))
        rv.sh = lambda *a, **k: None
        self.assertEqual(rv.read_log("x.service")[0], "")


class Gather(Base):
    """The window's data comes from one batched systemctl call per kind of unit."""
    SHOW_TIMERS = ("Id=a.timer\nActiveState=active\nUnitFileState=enabled\nNextElapseUSecRealtime=Tue 2026-11-10 03:00:00 -03\n\n"
                   "Id=b.timer\nActiveState=inactive\nUnitFileState=disabled\nNextElapseUSecRealtime=\n")
    SHOW_SERVICES = ("Id=a.service\nActiveState=inactive\nResult=success\nExecMainStatus=0\nExecMainExitTimestamp=Mon 2026-11-09 03:00:01 -03\n\n"
                     "Id=b.service\nActiveState=activating\nResult=exit-code\nExecMainStatus=3\nExecMainExitTimestamp=Mon 2026-11-09 04:00:00 -03\n")

    def setUp(self):
        super().setUp()
        self.shows, self.timer_out = [], self.SHOW_TIMERS
        def ctl(*a):
            if a[0] == "show":
                self.shows.append(a)
                out = self.timer_out if a[1].endswith(".timer") else self.SHOW_SERVICES
                return type("R", (), {"returncode": 0, "stderr": "", "stdout": out})()
            return fake_ctl(*a)
        self._old, rv.ctl = rv.ctl, ctl
        self._sh, rv.sh = rv.sh, lambda *a, **k: Proc(stdout="Linger=no\n")

    def tearDown(self): rv.ctl, rv.sh = self._old, self._sh

    def test_show_many_splits_blocks_by_unit(self):
        r = rv.show_many(["a.timer", "b.timer"], "ActiveState")
        self.assertEqual(r["a.timer"]["ActiveState"], "active"); self.assertEqual(r["b.timer"]["ActiveState"], "inactive")
        self.assertEqual(rv.show_many([], "ActiveState"), {})

    def test_gather_uses_two_show_calls_for_any_number_of_tasks(self):
        for n in "ab": write(f"{n}.service", SIMPLE_SERVICE); write(f"{n}.timer", SIMPLE_TIMER)
        write("c.service", SIMPLE_SERVICE)
        d = rv.gather()
        self.assertEqual(len(self.shows), 2)
        a, b = d["tasks"]
        self.assertEqual((a["timer"], a["enabled"], a["next"]), ("a.timer", True, "Tue 2026-11-10 03:00:00 -03"))
        self.assertEqual((a["fstate"], a["running"], b["fstate"], b["running"]), ("enabled", False, "disabled", True))
        self.assertTrue(a["next_text"]); self.assertTrue(a["last_text"])
        self.assertEqual(a["last"], {"time": "Mon 2026-11-09 03:00:01 -03", "rc": 0})
        self.assertEqual((b["enabled"], b["next"], b["last"]["rc"]), (False, "", 3))
        self.assertEqual(d["free"], ["c.service"])
        self.assertIs(d["linger"], False)

    def test_interval_timer_gets_a_next_time_from_its_monotonic_clock(self):
        write("c.service", SIMPLE_SERVICE); write("c.timer", SIMPLE_TIMER)
        self.timer_out = ("Id=c.timer\nActiveState=active\nUnitFileState=enabled\nNextElapseUSecRealtime=\n"
                          f"NextElapseUSecMonotonic={time.monotonic() + 300:.3f}s\n")
        (c,) = rv.gather()["tasks"]
        self.assertEqual(c["next_text"], "in 5 min")


class Times(unittest.TestCase):
    NOW = time.mktime((2026, 11, 9, 12, 0, 0, 0, 0, -1))

    def at(self, d, h, m=0): return time.mktime((2026, 11, d, h, m, 0, 0, 0, -1))

    def test_relative_near(self):
        n = self.NOW
        for delta, want in ((30, "in less than a minute"), (-30, "just now"), (720, "in 12 min"), (-300, "5 min ago"),
                            (2 * 3600 + 300, "in 2 h 5 min"), (3 * 3600, "in 3 h"), (-3 * 3600, "3 h ago")):
            self.assertEqual(rv.relative(n + delta, n), want, delta)

    def test_relative_days(self):
        n = self.NOW
        self.assertEqual(rv.relative(self.at(9, 19), n), "today 19:00")
        self.assertEqual(rv.relative(self.at(10, 3), n), "tomorrow 03:00")
        self.assertEqual(rv.relative(self.at(8, 3), n), "yesterday 03:00")
        self.assertEqual(rv.relative(self.at(6, 3), n), "3 days ago")
        far = self.at(20, 3)
        self.assertEqual(rv.relative(far, n), time.strftime("%a %d %b %H:%M", time.localtime(far)))

    def test_parse_ts(self):
        self.assertEqual(rv.parse_ts("Tue 2026-11-10 03:00:00 -03"), self.at(10, 3))
        self.assertEqual(rv.parse_ts("Tue 2026-11-10 03:00:00.123456 UTC"), self.at(10, 3))
        for bad in ("", "n/a", None): self.assertIsNone(rv.parse_ts(bad))

    def test_fractional_spans(self):
        self.assertEqual(rv.parse_span_f("1h 2min 3.5s"), 3723.5); self.assertEqual(rv.parse_span_f("250ms"), 0.25)
        self.assertEqual(rv.parse_span_f("0"), 0.0)
        for bad in ("", "infinity", "soon"): self.assertIsNone(rv.parse_span_f(bad), bad)

    def test_next_run_epoch(self):
        cal = {"NextElapseUSecRealtime": "Tue 2026-11-10 03:00:00 -03", "NextElapseUSecMonotonic": "1h"}
        self.assertEqual(rv.next_run_epoch(cal, 1000, 500), self.at(10, 3))               # wall-clock time wins
        self.assertEqual(rv.next_run_epoch({"NextElapseUSecMonotonic": "1h"}, 1000, 500), 1000 + 3600 - 500)
        for kv in ({}, {"NextElapseUSecMonotonic": "0"}, {"NextElapseUSecMonotonic": "infinity"}):
            self.assertIsNone(rv.next_run_epoch(kv, 1000, 500), kv)


class RowText(unittest.TestCase):
    def m(self, **kw):
        m = {"trigger": {**rv.DEFAULT_TR}, "enabled": True, "fstate": "enabled", "next": "Tue 2026-11-10 03:00:00 -03",
             "next_text": "in 5 min", "last": None, "last_text": "", "running": False}
        m.update(kw); return m

    def test_active_and_enabled(self):
        sub, tip = rv.task_texts(self.m())
        self.assertEqual(sub, "Every day at 03:00\nNext: in 5 min"); self.assertEqual(tip, "Next: Tue 2026-11-10 03:00:00 -03")

    def test_active_but_not_enabled_says_so(self):
        for st in ("disabled", "static", "transient"):
            self.assertIn("Not enabled", rv.task_texts(self.m(fstate=st))[0], st)
        self.assertNotIn("Not enabled", rv.task_texts(self.m(fstate=""))[0])             # unknown: don't guess

    def test_inactive_is_stopped_or_disabled(self):
        self.assertIn("Stopped, starts again at next login", rv.task_texts(self.m(enabled=False))[0])
        self.assertIn("Disabled", rv.task_texts(self.m(enabled=False, fstate="disabled"))[0])

    def test_running_and_failed(self):
        last = {"time": "Mon 2026-11-09 04:00:00 -03", "rc": 3}
        sub, tip = rv.task_texts(self.m(running=True, last=last, last_text="5 min ago"))
        self.assertTrue(sub.endswith("Running now · Last: 5 min ago failed (3)"))
        self.assertIn("Last: Mon 2026-11-09 04:00:00 -03", tip)

    def test_unknown_next(self):
        self.assertIn("Next: when triggered", rv.task_texts(self.m(next_text="", next=""))[0])


class SetTimer(unittest.TestCase):
    def setUp(self):
        self._ctl, self.calls = rv.ctl, []

    def tearDown(self): rv.ctl = self._ctl

    def machine(self, enable_ok=True, enable_activates=True, start_ok=True):
        state = {"active": False}
        def ctl(*a):
            self.calls.append(a[0])
            if a[0] == "show": return Proc(stdout=f"ActiveState={'active' if state['active'] else 'inactive'}\n")
            if a[0] in ("enable", "disable"):
                if not enable_ok: return Proc(stderr="no installation config", returncode=1)
                if enable_activates: state["active"] = a[0] == "enable"
                return Proc()
            if not start_ok: return Proc(stderr="boom", returncode=1)
            state["active"] = a[0] == "start"; return Proc()
        rv.ctl = ctl; return state

    def test_normal_on_and_off(self):
        st = self.machine()
        self.assertIsNone(rv.set_timer("x.timer", True)); self.assertTrue(st["active"])
        self.assertIsNone(rv.set_timer("x.timer", False)); self.assertFalse(st["active"])
        self.assertNotIn("start", self.calls); self.assertNotIn("stop", self.calls)

    def test_timer_without_install_section_falls_back_to_start_and_stop(self):
        st = self.machine(enable_ok=False)
        self.assertIsNone(rv.set_timer("x.timer", True)); self.assertTrue(st["active"])
        self.assertIsNone(rv.set_timer("x.timer", False)); self.assertFalse(st["active"])

    def test_enable_that_does_not_start_is_noticed(self):
        st = self.machine(enable_activates=False)
        self.assertIsNone(rv.set_timer("x.timer", True)); self.assertTrue(st["active"])

    def test_failure_is_reported(self):
        self.machine(enable_ok=False, start_ok=False)
        self.assertEqual(rv.set_timer("x.timer", True), "boom")


if __name__ == "__main__":
    try: unittest.main()
    finally: shutil.rmtree(TMP, ignore_errors=True)
