# reveille

GTK4/libadwaita front end for systemd user timers. Create, edit and monitor scheduled tasks without writing unit files.

## Requirements

- Linux with systemd (user session)
- Python 3
- PyGObject, GTK 4, libadwaita 1

## Usage

    ./reveille              open the window
    ./reveille install      add to the app menu
    ./reveille uninstall    remove from the app menu
    ./reveille services     list services the picker finds
    ./reveille run-task ID  run one task (called by the timers)

`install` copies the script to `~/.local/share/reveille/`, so moving or deleting the download won't break existing timers.

## Triggers

Daily, weekly, monthly, every N minutes/hours, at login, or a custom systemd calendar expression.

## Files

- Tasks: `~/.config/reveille/tasks.json`
- Run results: `~/.local/state/reveille/runs/`
- Units: `~/.config/systemd/user/` (only files prefixed `reveille-` are touched)

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
