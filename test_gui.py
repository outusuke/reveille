#!/usr/bin/env python3
"""Smoke test of the GTK window: starts the real app, opens the editor and checks the wake-from-sleep switch.
Needs PyGObject, GTK 4, libadwaita 1.5+ and a display (xvfb-run is enough); skipped when any is missing.
systemctl is stubbed and units go to a temporary XDG_CONFIG_HOME.   Run: xvfb-run -a python3 -m unittest test_gui"""
import importlib.machinery, importlib.util, os, sys, tempfile, unittest

try:
    import gi
    gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk
    HAVE_GUI = Gtk.init_check() and hasattr(Adw.ApplicationWindow, "get_visible_dialog")
except (ImportError, ValueError):
    HAVE_GUI = False

TMP = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = TMP
os.environ.setdefault("GTK_A11Y", "none")
HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("rv_gui", os.path.join(HERE, "reveille"))
_spec = importlib.util.spec_from_loader("rv_gui", _loader)
rv = importlib.util.module_from_spec(_spec)
_loader.exec_module(rv)


def walk(widget):
    """Every widget below `widget`, depth first."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from walk(child)
        child = child.get_next_sibling()


def row(dialog, title):
    return next(w for w in walk(dialog) if isinstance(w, Adw.PreferencesRow) and w.get_title() == title)


@unittest.skipUnless(HAVE_GUI, "needs PyGObject, GTK 4, libadwaita 1.5 and a display")
class WakeSwitch(unittest.TestCase):
    def test_editor_shows_saves_and_greys_out_the_switch(self):
        rv.ctl = lambda *a: type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        rv.list_services = lambda: []
        base = {"name": "Alarm", "kind": "command", "command": "/bin/true", "trigger": {**rv.DEFAULT_TR},
                "catchup": True, "enabled": True, "adv": {"wake": True}, "unit": "alarm"}
        self.assertIsNone(rv.apply_task(base))               # a real unit file, written before the app starts
        saved = []
        rv.apply_task = lambda t: saved.append(t)
        rv.linger_state = lambda: True                       # no banner
        env = {"wake": True, "sd": 255}                      # what gather() reports about this session
        rv.wake_alarm_capable = lambda: env["wake"]
        rv.systemd_version = lambda: env["sd"]
        TITLE = "Wake the computer from sleep"
        errors, steps = [], []

        def editor(win):
            dlg = win.get_visible_dialog()
            return dlg if dlg is not None and hasattr(dlg, "wake") else None

        def closed(win):
            """True once no dialog is open. A dialog is closed for good on each look: close() is animated, can
            be ignored while the dialog is still opening, and Xvfb has no frame clock to finish it."""
            dlg = win.get_visible_dialog()
            if dlg is not None: dlg.force_close()
            return win.get_visible_dialog() is None

        def script():
            """One step per tick of the main loop: open an editor, look at it, press Save, repeat."""
            app = Gio.Application.get_default()
            win = app.props.active_window
            yield lambda: "alarm.timer" in win.cur
            win.edit(win.cur["alarm.timer"])                 # 1. an existing task that wakes the computer
            yield lambda: editor(win)
            dlg = editor(win)
            sw = row(dlg, TITLE)
            self.assertIs(sw, dlg.wake); self.assertTrue(sw.get_active()); self.assertTrue(sw.get_sensitive())
            sw.set_active(False)
            dlg.save()
            yield lambda: saved and closed(win)
            self.assertIs(saved[-1]["adv"]["wake"], False)
            win.edit(None)                                   # 2. a new task: off by default, on when switched on
            yield lambda: editor(win)
            dlg = editor(win)
            self.assertFalse(dlg.wake.get_active())
            dlg.name.set_text("Morning"); dlg.cmd.set_text("/bin/true"); dlg.kind.set_selected(1)
            dlg.wake.set_active(True)
            dlg.save()
            yield lambda: len(saved) == 2 and closed(win)
            self.assertEqual((saved[-1]["name"], saved[-1]["adv"]["wake"]), ("Morning", True))
            yield lambda: not win.busy and not win.again     # no refresh in flight that could land after the change
            env.update(wake=False)                           # 3. a session without CAP_WAKE_ALARM: greyed out
            win.wake_ok = False                              # (the next refresh reads the same from gather)
            win.edit(win.cur["alarm.timer"])
            yield lambda: editor(win)
            dlg = editor(win)
            self.assertFalse(dlg.wake.get_sensitive()); self.assertIn("CAP_WAKE_ALARM", dlg.wake.get_subtitle())
            yield lambda: closed(win)
            yield lambda: not win.busy and not win.again
            env.update(wake=True, sd=249)                    # 4. too old a systemd: greyed out with its own reason
            win.wake_ok, win.sdver = True, 249
            win.edit(win.cur["alarm.timer"])
            yield lambda: editor(win)
            dlg = editor(win)
            self.assertFalse(dlg.wake.get_sensitive()); self.assertIn("254", dlg.wake.get_subtitle())

        gen, waiting, ticks = script(), [None], [0]

        def tick():
            ticks[0] += 1
            app = Gio.Application.get_default()
            try:
                if ticks[0] > 300: raise TimeoutError(f"the window did not get past step {len(steps)}")
                if app is None or app.props.active_window is None: return True
                if waiting[0] is not None and not waiting[0](): return True
                steps.append(1)
                waiting[0] = next(gen)
            except StopIteration:
                app.quit(); return False
            except BaseException as e:                       # a failed assertion must end the app, then fail the test
                errors.append(e); app.quit(); return False
            return True

        GLib.timeout_add(100, tick)
        rv.gui()
        if errors: raise errors[0]
        self.assertGreaterEqual(len(steps), 9)


if __name__ == "__main__":
    unittest.main()
