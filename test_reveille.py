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
                                    "online": True, "delay": 60, "retries": 0, "retry_wait": 5, "low": False, "path": "", "then": "", "fail": ""})
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
        self.assertEqual(s2["adv"], {"cwd": "/tmp", "env": "A=1", "timeout": 5, "ac": True, "online": True, "retries": 0, "retry_wait": 5, "low": False, "path": "", "then": "", "fail": ""})
        svc3, _ = self.save(m, adv={"cwd": "", "env": "", "timeout": 0, "ac": False, "online": False, "delay": 0})
        self.assertEqual(svc3, GPODDER_SERVICE)

    def test_rename_changes_both_descriptions(self):
        m = self.load(GPODDER_SERVICE, GPODDER_TIMER)
        svc, tim = self.save(m, name="Podcasts")
        self.assertIn("Description=Podcasts", svc); self.assertIn("Description=Podcasts", tim)

    def test_foreign_dependencies_and_conditions_are_kept(self):
        svc = SIMPLE_SERVICE.replace("[Service]", "After=mnt-data.mount network-online.target\nConditionFileNotEmpty=/x\n\n[Service]")
        m = self.load(svc)
        out, _ = self.save(m, adv={"cwd": "", "env": "", "timeout": 0, "ac": False, "online": False, "delay": 0})
        self.assertIn("After=mnt-data.mount network-online.target", out)
        self.assertIn("ConditionFileNotEmpty=/x", out)

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
        tr = self.parse(OnCalendar=["*-*-* 07:10:00", "Mon *-*-* 18:00:00"])[0]
        self.assertEqual((tr["type"], tr["expr"]), ("custom", "*-*-* 07:10:00 | Mon *-*-* 18:00:00"))

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


class PickList(unittest.TestCase):
    def test_listed_value_is_selected_in_place(self):
        self.assertEqual(rv.pick_list(["a", "b", "c"], "b"), (["a", "b", "c"], 1))

    def test_missing_value_is_kept_not_replaced_by_the_first_item(self):
        # an uninstalled app must not turn into the first app on save
        items, i = rv.pick_list(["a.desktop", "b.desktop"], "gone.desktop")
        self.assertEqual((items[i], len(items)), ("gone.desktop", 3))

    def test_no_current_value_selects_first(self):
        self.assertEqual(rv.pick_list(["a", "b"], None), (["a", "b"], 0))
        self.assertEqual(rv.pick_list([], None), ([], 0))

    def test_input_list_is_not_modified(self):
        src = ["a"]; rv.pick_list(src, "zzz"); self.assertEqual(src, ["a"])


class BadCalendar(unittest.TestCase):
    def setUp(self): self._sh = rv.sh
    def tearDown(self): rv.sh = self._sh

    def test_empty_is_bad(self):
        self.assertTrue(rv.bad_calendar("")); self.assertTrue(rv.bad_calendar(" | "))

    def test_every_part_is_checked(self):
        seen = []
        def fake(*a, **k):
            seen.append(a[2]); return Proc(returncode=1 if a[2] == "nonsense" else 0)
        rv.sh = fake
        self.assertFalse(rv.bad_calendar("Mon 09:00 | Fri 10:00")); self.assertEqual(seen, ["Mon 09:00", "Fri 10:00"])
        self.assertTrue(rv.bad_calendar("Mon 09:00 | nonsense"))

    def test_missing_or_slow_analyzer_does_not_crash_or_reject(self):
        rv.sh = lambda *a, **k: None
        self.assertFalse(rv.bad_calendar("Mon 09:00"))


class StartService(Base):
    def test_success_and_failure(self):
        self.assertIsNone(rv.start_service("x.service"))
        self.assertIn(("start", "--no-block", "x.service"), CALLS)
        old = rv.ctl
        rv.ctl = lambda *a: Proc(stderr="Unit x.service not found.\n", returncode=5)
        try: self.assertEqual(rv.start_service("x.service"), "Unit x.service not found.")
        finally: rv.ctl = old

    def test_start_now_still_works_with_a_task(self):
        self.assertIsNone(rv.start_now({"service": "y.service"})); self.assertIn(("start", "--no-block", "y.service"), CALLS)


class FindRunnable(unittest.TestCase):
    DATA = {"tasks": [{"unit": "nightly", "timer": "nightly.timer", "name": "Nightly Backup", "service": "nightly.service"}],
            "free": ["orphan.service"]}

    def test_matches_unit_timer_name_and_service_case_insensitively(self):
        for n in ("nightly", "NIGHTLY.timer", "nightly backup", "nightly.service"):
            self.assertEqual(rv.find_runnable(n, self.DATA), ("nightly.service", None))

    def test_services_without_a_timer(self):
        self.assertEqual(rv.find_runnable("orphan", self.DATA), ("orphan.service", None))
        self.assertEqual(rv.find_runnable("orphan.service", self.DATA), ("orphan.service", None))

    def test_unknown_name_gives_a_hint(self):
        svc, err = rv.find_runnable("nope", self.DATA)
        self.assertIsNone(svc); self.assertIn("reveille list", err)


class CommandLine(Base):
    def setUp(self):
        super().setUp(); self._gather, self._gui = rv.gather, rv.gui
        rv.gui = lambda: "gui opened"

    def tearDown(self): rv.gather, rv.gui = self._gather, self._gui

    def run_main(self, *argv):
        import contextlib, io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try: code = rv.main(list(argv))
            except SystemExit as e: code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_version_and_help_do_not_open_the_window(self):
        code, out, _ = self.run_main("--version"); self.assertEqual(code, 0); self.assertIn(rv.VERSION, out)
        code, out, _ = self.run_main("--help"); self.assertEqual(code, 0); self.assertIn("list", out)

    def test_unknown_argument_is_an_error_not_a_window(self):
        for argv in (["--bogus"], ["bogus"], ["run"]):
            code, _, err = self.run_main(*argv); self.assertEqual(code, 2); self.assertIn("usage", err)

    def test_no_arguments_opens_the_window(self):
        import sys, types
        fake = types.SimpleNamespace(require_version=lambda *a: None)
        old = sys.modules.get("gi"); sys.modules["gi"] = fake
        try: self.assertEqual(rv.main([]), "gui opened")
        finally:
            if old is None: del sys.modules["gi"]
            else: sys.modules["gi"] = old

    def test_missing_gtk_gives_a_message_not_a_traceback(self):
        import sys
        old = sys.modules.get("gi"); sys.modules["gi"] = None          # makes "import gi" raise ImportError
        try: code, _, err = self.run_main()
        finally:
            if old is None: del sys.modules["gi"]
            else: sys.modules["gi"] = old
        self.assertEqual(code, 1); self.assertIn("PyGObject", err); self.assertIn("--help", err)

    def test_list_prints_tasks_or_says_there_are_none(self):
        rv.gather = lambda: {"tasks": [], "free": []}
        self.assertEqual(self.run_main("list")[:2], (0, "No tasks\n"))
        m = {"unit": "nightly", "name": "Nightly", "trigger": {**rv.DEFAULT_TR}, "enabled": True, "fstate": "enabled",
             "next_text": "tomorrow 03:00", "next": "", "last": None, "last_text": "", "running": False,
             "timer": "nightly.timer", "service": "nightly.service"}
        rv.gather = lambda: {"tasks": [m], "free": []}
        code, out, _ = self.run_main("list")
        self.assertEqual(code, 0); self.assertIn("nightly: Nightly", out); self.assertIn("tomorrow 03:00", out)

    def test_run_starts_the_service_and_reports_unknown_names(self):
        m = {"unit": "nightly", "name": "Nightly", "timer": "nightly.timer", "service": "nightly.service"}
        rv.gather = lambda: {"tasks": [m], "free": []}
        code, out, _ = self.run_main("run", "nightly")
        self.assertEqual(code, 0); self.assertIn("Started nightly.service", out); self.assertIn(("start", "--no-block", "nightly.service"), CALLS)
        code, _, err = self.run_main("run", "nope"); self.assertEqual(code, 1); self.assertIn("No task or service", err)

    def test_run_reports_a_failed_start(self):
        rv.gather = lambda: {"tasks": [], "free": ["x.service"]}
        old = rv.ctl; rv.ctl = lambda *a: Proc(stderr="denied", returncode=1)
        try: code, _, err = self.run_main("run", "x")
        finally: rv.ctl = old
        self.assertEqual(code, 1); self.assertIn("denied", err)


def adv(**kw):
    return {"cwd": "", "env": "", "timeout": 0, "ac": False, "online": False, "delay": 0, **kw}


class Reliability(Base):
    """Retry on failure, low priority, a path condition and "then run", written to and read back from units."""

    def roundtrip(self, **kw):
        t = task(adv=adv(**kw)); self.assertIsNone(rv.apply_task(t))
        return rv.load_task(f"{t['unit']}.timer"), read(f"{rv.UNITS}/{t['unit']}.service")

    def test_retry_window_covers_every_try(self):
        self.assertEqual(rv.retry_window(3, 5), 4 * (5 + 60) * 60 + 60)          # a run is assumed to take an hour
        self.assertEqual(rv.retry_window(2, 10, 20), 3 * (10 + 20) * 60 + 60)    # a timeout bounds a run
        self.assertGreater(rv.retry_window(1, 1), 2 * 60)

    def test_retry_is_written_as_restart_on_failure_with_a_matching_limit(self):
        m, svc = self.roundtrip(retries=3, retry_wait=10, timeout=20)
        for line in ("Restart=on-failure", "RestartSec=10min", "StartLimitBurst=4",
                     f"StartLimitIntervalSec={rv.retry_window(3, 10, 20)}", "TimeoutStartSec=20min"):
            self.assertIn(line, svc)
        self.assertTrue(m["full"]); self.assertEqual((m["adv"]["retries"], m["adv"]["retry_wait"]), (3, 10))

    def test_no_retries_writes_nothing(self):
        m, svc = self.roundtrip(retries=0, retry_wait=7)
        for key in ("Restart", "StartLimit", "Nice", "IOScheduling", "OnSuccess", "ConditionPath"): self.assertNotIn(key, svc)
        self.assertEqual(m["adv"]["retries"], 0)

    def test_turning_retries_off_removes_the_lines(self):
        t = task(adv=adv(retries=2)); rv.apply_task(t)
        rv.apply_task({**t, "old_name": t["name"], "keep_exec": True, "adv": adv(retries=0)})
        svc = read(f"{rv.UNITS}/{t['unit']}.service")
        for key in ("Restart", "StartLimit"): self.assertNotIn(key, svc)

    def test_low_priority_round_trip(self):
        m, svc = self.roundtrip(low=True)
        self.assertIn("Nice=19", svc); self.assertIn("IOSchedulingClass=idle", svc); self.assertTrue(m["adv"]["low"])
        self.assertFalse(self.roundtrip(low=False)[0]["adv"]["low"])

    def test_a_foreign_nice_value_survives_unless_low_priority_is_on(self):
        svc = SIMPLE_SERVICE + "Nice=5\nIOSchedulingClass=best-effort\n"
        write("x.service", svc); write("x.timer", SIMPLE_TIMER)
        m = rv.load_task("x.timer"); self.assertTrue(m["full"]); self.assertFalse(m["adv"]["low"])
        base = {"name": "x", "kind": "command", "command": "/usr/bin/true", "trigger": rv.DEFAULT_TR, "service": "x.service",
                "unit": "x", "old_name": "x", "keep_exec": True}
        out, _ = rv.unit_texts({**base, "adv": adv(low=False)}, svc, SIMPLE_TIMER)
        self.assertIn("Nice=5", out); self.assertIn("IOSchedulingClass=best-effort", out)
        out, _ = rv.unit_texts({**base, "adv": adv(low=True)}, svc, SIMPLE_TIMER)
        self.assertNotIn("Nice=5", out); self.assertEqual(out.count("Nice="), 1); self.assertIn("Nice=19", out)

    def test_path_condition_round_trip_including_inversion_and_percent(self):
        for path in ("/mnt/data", "!/tmp/skip", "/srv/100%"):
            m, svc = self.roundtrip(path=path)
            self.assertEqual(m["adv"]["path"], path)
        self.assertIn("ConditionPathExists=/srv/100%%", svc)            # % is escaped in the file

    def test_then_run_round_trip_and_clearing(self):
        m, svc = self.roundtrip(then="upload.service")
        self.assertIn("OnSuccess=upload.service", svc); self.assertEqual(m["adv"]["then"], "upload.service")
        self.assertEqual(self.roundtrip(then="")[0]["adv"]["then"], "")

    def test_everything_together_and_other_lines_survive(self):
        t = task(adv=adv(retries=1, retry_wait=2, low=True, path="/x", then="b.service", ac=True))
        rv.apply_task(t)
        path = f"{rv.UNITS}/{t['unit']}.service"
        with open(path, "a") as f: f.write("")
        text = read(path).replace("[Unit]\n", "[Unit]\nSuccessAction=none\n")
        write(f"{t['unit']}.service", text)
        rv.apply_task({**t, "old_name": t["name"], "keep_exec": True})
        out = read(path); self.assertIn("SuccessAction=none", out)
        m = rv.load_task(f"{t['unit']}.timer")
        self.assertEqual((m["adv"]["retries"], m["adv"]["low"], m["adv"]["path"], m["adv"]["then"], m["adv"]["ac"]),
                         (1, True, "/x", "b.service", True))


class Representable(Base):
    def why(self, extra_unit="", extra_service=""):
        text = (f"[Unit]\nDescription=x\n{extra_unit}\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n{extra_service}")
        write("x.service", text); return rv.parse_service("x.service").get("why", "")

    def test_what_the_editor_cannot_show_limits_the_task(self):
        self.assertIn("Restart=", self.why(extra_service="Restart=always\n"))
        self.assertIn("StartLimitBurst", self.why(extra_service="Restart=on-failure\nRestartSec=5min\n"))
        self.assertIn("StartLimitBurst", self.why("StartLimitBurst=99\n", "Restart=on-failure\nRestartSec=5min\n"))
        self.assertIn("RestartSec", self.why("StartLimitBurst=3\n", "Restart=on-failure\nRestartSec=30s\n"))
        self.assertIn("RestartSec", self.why("StartLimitBurst=3\n", "Restart=on-failure\n"))
        self.assertIn("ConditionPathExists", self.why("ConditionPathExists=/a\nConditionPathExists=/b\n"))
        self.assertIn("OnSuccess", self.why("OnSuccess=a.service b.service\n"))
        self.assertIn("OnSuccess", self.why("OnSuccess=a.service\nOnSuccess=b.service\n"))

    def test_what_it_can_show_is_not_limited(self):
        self.assertEqual(self.why(extra_service="Restart=no\nNice=10\n"), "")
        self.assertEqual(self.why("StartLimitBurst=4\n", "Restart=on-failure\nRestartSec=15min\n"), "")
        self.assertEqual(self.why("OnSuccess=a.service\nConditionPathExists=!/skip\n"), "")

    def test_burst_maps_to_retries(self):
        write("x.service", "[Unit]\nStartLimitBurst=4\n[Service]\nExecStart=/usr/bin/true\nRestart=on-failure\nRestartSec=15min\n")
        a = rv.parse_service("x.service")["adv"]; self.assertEqual((a["retries"], a["retry_wait"]), (3, 15))


class ThenCycle(Base):
    def link(self, name, then=""):
        write(name, "[Unit]\n" + (f"OnSuccess={then}\n" if then else "") + "[Service]\nExecStart=/usr/bin/true\n")

    def test_a_task_cannot_run_itself(self):
        self.assertTrue(rv.then_cycle("a.service", "a.service"))

    def test_loops_of_any_length_are_found(self):
        self.link("b.service", "a.service"); self.assertTrue(rv.then_cycle("a.service", "b.service"))
        self.link("c.service", "b.service"); self.assertTrue(rv.then_cycle("a.service", "c.service"))

    def test_a_chain_without_a_loop_is_fine(self):
        self.link("b.service", "c.service"); self.link("c.service")
        self.assertFalse(rv.then_cycle("a.service", "b.service"))

    def test_an_existing_loop_elsewhere_does_not_hang(self):
        self.link("b.service", "c.service"); self.link("c.service", "b.service")
        self.assertFalse(rv.then_cycle("a.service", "b.service"))

    def test_unreadable_or_empty_targets(self):
        self.assertFalse(rv.then_cycle("a.service", "missing.service")); self.assertFalse(rv.then_cycle("a.service", ""))


class SystemdVersion(unittest.TestCase):
    def setUp(self): self._sh = rv.sh; rv._CACHE.clear()
    def tearDown(self): rv.sh = self._sh; rv._CACHE.clear()

    def test_parsed_and_asked_only_once(self):
        calls = []
        rv.sh = lambda *a, **k: calls.append(a) or Proc(stdout="systemd 255 (255.4-1ubuntu8)\n+PAM +AUDIT\n")
        self.assertEqual(rv.systemd_version(), 255); self.assertEqual(rv.systemd_version(), 255); self.assertEqual(len(calls), 1)

    def test_unknown_when_it_cannot_be_asked(self):
        rv.sh = lambda *a, **k: None; self.assertIsNone(rv.systemd_version())
        rv._CACHE.clear(); rv.sh = lambda *a, **k: Proc(stdout="garbage"); self.assertIsNone(rv.systemd_version())


class RowText(unittest.TestCase):
    M = {"trigger": {**rv.DEFAULT_TR}, "enabled": True, "fstate": "enabled", "next_text": "tomorrow 03:00", "next": "",
         "last": {"time": "x", "rc": 1}, "last_text": "5 min ago", "running": False}

    def test_waiting_to_retry_is_shown_instead_of_running(self):
        sub, _ = rv.task_texts({**self.M, "retrying": True, "running": False})
        self.assertIn("Waiting to retry", sub); self.assertNotIn("Running now", sub)
        sub, _ = rv.task_texts({**self.M, "retrying": False, "running": True}); self.assertIn("Running now", sub)

    def test_rows_without_the_flag_still_work(self):
        self.assertIn("failed (1)", rv.task_texts(self.M)[0])


class FollowLogTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self._path = os.environ["PATH"]
        os.environ["PATH"] = self.dir + os.pathsep + self._path
    def tearDown(self):
        os.environ["PATH"] = self._path; shutil.rmtree(self.dir, ignore_errors=True)

    def fake_journalctl(self, body):
        path = os.path.join(self.dir, "journalctl")
        with open(path, "w") as f: f.write("#!/bin/sh\n" + body)
        os.chmod(path, 0o755)

    def wait_for(self, got, n, timeout=5):
        end = time.time() + timeout
        while len(got) < n and time.time() < end: time.sleep(0.02)

    def test_lines_arrive_as_they_are_written_and_stop_ends_the_follow(self):
        self.fake_journalctl('echo "$@"\necho "-- No entries --"\necho one\necho two\nexec sleep 30\n')
        got = []; f = rv.FollowLog("x.service", got.append, lines=50)
        self.assertIsNone(f.start()); self.wait_for(got, 3)
        self.assertEqual(got[1:], ["one", "two"])                        # "-- ..." status lines are dropped
        for arg in ("--user", "--unit=x.service", "-f", "-n", "50"): self.assertIn(arg, got[0].split())
        f.stop(); end = time.time() + 5
        while f.proc.poll() is None and time.time() < end: time.sleep(0.02)
        self.assertIsNotNone(f.proc.poll())                              # the process was ended, not left running

    def test_nothing_is_delivered_after_stop(self):
        self.fake_journalctl("trap '' TERM\necho first\nsleep 0.3\necho late\n")      # keeps running after stop()
        got = []; f = rv.FollowLog("x.service", got.append)
        f.start(); self.wait_for(got, 1); f.stop(); time.sleep(0.6)
        self.assertEqual(got, ["first"])

    def test_missing_journalctl_is_an_error_text_not_a_crash(self):
        os.environ["PATH"] = self.dir                                    # an empty folder: no journalctl anywhere
        self.assertEqual(rv.FollowLog("x.service", lambda l: None).start(), "journalctl is not available")


class LoginDelay(Editable):
    """"At login" keeps the delay it was written with."""
    def tim(self, line): return "[Timer]\n" + line + "\n[Install]\nWantedBy=timers.target\n"

    def test_the_delay_is_read(self):
        for text, secs in (("45s", 45), ("10s", 10), ("2min", 120), ("0", 0), ("1h 30min", 5400)):
            tr = rv.parse_schedule({"OnStartupSec": [text]})[0]
            self.assertEqual((tr["type"], tr["login_sec"]), ("login", secs), text)
        self.assertIsNone(rv.parse_schedule({"OnStartupSec": ["soon"]}))
        self.assertIsNone(rv.parse_schedule({"OnStartupSec": ["1500ms"]}))          # not whole seconds: don't round it

    def test_saving_keeps_the_original_value(self):
        m = self.load(SIMPLE_SERVICE, self.tim("OnStartupSec=45s"))
        self.assertEqual(m["trigger"]["login_sec"], 45)
        _, tim = self.save(m)
        self.assertIn("OnStartupSec=45s", tim); self.assertNotIn("10s", tim)

    def test_a_longer_delay_keeps_its_meaning(self):
        m = self.load(SIMPLE_SERVICE, self.tim("OnStartupSec=5min"))
        _, tim = self.save(m)
        self.assertIn("OnStartupSec=5min", tim)

    def test_a_new_login_task_gets_ten_seconds(self):
        rv.apply_task(task(trigger={**rv.DEFAULT_TR, "type": "login"}))
        self.assertIn("OnStartupSec=10s", read(f"{rv.UNITS}/backup.timer"))

    def test_describe_says_so_only_when_it_is_not_the_default(self):
        self.assertEqual(rv.describe({**rv.DEFAULT_TR, "type": "login"}), "At login")
        self.assertEqual(rv.describe({**rv.DEFAULT_TR, "type": "login", "login_sec": 300}), "At login, after 5 min")


class CatchUp(Base):
    def test_only_calendar_schedules_have_missed_runs(self):
        for tp in ("interval", "login"):
            self.assertNotIn(tp, rv.CALENDAR_TYPES)
            self.assertNotIn("Persistent=true", rv.timer_lines({**rv.DEFAULT_TR, "type": tp}, True, 0))
        for tp in ("daily", "weekdays", "weekly", "monthly", "lastday", "times", "custom"):
            self.assertIn(tp, rv.CALENDAR_TYPES)
            tr = {**rv.DEFAULT_TR, "type": tp, "expr": "Mon 09:00"}
            self.assertIn("Persistent=true", rv.timer_lines(tr, True, 0), tp)
            self.assertNotIn("Persistent=true", rv.timer_lines(tr, False, 0), tp)

    def test_every_trigger_the_editor_offers_is_known(self):
        self.assertEqual(len(rv.TRIGGERS), len(rv.TRIGGER_IDS))
        self.assertEqual(set(rv.TRIGGER_IDS) - {"interval", "login"}, rv.CALENDAR_TYPES)


class DropIns(Editable):
    """NAME.service.d/*.conf can change what the editor shows; it must say so instead of showing a stale value."""
    def dropin(self, unit, text, name="override.conf"):
        os.makedirs(f"{rv.UNITS}/{unit}.d", exist_ok=True); write(f"{unit}.d/{name}", text)

    def test_no_drop_ins_no_note(self):
        m = self.load(SIMPLE_SERVICE); self.assertEqual(m["dropins"], []); self.assertTrue(m["full"])

    def test_an_override_of_the_command_limits_the_task_and_names_the_file(self):
        write("x.service", SIMPLE_SERVICE); write("x.timer", SIMPLE_TIMER)
        self.dropin("x.service", "[Service]\nExecStart=\nExecStart=/usr/bin/false\n")
        m = rv.load_task("x.timer")
        self.assertFalse(m["full"]); self.assertIsNotNone(m["trigger"])             # the schedule is still editable
        self.assertIn("x.service.d/override.conf", m["why"]); self.assertIn("ExecStart=", m["why"])
        self.assertEqual(m["dropins"], ["x.service.d/override.conf"])

    def test_every_managed_service_setting_counts(self):
        for sect, key in (("Service", "Environment=A=1"), ("Service", "TimeoutStartSec=5min"), ("Service", "Nice=5"),
                          ("Unit", "ConditionPathExists=/x"), ("Unit", "OnSuccess=a.service"),
                          ("Unit", "OnFailure=a.service"), ("Unit", "Wants=network-online.target")):
            shutil.rmtree(f"{rv.UNITS}/x.service.d", ignore_errors=True)
            write("x.service", SIMPLE_SERVICE); write("x.timer", SIMPLE_TIMER)
            self.dropin("x.service", f"[{sect}]\n{key}\n")
            self.assertFalse(rv.load_task("x.timer")["full"], key)

    def test_unrelated_overrides_only_get_a_note(self):
        write("x.service", SIMPLE_SERVICE); write("x.timer", SIMPLE_TIMER)
        self.dropin("x.service", "[Service]\nMemoryMax=1G\n[Unit]\nAfter=graphical-session.target\n")
        m = rv.load_task("x.timer")
        self.assertTrue(m["full"]); self.assertEqual(m["dropins"], ["x.service.d/override.conf"])

    def test_a_timer_drop_in_that_changes_the_schedule_hides_it(self):
        write("x.service", SIMPLE_SERVICE); write("x.timer", SIMPLE_TIMER)
        self.dropin("x.timer", "[Timer]\nOnCalendar=\nOnCalendar=hourly\n")
        m = rv.load_task("x.timer")
        self.assertIsNone(m["trigger"]); self.assertFalse(m["full"]); self.assertIn("x.timer.d/override.conf", m["why"])

    def test_a_timer_drop_in_about_something_else_is_fine(self):
        write("x.service", SIMPLE_SERVICE); write("x.timer", SIMPLE_TIMER)
        self.dropin("x.timer", "[Timer]\nAccuracySec=1h\n")
        m = rv.load_task("x.timer"); self.assertTrue(m["full"]); self.assertEqual(m["dropins"], ["x.timer.d/override.conf"])

    def test_only_conf_files_count_and_saving_leaves_them_alone(self):
        write("x.service", SIMPLE_SERVICE); write("x.timer", SIMPLE_TIMER)
        self.dropin("x.service", "[Service]\nMemoryMax=1G\n"); self.dropin("x.service", "ignored", "notes.txt")
        m = rv.load_task("x.timer"); self.assertEqual(m["dropins"], ["x.service.d/override.conf"])
        self.save(m, trigger={**WEEKLY})
        self.assertEqual(read(f"{rv.UNITS}/x.service.d/override.conf"), "[Service]\nMemoryMax=1G\n")

    def test_a_task_for_an_existing_service_ignores_that_services_drop_ins(self):
        write("x.timer", SIMPLE_TIMER.replace("[Timer]\n", "[Timer]\nUnit=other.service\n"))
        self.dropin("other.service", "[Service]\nExecStart=/bin/false\n")
        self.assertTrue(rv.load_task("x.timer")["full"])


class ServiceList(Base):
    def test_the_refresh_does_not_list_services(self):
        calls = []
        old = rv.list_services; rv.list_services = lambda: calls.append(1) or []
        old_sh = rv.sh; rv.sh = lambda *a, **k: Proc(stdout="Linger=no\n")
        try:
            write("a.service", SIMPLE_SERVICE); write("a.timer", SIMPLE_TIMER)
            d = rv.gather()
        finally: rv.list_services, rv.sh = old, old_sh
        self.assertEqual(calls, []); self.assertNotIn("services", d); self.assertEqual(len(d["tasks"]), 1)


class FailureHandler(Base):
    """"If it fails, run": OnFailure=, with the same loop check as "Then run"."""
    def roundtrip(self, **kw):
        t = task(adv=adv(**kw)); self.assertIsNone(rv.apply_task(t))
        return rv.load_task(f"{t['unit']}.timer"), read(f"{rv.UNITS}/{t['unit']}.service")

    def test_round_trip_and_clearing(self):
        m, svc = self.roundtrip(fail="notify.service")
        self.assertIn("OnFailure=notify.service", svc); self.assertEqual(m["adv"]["fail"], "notify.service")
        self.assertTrue(m["full"])
        m2, svc2 = self.roundtrip(fail="")
        self.assertNotIn("OnFailure", svc2); self.assertEqual(m2["adv"]["fail"], "")

    def test_both_handlers_can_be_set(self):
        m, svc = self.roundtrip(then="a.service", fail="b.service")
        self.assertEqual((m["adv"]["then"], m["adv"]["fail"]), ("a.service", "b.service"))

    def test_a_template_instance_is_kept_as_written(self):
        m, svc = self.roundtrip(fail="notify@%n.service")        # %n is meant: it is not escaped like other text
        self.assertIn("OnFailure=notify@%n.service", svc); self.assertEqual(m["adv"]["fail"], "notify@%n.service")

    def test_several_handlers_cannot_be_shown(self):
        write("x.service", SIMPLE_SERVICE.replace("[Service]", "OnFailure=a.service b.service\n[Service]"))
        self.assertIn("OnFailure", rv.parse_service("x.service")["why"])

    def test_the_loop_check_follows_failure_links_and_mixed_ones(self):
        def link(name, key="", target=""):
            write(name, "[Unit]\n" + (f"{key}={target}\n" if key else "") + "[Service]\nExecStart=/usr/bin/true\n")
        link("b.service", "OnFailure", "a.service"); self.assertTrue(rv.then_cycle("a.service", "b.service"))
        link("b.service", "OnSuccess", "c.service"); link("c.service", "OnFailure", "a.service")
        self.assertTrue(rv.then_cycle("a.service", "b.service"))
        link("c.service"); self.assertFalse(rv.then_cycle("a.service", "b.service"))

    def test_drop_in_failure_handler_is_noticed(self):
        write("x.service", SIMPLE_SERVICE); write("x.timer", SIMPLE_TIMER)
        os.makedirs(f"{rv.UNITS}/x.service.d"); write("x.service.d/o.conf", "[Unit]\nOnFailure=n.service\n")
        self.assertIn("OnFailure=", rv.load_task("x.timer")["why"])


class Intervals(Base):
    def parse(self, **kv):
        return rv.parse_schedule({k: v if isinstance(v, list) else [v] for k, v in kv.items()})

    def trig(self, **kv):
        r = self.parse(**kv); return r and (r[0]["type"], r[0]["every"], r[0]["unit"])

    def test_every_unit_is_read(self):
        self.assertEqual(self.trig(OnUnitActiveSec="30s"), ("interval", 30, "s"))
        self.assertEqual(self.trig(OnUnitActiveSec="15min"), ("interval", 15, "min"))
        self.assertEqual(self.trig(OnUnitActiveSec="2h"), ("interval", 2, "h"))
        self.assertEqual(self.trig(OnUnitActiveSec="3d"), ("interval", 3, "d"))

    def test_compound_and_odd_spellings_are_read_not_locked(self):
        self.assertEqual(self.trig(OnUnitActiveSec="1h 30min"), ("interval", 90, "min"))
        self.assertEqual(self.trig(OnUnitActiveSec="1h30min"), ("interval", 90, "min"))
        self.assertEqual(self.trig(OnUnitActiveSec="90"), ("interval", 90, "s"))
        self.assertEqual(self.trig(OnUnitActiveSec="1.5h"), ("interval", 90, "min"))
        self.assertEqual(self.trig(OnUnitActiveSec="24h"), ("interval", 1, "d"))
        self.assertEqual(self.trig(OnStartupSec="1h 30min", OnUnitActiveSec="90min"), ("interval", 90, "min"))

    def test_what_cannot_be_shown_stays_unedited(self):
        self.assertIsNone(self.parse(OnUnitActiveSec="0"))
        self.assertIsNone(self.parse(OnUnitActiveSec="500ms"))
        self.assertIsNone(self.parse(OnUnitActiveSec="soon"))
        self.assertIsNone(self.parse(OnUnitActiveSec="30min", OnStartupSec="5min"))       # a different first run
        self.assertIsNone(self.parse(OnUnitActiveSec=f"{rv.MAX_EVERY + 1}s"))              # longer than the box holds
        self.assertIsNone(self.parse(OnUnitActiveSec=["5min", "10min"]))

    def test_written_in_the_shortest_exact_form(self):
        for every, unit, text in ((30, "s", "30s"), (90, "s", "90s"), (120, "s", "2min"), (90, "min", "90min"),
                                  (120, "min", "2h"), (36, "h", "36h"), (48, "h", "2d"), (1, "d", "1d")):
            lines = rv.timer_lines({**rv.DEFAULT_TR, "type": "interval", "every": every, "unit": unit}, True, 0)
            self.assertEqual(lines[:2], [f"OnStartupSec={text}", f"OnUnitActiveSec={text}"], (every, unit))

    def test_every_value_survives_a_round_trip(self):
        for every, unit in ((10, "s"), (45, "s"), (90, "s"), (5, "min"), (90, "min"), (6, "h"), (36, "h"), (2, "d")):
            tr = {**rv.DEFAULT_TR, "type": "interval", "every": every, "unit": unit}
            kv = {}
            for l in rv.timer_lines(tr, True, 0): k, v = l.split("=", 1); kv.setdefault(k, []).append(v)
            back = rv.parse_schedule(kv)[0]
            self.assertEqual(rv.interval_seconds(back), rv.interval_seconds(tr), (every, unit))

    def test_sub_minute_intervals_ask_for_matching_accuracy(self):
        sec = rv.timer_lines({**rv.DEFAULT_TR, "type": "interval", "every": 20, "unit": "s"}, True, 0)
        self.assertIn("AccuracySec=1s", sec)
        self.assertIn("AccuracySec=1s", rv.timer_lines({**rv.DEFAULT_TR, "type": "interval", "every": 90, "unit": "s"}, True, 0))
        for every, unit in ((1, "min"), (30, "min"), (3, "h")):                    # unchanged for what already worked
            self.assertNotIn("AccuracySec=1s", rv.timer_lines({**rv.DEFAULT_TR, "type": "interval", "every": every, "unit": unit}, True, 0))

    def test_accuracy_is_replaced_for_seconds_and_a_users_own_value_is_kept_otherwise(self):
        timer = "[Timer]\nOnCalendar=daily\nAccuracySec=5min\n[Install]\nWantedBy=timers.target\n"
        write("x.timer", timer)
        self.assertIsNone(rv.rewrite_timer("x.timer", {**rv.DEFAULT_TR, "hour": 5}, True, 0))
        self.assertIn("AccuracySec=5min", read(f"{rv.UNITS}/x.timer"))
        self.assertIsNone(rv.rewrite_timer("x.timer", {**rv.DEFAULT_TR, "type": "interval", "every": 30, "unit": "s"}, True, 0))
        out = read(f"{rv.UNITS}/x.timer")
        self.assertEqual(out.count("AccuracySec="), 1); self.assertIn("AccuracySec=1s", out)

    def test_an_empty_interval_is_refused_before_anything_is_written(self):
        write("x.timer", SIMPLE_TIMER)
        with self.assertRaises(ValueError):
            rv.rewrite_timer("x.timer", {**rv.DEFAULT_TR, "type": "interval", "every": 0, "unit": "s"}, True, 0)
        self.assertEqual(read(f"{rv.UNITS}/x.timer"), SIMPLE_TIMER)
        self.assertFalse(os.path.exists(f"{rv.UNITS}/x.timer.reveille-bak"))

    def test_a_task_with_a_one_and_a_half_hour_timer_is_editable(self):
        write("x.service", SIMPLE_SERVICE)
        write("x.timer", "[Timer]\nOnStartupSec=1h 30min\nOnUnitActiveSec=1h 30min\n[Install]\nWantedBy=timers.target\n")
        m = rv.load_task("x.timer")
        self.assertTrue(m["full"]); self.assertEqual((m["trigger"]["every"], m["trigger"]["unit"]), (90, "min"))


class Presets(Base):
    def parse(self, *cals, **kv):
        kv = {k: [v] for k, v in kv.items()}; kv["OnCalendar"] = list(cals); return rv.parse_schedule(kv)[0]

    def test_weekdays(self):
        for expr in ("Mon,Tue,Wed,Thu,Fri *-*-* 09:00:00", "Mon..Fri *-*-* 09:00:00", "Mon..Fri 09:00", "Mon..Wed,Thu,Fri 9:00"):
            tr = self.parse(expr); self.assertEqual((tr["type"], tr["hour"], tr["minute"]), ("weekdays", 9, 0), expr)
        tr = {**rv.DEFAULT_TR, "type": "weekdays", "hour": 9}
        self.assertEqual(rv.on_calendar(tr), "Mon,Tue,Wed,Thu,Fri *-*-* 09:00:00")
        self.assertEqual(rv.timer_lines(tr, False, 0), ["OnCalendar=Mon,Tue,Wed,Thu,Fri *-*-* 09:00:00"])

    def test_weekly_ranges_and_other_day_sets(self):
        self.assertEqual(self.parse("Sat,Sun *-*-* 10:00:00")["days"], ["Sat", "Sun"])
        self.assertEqual(self.parse("Mon..Wed,Sat *-*-* 10:00:00")["days"], ["Mon", "Tue", "Wed", "Sat"])
        self.assertEqual(self.parse("Fri..Mon *-*-* 10:00:00")["type"], "custom")      # a wrapping range: leave it alone
        self.assertEqual(self.parse("Mon *-*-* 08,12:00:00")["type"], "custom")        # days and several hours at once

    def test_several_times_a_day(self):
        tr = {**rv.DEFAULT_TR, "type": "times", "times": ["08:00", "12:30", "18:00"]}
        self.assertEqual(rv.timer_lines(tr, True, 0), ["OnCalendar=*-*-* 08:00:00", "OnCalendar=*-*-* 12:30:00",
                                                       "OnCalendar=*-*-* 18:00:00", "Persistent=true"])
        back = self.parse("*-*-* 08:00:00", "*-*-* 12:30:00", "*-*-* 18:00:00")
        self.assertEqual((back["type"], back["times"]), ("times", ["08:00", "12:30", "18:00"]))

    def test_a_single_line_with_several_hours_is_read_too(self):
        tr = self.parse("*-*-* 08,12,18:00:00")
        self.assertEqual((tr["type"], tr["times"]), ("times", ["08:00", "12:00", "18:00"]))
        self.assertEqual(self.parse("*-*-* 8:00")["type"], "daily")
        self.assertEqual(self.parse("*-*-* 25:00:00")["type"], "custom")

    def test_repeated_times_collapse(self):
        tr = self.parse("*-*-* 08:00:00", "*-*-* 08:00:00"); self.assertEqual((tr["type"], tr["hour"]), ("daily", 8))

    def test_time_entry(self):
        self.assertEqual(rv.parse_times("18:00, 8:05 12:30"), ["08:05", "12:30", "18:00"])
        self.assertEqual(rv.parse_times("08:00;08:00"), ["08:00"])
        for bad in ("", "  ", "8", "24:00", "12:60", "08:00, noon", "8:5"): self.assertIsNone(rv.parse_times(bad), bad)

    def test_last_day_of_the_month(self):
        for expr in ("*-*~01 03:00:00", "*-*~1 03:00"):
            tr = self.parse(expr); self.assertEqual((tr["type"], tr["hour"]), ("lastday", 3), expr)
        self.assertEqual(rv.on_calendar({**rv.DEFAULT_TR, "type": "lastday", "hour": 23, "minute": 30}), "*-*~01 23:30:00")
        self.assertEqual(self.parse("*-*~02 03:00:00")["type"], "custom")                 # the second to last day is not this preset

    def test_the_new_expressions_are_valid_for_systemd(self):
        if rv.sh("systemd-analyze", "--version") is None: self.skipTest("no systemd-analyze")
        for tp in ("weekdays", "lastday", "times"):
            tr = {**rv.DEFAULT_TR, "type": tp}
            for part in rv.calendar_parts(rv.on_calendar(tr)):
                r = rv.sh("systemd-analyze", "calendar", part, timeout=5)
                self.assertEqual(r.returncode, 0, part)

    def test_every_preset_survives_a_save_and_load(self):
        for tr in ({**rv.DEFAULT_TR, "type": "weekdays", "hour": 6, "minute": 15},
                   {**rv.DEFAULT_TR, "type": "times", "times": ["07:00", "19:45"]},
                   {**rv.DEFAULT_TR, "type": "lastday", "hour": 22, "minute": 5}):
            shutil.rmtree(f"{TMP}/systemd", ignore_errors=True)
            t = task(trigger=tr); self.assertIsNone(rv.apply_task(t))
            back = rv.load_task(f"{t['unit']}.timer")["trigger"]
            self.assertEqual(back["type"], tr["type"])
            self.assertEqual(rv.on_calendar(back), rv.on_calendar(tr))

    def test_an_empty_schedule_is_refused_not_turned_into_a_login_timer(self):
        for tr in ({**rv.DEFAULT_TR, "type": "times", "times": []}, {**rv.DEFAULT_TR, "type": "custom", "expr": " "}):
            with self.assertRaises(ValueError): rv.timer_lines(tr, True, 0)
        with self.assertRaises(ValueError): rv.apply_task(task(trigger={**rv.DEFAULT_TR, "type": "times", "times": []}))
        self.assertFalse(os.path.exists(f"{rv.UNITS}/backup.timer"))


class RowWording(unittest.TestCase):
    def d(self, **kw): return rv.describe({**rv.DEFAULT_TR, **kw})

    def test_days(self):
        self.assertEqual(self.d(type="daily", hour=9), "Every day at 09:00")
        self.assertEqual(self.d(type="weekdays", hour=9), "Weekdays at 09:00")
        self.assertEqual(self.d(type="weekly", days=rv.WEEKDAYS, hour=9), "Weekdays at 09:00")
        self.assertEqual(self.d(type="weekly", days=["Sat", "Sun"], hour=9), "Weekends at 09:00")
        self.assertEqual(self.d(type="weekly", days=rv.DAYS, hour=9), "Every day at 09:00")
        self.assertEqual(self.d(type="weekly", days=["Mon", "Thu"], hour=9, minute=30), "Mon, Thu at 09:30")

    def test_months(self):
        self.assertEqual(self.d(type="monthly", dom=1), "On the 1st of every month at 03:00")
        self.assertEqual([rv.ordinal(n) for n in (2, 3, 4, 11, 12, 13, 21, 22, 28)],
                         ["2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "28th"])
        self.assertEqual(self.d(type="lastday", hour=23), "Last day of every month at 23:00")

    def test_several_times(self):
        self.assertEqual(self.d(type="times", times=["08:00", "12:30"]), "Every day at 08:00, 12:30")

    def test_intervals(self):
        for every, unit, text in ((1, "min", "Every minute"), (30, "min", "Every 30 minutes"), (1, "h", "Every hour"),
                                  (2, "h", "Every 2 hours"), (45, "s", "Every 45 seconds"), (1, "s", "Every second"),
                                  (1, "d", "Every day"), (3, "d", "Every 3 days")):
            self.assertEqual(self.d(type="interval", every=every, unit=unit), text)

    def test_a_trigger_from_an_older_version_still_reads(self):
        self.assertEqual(rv.describe({"type": "interval", "every": 2, "unit": "h"}), "Every 2 hours")
        self.assertEqual(rv.describe({"type": "login"}), "At login")

    def test_preview_text_for_interval_and_login(self):
        self.assertEqual(rv.next_elapse({**rv.DEFAULT_TR, "type": "interval", "every": 90, "unit": "min"}),
                         "First run 90 min after login, then repeats")
        self.assertEqual(rv.next_elapse({**rv.DEFAULT_TR, "type": "interval", "every": 2, "unit": "d"}),
                         "First run 2 days after login, then repeats")
        self.assertEqual(rv.next_elapse({**rv.DEFAULT_TR, "type": "login"}), "Shortly after you log in")
        self.assertEqual(rv.next_elapse({**rv.DEFAULT_TR, "type": "login", "login_sec": 300}), "5 min after you log in")


if __name__ == "__main__":
    try: unittest.main()
    finally: shutil.rmtree(TMP, ignore_errors=True)
