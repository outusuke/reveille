# reveille

GTK4/libadwaita front end for systemd user timers. Create, edit and monitor scheduled tasks without writing unit files.

systemd is the only store. Every task is a plain `.timer` (plus a `.service` for apps and commands) in `~/.config/systemd/user/`, with no database, no JSON file and no special unit prefix. The timers run your command directly and never call reveille, so the units keep working if you delete the program. Last-run results come from systemd itself (`systemctl --user status NAME.service`, `journalctl --user -u NAME.service`).

## Requirements

- Linux with systemd (user session)
- Python 3
- PyGObject, GTK 4, libadwaita 1

## Usage

    ./reveille              open the window
    ./reveille install      add to the app menu
    ./reveille uninstall    remove from the app menu
    ./reveille services     list services the picker finds

The window lists every timer in `~/.config/systemd/user/`, whether reveille wrote it or you did. Saving rewrites only the lines the editor manages (name, schedule, command or app, working directory, environment, timeout, AC power, network wait); every other line, comment and section in the unit files, such as `ExecCondition=` or `SyslogIdentifier=`, stays as it was, and an unchanged command is kept exactly as written. A task is limited to schedule-only editing, with the reason shown in the editor, when a managed setting can't be represented (for example several `ExecStart=` lines, an `ExecStart=-…` prefix or a timeout that isn't whole minutes). In that case the original timer is backed up once as `NAME.timer.reveille-bak`. Switching a task to an existing service moves its own service file to `NAME.service.reveille-bak`. Deleting a task removes its `.timer` and its own `.service`, with an Undo. Services without a timer are listed separately with a **Schedule…** button.

`install` only adds the app-menu entry (it copies the script to `~/.local/share/reveille/` so moving the download doesn't break the entry).

## Triggers

Daily, weekly, monthly, every N minutes/hours, at login, or a custom systemd calendar expression.

## Files

- Units: `~/.config/systemd/user/NAME.service` and `NAME.timer`, where NAME is derived from the task name

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
