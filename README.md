# reveille

GTK4/libadwaita front end for systemd user timers. Create, edit and monitor scheduled tasks without writing unit files.

systemd is the only store. Every task is a plain `.timer` (plus a `.service` for apps and commands) in `~/.config/systemd/user/`, with no database and no special prefix. The timers run your command directly and never call reveille, so they keep working if you delete the program. Last-run results come from systemd (`systemctl --user status NAME.service`, `journalctl --user -u NAME.service`).

![reveille window](docs/screenshot.png)

## Requirements

- Linux with systemd (user session) and Python 3
- PyGObject, GTK 4, libadwaita 1.5+
- systemd 244+ for retries, 249+ for "Then run", 254+ for wake from sleep (the editor greys these out on older versions)

## Usage

    ./reveille              open the window
    ./reveille install      add to the app menu (uninstall removes it)
    ./reveille list         print every task with its schedule, next run and last result (--json for scripts)
    ./reveille enable NAME  turn a task's timer on (disable NAME turns it off)
    ./reveille run NAME     run a task or service now
    ./reveille logs NAME    print the last 200 lines of its journal (-n N for another count)
    ./reveille new NAME --command CMD --at 09:00   create a task (or --every 15min, --calendar EXPR, --login; --days, --wake, --disabled, --dry-run)
    ./reveille import-cron  preview turning your crontab into tasks (--apply creates them)
    ./reveille --help       all commands

## Editing

The window lists every timer in the folder above, whether reveille wrote it or you did. Saving rewrites only the lines the editor manages; every other line, comment and section stays as it was, and an unchanged command is kept exactly as written.

When a managed setting can't be represented (several `ExecStart=` lines, a timeout that isn't whole minutes, an `OnFailure=` with several units, and similar), or a drop-in (`NAME.service.d/*.conf`) sets one, the task is limited to schedule-only editing and the editor says why. The original timer is then backed up once as `NAME.timer.reveille-bak`. A drop-in that changes the schedule, or a schedule the editor can't show (such as `OnActiveSec=`), opens a read-only view of the file. Drop-ins are never changed or deleted.

Delete is in each task's editor. A confirmation lists the exact files, a timer goes with its same-named `.service` unless another timer uses it, and Undo restores everything. Services without a timer are listed separately; click one to schedule it.

## Options

Under Advanced; they apply to apps and commands, except wake from sleep, which is a timer setting.

- **Retry on failure**: up to 10 tries, with a wait between them. A schedule shorter than the retry window is refused.
- **Run at low priority**: `Nice=19` and `IOSchedulingClass=idle`.
- **Only if this path exists**: `ConditionPathExists=` (start with `!` to require it missing).
- **Only if this command succeeds**: `ExecCondition=` (systemd 243+). The command runs just before the task; if it exits 1 to 254 the run is skipped quietly and doesn't count as a failure (so no retry and no "If it fails, run"), while 255 or a crash is a failure. Also `reveille new … --only-if CMD`. An existing `ExecCondition=` line is shown here and kept exactly as written until you change it; several lines, or one starting with `-`, `@`, `+`, `!` or `:`, limit the task to schedule-only editing.
- **After it finishes, run this command**: `ExecStopPost=`. It is a plain command rather than a service, and systemd runs it once the task has stopped, including after a failure and when "Only if this command succeeds" skips the run. Also `reveille new … --after CMD`. systemd sets `$SERVICE_RESULT`, `$EXIT_CODE` and `$EXIT_STATUS` for it, but reveille writes `$` as `$$` so that no variable is expanded by systemd; to use them, run a shell, such as `/bin/sh -c 'echo $SERVICE_RESULT >> ~/task.log'`. systemd also runs `ExecStopPost=` when a service is restarted, so with "Retry on failure" expect the command after every try, not only after the last one (this follows systemd.service(5); reveille has not tested it). Handled like the condition above: an unchanged line is kept as written, and several lines or a leading `-`, `@`, `+`, `!` or `:` limit the task to schedule-only editing.
- **Then run** / **If it fails, run**: start another service on success or failure. `reveille-notify@%n.service` sends a desktop notification (needs `notify-send`). Choices that would make tasks run each other in a loop are refused.
- **Wake the computer from sleep**: `WakeSystem=true`. It only resumes the computer; nothing suspends it again, and the hardware must support timed wake-up. In a user session it needs systemd 254+ and a manager holding `CAP_WAKE_ALARM`, which the editor checks. Rows show "wakes from sleep", and `list --json` has a `wake` field.
- **Wait for the network**: up to 60 seconds, then runs anyway. A user session has no `network-online.target`.
- **Run missed tasks after startup**: `Persistent=true`, for calendar schedules only.

## Triggers

Daily, Weekdays, Weekly, Monthly (day 1 to 28), Last day of the month, Several times a day, At an interval (with an optional first run after login), At login, and Custom (any systemd calendar expression; separate several with `|`). Existing timers are recognized where possible; anything else stays custom.

## Importing a crontab

Main menu, **Import from crontab…**, or `reveille import-cron`. Nothing is written without `--apply`, and your crontab is never changed, so remove the imported lines yourself or the jobs run twice. Use `--disabled` to create the timers switched off, and `--file FILE` to read a saved crontab.

Schedules follow cron's wall clock (`*/15 * * * *` becomes `*:0/15`), shell commands run as `SHELL -c '…'`, and `VAR=value` lines become the environment. Imported tasks don't catch up on missed runs, as in cron. `MAILTO=`, `CRON_TZ=`, an unescaped `%`, out-of-range values and `5/15`-style steps are not carried over; such entries are listed with the reason and skipped.

## Running while logged out

User timers only run while your user session is running. If tasks exist and lingering is off, a banner offers `loginctl enable-linger` (the main menu can also toggle it). With lingering on, "At login" tasks run at boot; apps still need a desktop session, so mostly commands benefit.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
