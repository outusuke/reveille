# reveille

GTK4/libadwaita front end for systemd user timers. Create, edit and monitor scheduled tasks without writing unit files.

systemd is the only store. Every task is a plain `.timer` (plus a `.service` for apps and commands) in `~/.config/systemd/user/`, with no database, no JSON file and no special unit prefix. The timers run your command directly and never call reveille, so the units keep working if you delete the program. Last-run results come from systemd itself (`systemctl --user status NAME.service`, `journalctl --user -u NAME.service`).

## Requirements

- Linux with systemd (user session)
- Python 3
- PyGObject, GTK 4, libadwaita 1.5 or newer (the editor uses `Adw.Dialog`)

## Usage

    ./reveille              open the window
    ./reveille install      add to the app menu
    ./reveille uninstall    remove from the app menu
    ./reveille services     list services the picker finds

The window lists every timer in `~/.config/systemd/user/`, whether reveille wrote it or you did. Saving rewrites only the lines the editor manages (name, schedule, command or app, working directory, environment, timeout, AC power, network wait); every other line, comment and section in the unit files, such as `ExecCondition=` or `SyslogIdentifier=`, stays as it was, and an unchanged command is kept exactly as written. A task is limited to schedule-only editing, with the reason shown in the editor, when a managed setting can't be represented (for example several `ExecStart=` lines, an `ExecStart=-…` prefix or a timeout that isn't whole minutes). In that case the original timer is backed up once as `NAME.timer.reveille-bak`. Switching a task to an existing service moves its own service file to `NAME.service.reveille-bak`. Delete lives inside the item: the editor of any task has a Delete button (even for timers limited to schedule-only editing), and clicking a service without a timer opens an editor with a Delete service button. A timer whose schedule the editor can't show at all (for example `OnActiveSec=`) opens a read-only view of its file with Open file and Delete task buttons. A confirmation lists the exact files first. A timer is deleted together with its same-named `.service` unless another timer still triggers that service, and a service without a timer is deleted on its own. Symlinks are removed as links (the file they point to is kept), `.reveille-bak` backups and `.d` override folders are never touched, and Undo restores everything, including links. Services without a timer are listed separately; click one to schedule it.

`install` only adds the app-menu entry (it copies the script to `~/.local/share/reveille/` so moving the download doesn't break the entry).

## Logs and running while logged out

Every task row has a log button that shows the last 200 lines of the service's journal (the same as `journalctl --user -u NAME.service`), with Reload and Copy. Services without a timer have it too.

User timers only run while your user session is running. When you are logged out, or after a restart until you log in, they wait. If tasks exist and lingering is off, reveille shows a banner explaining this and offers to turn it on (`loginctl enable-linger`); "Not now" hides it until the next start. The main menu can turn lingering on or off at any time. With lingering on, "At login" tasks run at boot, and apps still need a desktop session, so mostly commands benefit.

## Triggers

Daily, weekly, monthly, every N minutes/hours, at login, or a custom systemd calendar expression.

## Files

- Units: `~/.config/systemd/user/NAME.service` and `NAME.timer`, where NAME is derived from the task name

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
