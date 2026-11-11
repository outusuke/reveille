#: layer 11: the GTK4/libadwaita window (one function; its classes close over its imports)
# ---------------------------------------------------------------- GUI
def gui():
    import gi
    gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk

    def icon_btn(icon, tip, cb, css=None):
        b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER)
        b.add_css_class("flat")
        if css: b.add_css_class(css)
        b.connect("clicked", lambda *_: cb())
        return b

    class Editor(Adw.Dialog):
        def __init__(self, win, m=None, preset=None):
            super().__init__(title="Edit task" if m else ("Schedule service" if preset else "New task"), content_width=520, content_height=680)
            self.win, self.m, self._pv_src = win, m, 0
            self.full = m is None or m["full"]            # a hand-written unit only has its schedule editable
            t = m or {"kind": "app", "enabled": True, "catchup": True,
                      "trigger": {"type": "daily", "hour": 3, "minute": 0, "days": ["Mon"], "dom": 1,
                                  "every": 30, "unit": "min"}}
            if preset: t = dict(t, kind="service", service=preset, name=preset[:-8] if preset.endswith(".service") else preset)
            tr = {**DEFAULT_TR, **t["trigger"]}
            self.apps = sorted((a for a in Gio.AppInfo.get_all() if a.should_show()),
                               key=lambda a: a.get_name().lower())

            page = Adw.PreferencesPage()
            why = (m or {}).get("why", "")
            note = Adw.PreferencesGroup(title="Only the schedule can be edited",
                                        description=GLib.markup_escape_text(f"Because {why}.") if why else "")
            note.set_visible(not self.full and bool(why)); page.add(note)
            drop = (m or {}).get("dropins") or []
            if drop and self.full:                         # not restricted, but worth knowing about
                page.add(Adw.PreferencesGroup(
                    title="Drop-in overrides",
                    description=GLib.markup_escape_text(
                        "systemd also applies these files. The editor doesn't read or change them:\n" + "\n".join(drop))))
            g = Adw.PreferencesGroup(title="General"); page.add(g)
            self.name = Adw.EntryRow(title="Name", text=t.get("name", "")); g.add(self.name)
            self.own_groups = [g]                          # hidden when only the schedule is editable

            g = Adw.PreferencesGroup(title="What to run"); page.add(g)
            self.own_groups.append(g)
            self.kind = Adw.ComboRow(title="Run", model=Gtk.StringList.new(["Application", "Command", "Service"]),
                                     selected=["app", "command", "service"].index(t["kind"]))
            g.add(self.kind)
            names = {a.get_id(): a.get_name() for a in self.apps}
            # an app that is no longer listed stays selectable, so saving a schedule change can't swap it
            self.app_ids, sel = pick_list([a.get_id() for a in self.apps], t.get("app") if t["kind"] == "app" else None)
            self.app = Adw.ComboRow(title="Application", enable_search=True,
                                    model=Gtk.StringList.new([names.get(i, f"{i} (not installed)") for i in self.app_ids]))
            self.app.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
            self.app.set_selected(sel)
            g.add(self.app)
            found = win.services                           # fetched by Win.edit just before this editor opened
            self.services, sel = pick_list(found, t.get("service") if t["kind"] == "service" else None)
            self.svc = Adw.ComboRow(title="Service", subtitle=f"{len(found)} user services found",
                                    enable_search=True, model=Gtk.StringList.new(self.services))
            self.svc.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
            self.svc.set_selected(sel)
            for row in (self.app, self.svc):
                def tip(r, *_):
                    it = r.get_selected_item()
                    r.set_tooltip_text(it.get_string() if it else None)
                row.connect("notify::selected", tip); tip(row)
            self.cmd = Adw.EntryRow(title="Command (use sh -c \"…\" for pipes)", text=t.get("command", ""))
            g.add(self.cmd)

            g = Adw.PreferencesGroup(title="When"); page.add(g)
            self.trig = Adw.ComboRow(title="Repeat", model=Gtk.StringList.new(TRIGGERS),
                                     selected=TRIGGER_IDS.index(tr["type"]))
            g.add(self.trig)
            self.hour = Adw.SpinRow.new_with_range(0, 23, 1); self.hour.set_title("Hour"); self.hour.set_value(tr["hour"])
            self.minute = Adw.SpinRow.new_with_range(0, 59, 1); self.minute.set_title("Minute"); self.minute.set_value(tr["minute"])
            self.dom = Adw.SpinRow.new_with_range(1, 28, 1); self.dom.set_title("Day of month"); self.dom.set_value(tr["dom"])
            self.every = Adw.SpinRow.new_with_range(1, MAX_EVERY, 1); self.every.set_title("Every"); self.every.set_value(tr["every"])
            self.unit = Adw.ComboRow(title="Unit", model=Gtk.StringList.new([EVERY_NAMES[u][1] for u in INTERVAL_UNITS]),
                                     selected=list(INTERVAL_UNITS).index(tr["unit"]) if tr["unit"] in INTERVAL_UNITS else 1)
            self.login_sec = tr["login_sec"]               # not editable here, but a hand-set delay must survive a save
            self.first_key = tr.get("first_key")           # likewise the key (OnBootSec=) a hand-written timer used
            self.first = Adw.EntryRow(title="First run after login (optional, e.g. 2min; empty = same as Every)",
                                      text="" if tr.get("first_sec") is None else fmt_span(tr["first_sec"]))
            self.first.connect("changed", self.refresh)
            self.times = Adw.EntryRow(title="Times (e.g. 08:00, 12:30, 18:00)", text=", ".join(tr["times"]))
            self.times.connect("changed", self.refresh)
            self.days_row = Adw.ActionRow(title="Days")
            box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER); self.day_btns = {}
            for d in DAYS:
                b = Gtk.ToggleButton(label=d[:2], active=d in tr["days"]); b.connect("toggled", self.refresh)
                self.day_btns[d] = b; box.append(b)
            self.days_row.add_suffix(box)
            self.expr = Adw.EntryRow(title="Calendar expression (e.g. Mon..Fri 09:00; separate several with |)", text=tr["expr"])
            self.expr.connect("changed", self.refresh)
            self.when = [self.hour, self.minute, self.days_row, self.dom, self.times, self.every, self.unit, self.first, self.expr]
            for r in self.when: g.add(r)
            self.preview = Adw.ActionRow(title="Next run", subtitle_selectable=True)
            self.preview.add_css_class("property"); g.add(self.preview)

            g = Adw.PreferencesGroup(title="Options"); page.add(g)
            self.opts = g
            self.catchup = Adw.SwitchRow(title="Run missed tasks after startup",
                                         subtitle="If the computer was off at the scheduled time",
                                         active=t.get("catchup", True))
            g.add(self.catchup)
            self.enabled = Adw.SwitchRow(title="Run on schedule", subtitle="Turn off to pause this task without deleting it",
                                       active=t.get("enabled", True)); g.add(self.enabled)

            adv = t.get("adv", {})
            g = Adw.PreferencesGroup(title="Advanced"); page.add(g)
            self.cwd = Adw.EntryRow(title="Working directory", text=adv.get("cwd", ""))
            self.env = Adw.EntryRow(title="Environment (KEY=value KEY2=\"a b\")", text=adv.get("env", ""))
            self.timeout = Adw.SpinRow.new_with_range(0, 1440, 1)
            self.timeout.set_title("Stop after (minutes)"); self.timeout.set_subtitle("0 means never"); self.timeout.set_value(adv.get("timeout", 0))
            self.ac = Adw.SwitchRow(title="Only on AC power", active=adv.get("ac", False))
            self.online = Adw.SwitchRow(title="Wait for the network", active=adv.get("online", False))
            self.delay = Adw.SpinRow.new_with_range(0, 86400, 10)
            self.delay.set_title("Random delay (seconds)"); self.delay.set_subtitle("Spreads runs out so many tasks don't start at once")
            self.delay.set_value(adv.get("delay", 0))
            sd = win.sdver                                  # systemd's version, to grey out what it can't do
            self.retries = Adw.SpinRow.new_with_range(0, 10, 1); self.retries.set_title("Retry on failure")
            self.retries.set_subtitle("How many times to try again; 0 means never"); self.retries.set_value(adv.get("retries", 0))
            self.retry_wait = Adw.SpinRow.new_with_range(1, 1440, 1); self.retry_wait.set_title("Wait between tries (minutes)")
            self.retry_wait.set_value(adv.get("retry_wait", 5))
            self.low = Adw.SwitchRow(title="Run at low priority", active=adv.get("low", False),
                                     subtitle="Lowest CPU and disk priority, so it doesn't slow down your work")
            self.path = Adw.EntryRow(title="Only if this path exists (start with ! to require it missing)",
                                     text=adv.get("path", ""))
            others = [x for x in found if x != (m or {}).get("service")]
            def picker(title, subtitle, cur):              # "None" plus the services; a current value that isn't listed stays
                items, sel = pick_list(others, cur)
                row = Adw.ComboRow(title=title, subtitle=subtitle, enable_search=True,
                                   model=Gtk.StringList.new(["None"] + items))
                row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
                row.set_selected(sel + 1 if cur else 0)
                return row, [""] + items
            self.then, self.then_opts = picker("Then run", "A service to start after this one succeeds", adv.get("then", ""))
            self.fail, self.fail_opts = picker("If it fails, run",
                                               "A service to start when this one fails (after the last retry, if any)",
                                               adv.get("fail", ""))
            if sd is not None and sd < 244:
                self.retries.set_sensitive(False); self.retries.set_subtitle(f"Needs systemd 244 or newer (this is {sd})")
            if sd is not None and sd < 249:
                self.then.set_sensitive(False); self.then.set_subtitle(f"Needs systemd 249 or newer (this is {sd})")
            self.own_only = [self.cwd, self.env, self.timeout, self.ac, self.online, self.retries, self.retry_wait,
                             self.low, self.path, self.then, self.fail]   # don't apply to an existing service
            for r in self.own_only + [self.delay]: g.add(r)

            # Delete lives inside the item: a task's timer, or a service without a timer opened via its row
            self.target = m["timer"] if m else (preset if preset and delete_plan(preset) else None)
            if self.target:
                g = Adw.PreferencesGroup(); page.add(g)
                db = Gtk.Button(label="Delete task" if m else "Delete service", halign=Gtk.Align.CENTER)
                db.add_css_class("destructive-action")
                db.connect("clicked", lambda *_: self.delete()); g.add(db)

            hb = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
            cancel = Gtk.Button(label="Cancel"); cancel.connect("clicked", lambda *_: self.close()); hb.pack_start(cancel)
            save = Gtk.Button(label="Save"); save.add_css_class("suggested-action")
            save.connect("clicked", lambda *_: self.save()); hb.pack_end(save)
            tv = Adw.ToolbarView(content=page); tv.add_top_bar(hb)
            self.set_child(tv)

            for w in (self.kind, self.trig, self.unit, self.svc):
                w.connect("notify::selected", self.refresh)
            for w in (self.hour, self.minute, self.dom, self.every, self.retries):
                w.connect("notify::value", self.refresh)
            self.refresh()

        def trigger(self):
            tp = TRIGGER_IDS[self.trig.get_selected()]
            return {"type": tp, "expr": self.expr.get_text().strip(), "hour": int(self.hour.get_value()), "minute": int(self.minute.get_value()),
                    "days": [d for d, b in self.day_btns.items() if b.get_active()],
                    "dom": int(self.dom.get_value()), "every": int(self.every.get_value()),
                    "unit": list(INTERVAL_UNITS)[self.unit.get_selected()],
                    "times": parse_times(self.times.get_text()) or [], "login_sec": self.login_sec,
                    "first_sec": self.first_span()[1], "first_key": self.first_key}

        def first_span(self):
            """(valid, seconds or None) for the "First run" box: empty means the same as the interval."""
            text = self.first.get_text().strip()
            if not text: return True, None
            secs = exact_span(text)
            return secs is not None, secs

        def refresh(self, *_):
            k = self.kind.get_selected()
            self.app.set_visible(k == 0); self.cmd.set_visible(k == 1); self.svc.set_visible(k == 2)
            for r in self.own_only: r.set_visible(k != 2)
            self.retry_wait.set_visible(k != 2 and self.retries.get_value() > 0)
            if not self.full:                              # only the schedule of a hand-written timer is editable
                for r in (self.name, self.kind, self.app, self.cmd, self.svc, self.enabled, *self.own_only, *self.own_groups):
                    r.set_visible(False)
            tp = TRIGGER_IDS[self.trig.get_selected()]
            clock = tp in ("daily", "weekdays", "weekly", "monthly", "lastday")
            show = {self.hour: clock, self.minute: clock, self.days_row: tp == "weekly", self.dom: tp == "monthly",
                    self.times: tp == "times", self.every: tp == "interval", self.unit: tp == "interval", self.first: tp == "interval",
                    self.expr: tp == "custom"}
            for w, v in show.items(): w.set_visible(v)
            # "Run missed tasks" only means something for a calendar schedule: an interval or a login has no missed time
            self.catchup.set_visible(tp in CALENDAR_TYPES)
            self.opts.set_visible(self.catchup.get_visible() or self.enabled.get_visible())
            tr = self.trigger()
            if tp == "weekly" and not tr["days"]:
                self.preview.set_subtitle("Pick at least one day")
            elif tp == "times" and not tr["times"]:
                self.preview.set_subtitle("Enter times like 08:00, 12:30")
            else:                                          # systemd-analyze runs off the main thread, after a pause
                if self._pv_src: GLib.source_remove(self._pv_src)
                self._pv_src = GLib.timeout_add(250, self.run_preview, tr)

        def run_preview(self, tr):
            self._pv_src = 0
            def work(): GLib.idle_add(self.show_preview, tr, next_elapse(tr))
            threading.Thread(target=work, daemon=True).start()
            return False

        def show_preview(self, tr, text):
            if tr == self.trigger(): self.preview.set_subtitle(text)      # drop answers for an older input
            return False

        def save(self):
            name, tr = self.name.get_text().strip(), self.trigger()
            if tr["type"] == "custom" and not calendar_parts(tr["expr"]):
                return self.win.toast("That is not a valid calendar expression")
            if tr["type"] == "weekly" and not tr["days"]: return self.win.toast("Pick at least one day")
            if tr["type"] == "interval" and not self.first_span()[0]:
                return self.win.toast("First run: use a time like 2min, 90s or 1h")
            if tr["type"] == "times" and not tr["times"]: return self.win.toast("Enter times like 08:00, 12:30")
            if not self.full:
                timer, catchup, delay = self.m["timer"], self.catchup.get_active(), int(self.delay.get_value())
                return self.run_save("sched", tr, lambda: rewrite_timer(timer, tr, catchup, delay))
            k = self.kind.get_selected()
            if not name: return self.win.toast("Give the task a name")
            try:
                shlex.split(self.env.get_text())
            except ValueError:
                return self.win.toast("The environment field has an unclosed quote")
            t = {"name": name, "kind": ["app", "command", "service"][k], "trigger": tr,
                 "catchup": self.catchup.get_active(), "enabled": self.enabled.get_active(),
                 "adv": {"cwd": self.cwd.get_text().strip(), "env": self.env.get_text().strip(),
                         "timeout": int(self.timeout.get_value()), "ac": self.ac.get_active(),
                         "online": self.online.get_active(), "delay": int(self.delay.get_value()),
                         "retries": int(self.retries.get_value()), "retry_wait": int(self.retry_wait.get_value()),
                         "low": self.low.get_active(), "path": self.path.get_text().strip(),
                         "then": self.then_opts[self.then.get_selected()],
                         "fail": self.fail_opts[self.fail.get_selected()]}}
            if k == 0:
                if not self.app_ids: return self.win.toast("No applications found")
                t["app"] = self.app_ids[self.app.get_selected()]
            elif k == 2:
                if not self.services: return self.win.toast("No user services found")
                t["service"] = self.services[self.svc.get_selected()]
            else:
                t["command"] = self.cmd.get_text().strip()
            adv = t["adv"]
            if k != 2 and adv["retries"] and tr["type"] == "interval":      # a retry window longer than the interval
                window = retry_window(adv["retries"], adv["retry_wait"], adv["timeout"])
                if interval_seconds(tr) <= window:
                    return self.win.toast(f"Retries need a schedule longer than about {window // 60} min")
            if self.m:                              # editing in place: leave untouched what the user didn't change
                t["old_name"] = self.m["name"]
                same = (k == 0 and t.get("app") == self.m.get("app")) or (k == 1 and t.get("command") == self.m.get("command"))
                t["keep_exec"] = same and ["app", "command", "service"][k] == self.m["kind"]
            def job():                              # systemctl and unit-name lookups run off the main thread
                t["unit"] = self.m["unit"] if self.m else unique_base(name)
                if k != 2 and any(t["adv"][x] and then_cycle(t["unit"] + ".service", t["adv"][x]) for x in ("then", "fail")):
                    raise ValueError("That would make tasks run each other in a loop")
                return apply_task(t)
            self.run_save("task", tr, job)

        def run_save(self, kind, tr, job):
            """Validate a custom schedule, then run `job` (which talks to systemd) in a thread, so the window
            never freezes. `kind` is "sched" (schedule-only rewrite) or "task" (full write)."""
            self.set_sensitive(False)
            def work():
                try:
                    if tr["type"] == "custom" and bad_calendar(tr["expr"]): res = ("invalid", None)
                    else: res = (kind, job())
                except ValueError as e:
                    res = ("error", str(e))
                except Exception as e:                  # never leave the dialog stuck insensitive
                    res = ("error", f"Unexpected error: {e}")
                GLib.idle_add(self.saved, res)
            threading.Thread(target=work, daemon=True).start()

        def saved(self, res):
            self.set_sensitive(True)
            kind, val = res
            if kind == "invalid": self.win.toast("That is not a valid calendar expression")
            elif kind == "error": self.win.toast(val[:120])
            elif kind == "sched":
                self.close(); self.win.fill()
                self.win.toast(f"Could not save: {val}" if val else "Schedule updated")
            elif val and val.startswith("Could not write"): self.win.toast(val[:120])      # nothing was saved
            else:
                self.close(); self.win.fill()
                self.win.toast(f"Saved, but systemd said: {val[:80]}" if val else "Task saved")
            return False

        def delete(self):
            self.close(); self.win.ask_delete(self.target)

    class RawView(Adw.Dialog):
        """For a timer whose schedule the editor can't show: its file, plus the ways out (open it, delete it)."""
        def __init__(self, win, m):
            super().__init__(title=m["name"], content_width=560, content_height=560)
            page = Adw.PreferencesPage()
            why = m.get("why")
            page.add(Adw.PreferencesGroup(
                title="Only the file can be edited",
                description=GLib.markup_escape_text(
                    (f"Because {why}, the editor can't show this schedule" if why else
                     "This timer uses schedule options the editor can't show")
                    + ", so reveille leaves it alone. You can open the file in your editor, or delete the task.")))
            g = Adw.PreferencesGroup(title=GLib.markup_escape_text(m["timer"])); page.add(g)
            tv = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                              top_margin=8, bottom_margin=8, left_margin=8, right_margin=8)
            tv.get_buffer().set_text(read_text(unit_path(m["timer"])))
            sw = Gtk.ScrolledWindow(child=tv, min_content_height=220); sw.add_css_class("card"); g.add(sw)
            g = Adw.PreferencesGroup(); page.add(g)
            box = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
            ob = Gtk.Button(label="Open file")
            ob.connect("clicked", lambda *_: Gio.AppInfo.launch_default_for_uri(
                GLib.filename_to_uri(unit_path(m["timer"])), None))
            db = Gtk.Button(label="Delete task"); db.add_css_class("destructive-action")
            db.connect("clicked", lambda *_: (self.close(), win.ask_delete(m["timer"])))
            box.append(ob); box.append(db); g.add(box)
            hb = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
            close = Gtk.Button(label="Close"); close.connect("clicked", lambda *_: self.close()); hb.pack_start(close)
            tv_ = Adw.ToolbarView(content=page); tv_.add_top_bar(hb); self.set_child(tv_)

    class LogView(Adw.Dialog):
        """The tail of a service's journal, read in a thread so opening it never blocks the window.
        Follow shows new lines as they arrive (journalctl -f)."""
        MAX_LINES = 2000

        def __init__(self, service, follow=False):
            super().__init__(title=f"Log: {service}", content_width=720, content_height=560)
            self.service, self.follower, self.waiting = service, None, False
            self._pending, self._lock, self._flushing = [], threading.Lock(), False
            self.text = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                     wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                                     left_margin=10, right_margin=10)
            self.scroll = Gtk.ScrolledWindow(child=self.text, vexpand=True)
            hb = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
            close = Gtk.Button(label="Close"); close.connect("clicked", lambda *_: self.close()); hb.pack_start(close)
            hb.pack_end(icon_btn("view-refresh-symbolic", "Reload", self.reload))
            hb.pack_end(icon_btn("edit-copy-symbolic", "Copy the log", self.copy))
            self.follow_btn = Gtk.ToggleButton(label="Follow", tooltip_text="Show new lines as they arrive",
                                               valign=Gtk.Align.CENTER)
            self.follow_btn.connect("toggled", lambda b: self.set_follow(b.get_active()))
            hb.pack_end(self.follow_btn)
            tv = Adw.ToolbarView(content=self.scroll); tv.add_top_bar(hb); self.set_child(tv)
            self.connect("closed", lambda *_: self.stop_follow())
            if follow: self.follow_btn.set_active(True)
            else: self.load()

        def reload(self):
            if self.follower: self.start_follow()
            else: self.load()

        def load(self):
            self.text.get_buffer().set_text("Loading…")
            def work():
                text, err = read_log(self.service)
                GLib.idle_add(self.show, err or text)
            threading.Thread(target=work, daemon=True).start()

        def show(self, text):
            if self.follower: return False                 # following took over while this was loading
            self.text.get_buffer().set_text(text)
            GLib.timeout_add(100, self.to_end)             # after layout, so the newest lines are in view
            return False

        def set_follow(self, on):
            self.stop_follow()
            if on: self.start_follow()

        def start_follow(self):
            self.stop_follow()
            with self._lock: self._pending, self._flushing = [], False
            self.waiting = True
            self.text.get_buffer().set_text("Waiting for output…")
            f = FollowLog(self.service, self.on_line)
            err = f.start()
            if err:
                self.waiting = False; self.text.get_buffer().set_text(err); self.follow_btn.set_active(False)
            else:
                self.follower = f

        def stop_follow(self):
            if self.follower: self.follower.stop(); self.follower = None

        def on_line(self, line):                           # called from the reader thread
            with self._lock:
                self._pending.append(line)
                if self._flushing: return
                self._flushing = True
            GLib.idle_add(self.flush)

        def flush(self):
            with self._lock:
                lines, self._pending, self._flushing = self._pending, [], False
            if self.follower is None or not lines: return False
            buf, adj = self.text.get_buffer(), self.scroll.get_vadjustment()
            at_end = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 24     # only follow if already there
            if self.waiting: buf.set_text(""); self.waiting = False
            buf.insert(buf.get_end_iter(), "\n".join(lines) + "\n")
            extra = buf.get_line_count() - self.MAX_LINES
            if extra > 0:                                  # keep the buffer from growing without end
                res = buf.get_iter_at_line(extra); it = res[1] if isinstance(res, tuple) else res
                buf.delete(buf.get_start_iter(), it)
            if at_end: GLib.timeout_add(50, self.to_end)
            return False

        def to_end(self):
            adj = self.scroll.get_vadjustment(); adj.set_value(adj.get_upper() - adj.get_page_size())
            return False

        def copy(self):
            buf = self.text.get_buffer()
            self.get_clipboard().set_text(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False))

    class ImportCron(Adw.Dialog):
        """Review the entries of a crontab and turn the chosen ones into tasks. The crontab itself is never changed."""
        def __init__(self, win, plan):
            super().__init__(title="Import from crontab", content_width=560, content_height=680)
            self.win, self.plan, self.checks = win, plan, []
            page = Adw.PreferencesPage()
            notes = ["Your crontab is not changed: remove the lines you import yourself, or the jobs run twice."] + cron_notes(plan)
            page.add(Adw.PreferencesGroup(description=GLib.markup_escape_text("\n".join(notes))))
            g = Adw.PreferencesGroup(title="Entries"); page.add(g)
            for it in plan:
                title, sub = cron_row_texts(it)
                row = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(sub))
                ok = it["status"] == "new"                 # only a new entry can be chosen
                chk = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=ok, sensitive=ok)
                chk.connect("toggled", self.refresh)
                row.add_prefix(chk); row.set_activatable_widget(chk)
                self.checks.append(chk); g.add(row)
            g = Adw.PreferencesGroup(); page.add(g)
            self.on = Adw.SwitchRow(title="Switch the new timers on", active=False,
                                    subtitle="Leave this off until the cron lines are gone. Every task has its own switch in the list.")
            g.add(self.on)
            hb = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
            cancel = Gtk.Button(label="Cancel"); cancel.connect("clicked", lambda *_: self.close()); hb.pack_start(cancel)
            self.btn = Gtk.Button(label="Import"); self.btn.add_css_class("suggested-action")
            self.btn.connect("clicked", lambda *_: self.go()); hb.pack_end(self.btn)
            tv = Adw.ToolbarView(content=page); tv.add_top_bar(hb)
            self.set_child(tv)
            self.refresh()

        def chosen(self):
            return [it for it, c in zip(self.plan, self.checks) if it["status"] == "new" and c.get_active()]

        def refresh(self, *_):
            n = len(self.chosen())
            self.btn.set_label(f"Import {n}" if n else "Import"); self.btn.set_sensitive(n > 0)

        def go(self):
            chosen, enabled = self.chosen(), self.on.get_active()
            if not chosen: return
            self.set_sensitive(False)
            self.win.bg(lambda: import_crontab(chosen, enabled=enabled), lambda res: self.done(res, enabled))

        def done(self, res, enabled):
            self.set_sensitive(True)
            if isinstance(res, Exception): return self.win.toast(f"Could not import: {res}"[:120])
            self.close(); self.win.fill()
            self.win.toast(import_summary(res, enabled)[:140])

    class Win(Adw.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="Task Scheduler", default_width=640, default_height=560)
            self.overlay = Adw.ToastOverlay()
            tv = Adw.ToolbarView(); hb = Adw.HeaderBar()
            add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New task")
            add.connect("clicked", lambda *_: self.edit(None)); hb.pack_start(add)
            self.menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Main menu")
            hb.pack_end(self.menu_btn)
            self.linger, self.linger_dismissed = None, False
            for name, fn in (("install-menu", self.do_install), ("remove-menu", self.do_remove),
                             ("linger-on", lambda: self.do_linger(True)), ("linger-off", lambda: self.do_linger(False)),
                             ("import-cron", self.import_cron)):
                a = Gio.SimpleAction.new(name, None); a.connect("activate", lambda *_a, fn=fn: fn()); self.add_action(a)
            self.update_menu()
            tv.add_top_bar(hb)
            self.banner = Adw.Banner(title="Tasks only run while you're logged in", button_label="Learn more")
            self.banner.connect("button-clicked", lambda *_: self.explain_linger()); tv.add_top_bar(self.banner)
            self.stack = Gtk.Stack()
            empty = Adw.StatusPage(icon_name="alarm-symbolic", title="No tasks yet",
                                   description="Schedule an app or a command to run automatically.")
            first = Gtk.Button(label="Create task", halign=Gtk.Align.CENTER)
            first.add_css_class("suggested-action"); first.add_css_class("pill")
            first.connect("clicked", lambda *_: self.edit(None)); empty.set_child(first)
            self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE); self.list.add_css_class("boxed-list")
            self.free_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE); self.free_list.add_css_class("boxed-list")
            self.h1 = Gtk.Label(label="Scheduled", xalign=0); self.h1.add_css_class("heading")
            self.h2 = Gtk.Label(label="Services without a schedule", xalign=0); self.h2.add_css_class("heading")
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            for w in (self.h1, self.list, self.h2, self.free_list): body.append(w)
            clamp = Adw.Clamp(maximum_size=640, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
                              child=body)
            self.stack.add_named(Gtk.Spinner(spinning=True, width_request=32, height_request=32,
                                             halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER), "loading")
            self.stack.add_named(empty, "empty"); self.stack.add_named(Gtk.ScrolledWindow(child=clamp), "list")
            tv.set_content(self.stack); self.overlay.set_child(tv); self.set_content(self.overlay)
            self.services, self.busy, self.again, self.shape, self.has_tasks = [], False, False, None, False
            self.opening = self.importing = False
            self.sdver = None
            self.cur, self.rows, self.syncing = {}, {}, False
            self.stack.set_visible_child_name("loading")
            self.fill()
            GLib.timeout_add_seconds(30, lambda: (self.fill(), True)[1])

        def update_menu(self):
            m = Gio.Menu()
            m.append("Import from crontab…", "win.import-cron")
            if menu_installed(): m.append("Remove from app menu", "win.remove-menu")
            else: m.append("Add to app menu", "win.install-menu")
            if self.linger is True: m.append("Don't run tasks while logged out", "win.linger-off")
            elif self.linger is False: m.append("Run tasks while logged out", "win.linger-on")
            self.menu_btn.set_menu_model(m)

        def explain_linger(self):
            d = Adw.AlertDialog(
                heading="Run tasks while you're logged out?",
                body="Your tasks run inside your user session, so they wait when you are logged out, and after a "
                     "restart until you log in. Turning on \"lingering\" keeps your session running from boot, so "
                     "timers keep firing. Tasks set to \"At login\" will then run at boot instead, and apps need a "
                     "desktop session, so only commands gain from this.")
            d.add_response("later", "Not now"); d.add_response("enable", "Turn on")
            d.set_response_appearance("enable", Adw.ResponseAppearance.SUGGESTED)
            d.set_close_response("later"); d.set_default_response("enable")
            d.connect("response", lambda _d, r: self.do_linger(True) if r == "enable"
                      else setattr(self, "linger_dismissed", True) or self.show_banner())
            d.present(self)

        def do_linger(self, on):
            def work():
                err = set_linger(on)
                GLib.idle_add(self.linger_done, on, err)
            threading.Thread(target=work, daemon=True).start()

        def linger_done(self, on, err):
            self.toast(f"Could not change it: {err[:100]}" if err else
                       ("Tasks will keep running while you're logged out" if on else "Tasks now stop when you log out"))
            self.fill()
            return False

        def show_banner(self):
            self.banner.set_revealed(self.linger is False and self.has_tasks
                                     and not self.linger_dismissed)

        def do_install(self):
            err = install_menu()
            self.update_menu(); self.fill()
            self.toast(f"Could not add it: {err}" if err else "Added to the app menu")

        def do_remove(self):
            uninstall_menu(); self.update_menu(); self.fill()
            self.toast("Removed from the app menu")

        def toast(self, msg, button=None, cb=None):
            t = Adw.Toast(title=msg, timeout=5)
            if button:
                t.set_button_label(button); t.connect("button-clicked", lambda *_: cb())
            self.overlay.add_toast(t)

        def edit(self, m, preset=None):
            if m and m["trigger"] is None:
                RawView(self, m).present(self)
                return
            if self.opening: return                        # a second click while the first editor is on its way
            self.opening = True
            def done(found):                               # the service pickers are filled now, not on every refresh
                self.opening = False
                if not isinstance(found, Exception): self.services = found
                cur = self.cur.get(m["timer"], m) if m else None      # rows live on: use the latest data
                if cur and cur["trigger"] is None: RawView(self, cur).present(self)
                else: Editor(self, cur, preset).present(self)
            self.bg(list_services, done)

        def import_cron(self):
            """Read and convert the crontab off the main thread (it asks systemd to check every schedule), then
            open the review dialog."""
            if self.importing: return
            self.importing = True
            def work():
                text, err = read_crontab()
                return err, (None if err else crontab_plan(text))
            self.bg(work, self.cron_ready)

        def cron_ready(self, res):
            self.importing = False
            if isinstance(res, Exception): return self.toast(f"Could not read the crontab: {res}"[:120])
            err, plan = res
            if err: return self.toast(err[:120])
            if not plan: return self.toast("No crontab entries found")
            ImportCron(self, plan).present(self)

        def ask_delete(self, name):
            names = delete_plan(name)
            if not names:
                return self.toast("Nothing to delete: that unit isn't in ~/.config/systemd/user")
            lines = [f"• {n}" + (" (a link; the file it points to is kept)" if os.path.islink(f"{UNITS}/{n}") else "")
                     for n in names]
            d = Adw.AlertDialog(heading="Delete?", body="This will delete:\n" + "\n".join(lines))
            d.add_response("cancel", "Cancel"); d.add_response("delete", "Delete")
            d.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
            d.set_close_response("cancel"); d.set_default_response("cancel")
            d.connect("response", lambda _d, r: r == "delete" and self.do_delete(names))
            d.present(self)

        def bg(self, fn, done=None):
            """Run fn in a thread and hand its result (or the exception it raised) to done on the main thread."""
            def work():
                try: res = fn()
                except Exception as e: res = e
                def finish():
                    if done: done(res)
                    return False
                GLib.idle_add(finish)
            threading.Thread(target=work, daemon=True).start()

        def do_delete(self, names):
            self.bg(lambda: remove_units(names), self.deleted)

        def deleted(self, snap):
            self.fill()
            if isinstance(snap, Exception): return self.toast(f"Could not delete: {snap}"[:120])
            if snap["failed"]:
                return self.toast("Could not delete " + ", ".join(snap["failed"]))
            self.toast("Deleted", "Undo", lambda: self.bg(lambda: restore_units(snap), lambda _r: self.fill()))

        def run_now(self, service, live=True):
            self.bg(lambda: start_service(service), lambda err: self.started(err, service, live))

        def started(self, err, service, live):
            if isinstance(err, Exception): err = str(err)
            if err: return self.toast(f"Could not start: {err[:100]}")
            if live: LogView(service, follow=True).present(self)      # watch it run
            else: self.toast("Started")                               # an app has no output to follow
            GLib.timeout_add(1500, lambda: (self.fill(), False)[1])    # so "Running now" shows up

        def task_row(self, m):
            t = m["timer"]
            row = Adw.ActionRow(activatable=True)
            img = Gtk.Image(); row.add_prefix(img)
            row.add_suffix(icon_btn("text-x-generic-symbolic", "View log",
                                    lambda: LogView(self.cur[t]["service"]).present(self)))
            row.add_suffix(icon_btn("media-playback-start-symbolic", "Run now",
                                    lambda: self.run_now(self.cur[t]["service"], self.cur[t]["kind"] != "app")))
            sw = Gtk.Switch(valign=Gtk.Align.CENTER)
            sw.connect("state-set", lambda _s, on: self.on_switch(t, on))
            row.add_suffix(sw)
            row.connect("activated", lambda _r: self.edit(self.cur[t]))   # always the latest data, rows live on
            self.rows[t] = (row, img, sw)
            return row

        def paint(self, m):
            """Bring a row up to date without rebuilding it, so the list keeps its scroll position."""
            row, img, sw = self.rows[m["timer"]]
            sub, tip = task_texts(m)
            row.set_title(GLib.markup_escape_text(m["name"])); row.set_subtitle(GLib.markup_escape_text(sub))
            row.set_tooltip_text(tip or None)
            bad = bool(m["last"] and m["last"]["rc"] != 0)
            img.set_from_icon_name("dialog-warning-symbolic" if bad else "alarm-symbolic")
            (img.add_css_class if bad else img.remove_css_class)("error")
            self.syncing = True; sw.set_active(m["enabled"]); self.syncing = False

        def on_switch(self, timer, on):
            if self.syncing: return False                     # we are only showing the real state
            def work():
                err = set_timer(timer, on)
                GLib.idle_add(self.switched, on, err)
            threading.Thread(target=work, daemon=True).start()
            return False

        def switched(self, on, err):
            if err: self.toast(f"Could not {'turn on' if on else 'turn off'} the timer: {err[:100]}")
            self.fill()                                       # on failure this snaps the switch back to the truth
            return False

        def free_row(self, svc):
            row = Adw.ActionRow(title=GLib.markup_escape_text(svc), subtitle="No schedule · click to schedule or delete", activatable=True)
            row.connect("activated", lambda _r: self.edit(None, svc))
            row.add_prefix(Gtk.Image(icon_name="emblem-system-symbolic"))
            row.add_suffix(icon_btn("text-x-generic-symbolic", "View log", lambda: LogView(svc).present(self)))
            row.add_suffix(icon_btn("media-playback-start-symbolic", "Run now",
                                    lambda: self.run_now(svc)))
            row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))     # the whole row opens its editor
            return row

        def fill(self):
            """Refresh the lists. systemctl runs in a thread so the window never freezes; a request that arrives
            while one is running just triggers one more run afterwards."""
            if self.busy: self.again = True; return
            self.busy = True
            def work():
                try: data = gather()
                except Exception: data = None
                GLib.idle_add(self.render, data)
            threading.Thread(target=work, daemon=True).start()

        def render(self, data):
            self.busy = False
            if data is not None:
                self.has_tasks, self.sdver = bool(data["tasks"]), data["systemd"]
                if data["linger"] != self.linger: self.linger = data["linger"]; self.update_menu()
                tasks, free = data["tasks"], data["free"]
                self.cur = {m["timer"]: m for m in tasks}
                shape = (tuple(m["timer"] for m in tasks), tuple(free))
                if shape != self.shape:                       # rows added or removed: rebuild the lists
                    self.shape, self.rows = shape, {}
                    for lst in (self.list, self.free_list):
                        while (r := lst.get_first_child()) is not None: lst.remove(r)
                    self.stack.set_visible_child_name("list" if tasks or free else "empty")
                    self.h1.set_visible(bool(tasks) and bool(free)); self.list.set_visible(bool(tasks))
                    self.h2.set_visible(bool(free)); self.free_list.set_visible(bool(free))
                    for m in tasks: self.list.append(self.task_row(m))
                    for sv in free: self.free_list.append(self.free_row(sv))
                for m in tasks: self.paint(m)
            elif self.shape is None:                          # first load failed: don't spin forever
                self.stack.set_visible_child_name("empty")
            self.show_banner()
            if self.again: self.again = False; self.fill()
            return False

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id="io.github.reveille")
        def do_activate(self):
            (self.props.active_window or Win(self)).present()

    return App().run([])


