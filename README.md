# reveille

GTK4/libadwaita front end for systemd user timers. Create, edit and monitor scheduled tasks without writing unit files.

systemd is the only store. Every task is a plain `.timer` (plus a `.service` for apps and commands) in `~/.config/systemd/user/`, with no database, no JSON file and no special unit prefix. The timers run your command directly and never call reveille, so the units keep working if you delete the program. Last-run results come from systemd itself (`systemctl --user status NAME.service`, `journalctl --user -u NAME.service`).

## Requirements

- Linux with systemd (user session)
- Python 3
- systemd 244 or newer for retries, 249 or newer for "Then run" (the editor greys these out on older versions)
- PyGObject, GTK 4, libadwaita 1.5 or newer (the editor uses `Adw.Dialog`)

## Usage

    ./reveille              open the window
    ./reveille install      add to the app menu
    ./reveille uninstall    remove from the app menu
    ./reveille services     list services the picker finds
    ./reveille list         print every task with its schedule, next run and last result
    ./reveille run NAME     run a task or service now (task name or unit name)
    ./reveille --version    print the version (--help lists all commands)

The window lists every timer in `~/.config/systemd/user/`, whether reveille wrote it or you did. Saving rewrites only the lines the editor manages (name, schedule, command or app, working directory, environment, timeout, retries, low priority, path condition, "Then run", AC power, network wait); every other line, comment and section in the unit files, such as `ExecCondition=` or `SyslogIdentifier=`, stays as it was, and an unchanged command is kept exactly as written. A task is limited to schedule-only editing, with the reason shown in the editor, when a managed setting can't be represented (for example several `ExecStart=` lines, an `ExecStart=-…` prefix or a timeout that isn't whole minutes, several `ConditionPathExists=` lines, an `OnSuccess=` with several units, or a `Restart=` other than `on-failure`). In that case the original timer is backed up once as `NAME.timer.reveille-bak`. Switching a task to an existing service moves its own service file to `NAME.service.reveille-bak`. Delete lives inside the item: the editor of any task has a Delete button (even for timers limited to schedule-only editing), and clicking a service without a timer opens an editor with a Delete service button. A timer whose schedule the editor can't show at all (for example `OnActiveSec=`) opens a read-only view of its file with Open file and Delete task buttons. A confirmation lists the exact files first. A timer is deleted together with its same-named `.service` unless another timer still triggers that service, and a service without a timer is deleted on its own. Symlinks are removed as links (the file they point to is kept), `.reveille-bak` backups and `.d` override folders are never touched, and Undo restores everything, including links. Services without a timer are listed separately; click one to schedule it.

`install` only adds the app-menu entry (it copies the script to `~/.local/share/reveille/` so moving the download doesn't break the entry).

## What a row tells you

Each row shows the schedule, when it runs next and when it last ran, in plain terms ("in 12 min", "tomorrow 03:00", "yesterday 03:00"); hover for the exact times. A task that is running right now says so. The switch shows whether the timer is active, and the row says when that differs from what a restart will do: "Not enabled: won't start again after a restart" for a timer that is running but not enabled, "Stopped, starts again at next login" for one that is enabled but stopped. Timers written without an `[Install]` section can't be enabled, so the switch falls back to plain start and stop for them, and if systemd refuses, the reason is shown.

## Reliability options

These live under Advanced in the editor and apply to apps and commands (not to a task that triggers an existing service, which keeps its own settings).

- **Retry on failure**: how many times to try again (up to 10) and how many minutes to wait between tries. Written as `Restart=on-failure`, `RestartSec=` and a matching `StartLimitBurst=`. systemd stops retrying once the limit is reached, and the limit window is sized to hold every try (one hour per run is assumed unless a timeout is set). Two consequences: a schedule shorter than that window is refused, since the next run is the retry there, and a manual run is refused by systemd while the limit is in effect. While a task waits for its next try the row says "Waiting to retry".
- **Run at low priority**: `Nice=19` and `IOSchedulingClass=idle`. A different `Nice=` or `IOSchedulingClass=` you wrote by hand is left alone while this is off.
- **Only if this path exists**: `ConditionPathExists=`. Start the path with `!` to require that it is missing. When the condition fails systemd skips the run without error.
- **Then run**: starts another service after this one succeeds (`OnSuccess=`). Choices that would make tasks run each other in a loop are refused.

## Logs and running while logged out

Every task row has a log button that shows the last 200 lines of the service's journal (the same as `journalctl --user -u NAME.service`), with Reload and Copy. Services without a timer have it too. The Follow toggle shows new lines as they arrive. Run now starts the task and opens the log already following, so you can watch it work (apps have no output to follow, so they just show "Started").

User timers only run while your user session is running. When you are logged out, or after a restart until you log in, they wait. If tasks exist and lingering is off, reveille shows a banner explaining this and offers to turn it on (`loginctl enable-linger`); "Not now" hides it until the next start. The main menu can turn lingering on or off at any time. With lingering on, "At login" tasks run at boot, and apps still need a desktop session, so mostly commands benefit.

## Triggers

Daily, weekly, monthly, every N minutes/hours, at login, or a custom systemd calendar expression.

## Files

- Units: `~/.config/systemd/user/NAME.service` and `NAME.timer`, where NAME is derived from the task name

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
