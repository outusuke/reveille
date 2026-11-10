# src/: the source of `reveille`

`reveille` in the repository root is **generated**. Edit the fragments here, then run `python3 build.py`
(`python3 build.py --check` fails if the two disagree; `python3 test_build.py` runs that check too).
The program stays one installable file because `reveille install` copies that single file.

Fragments are joined in file-name order, byte for byte. Leading `#:` lines are notes and are not copied.

**Layer rule:** a fragment may use names defined in its own layer or a lower one, never a higher one. The build
refuses to write otherwise, and refuses a name defined in two fragments.

| layer | file | holds | does I/O? |
|---|---|---|---|
| 00 | `00_header.py` | shebang, docstring, imports | no |
| 01 | `01_constants.py` | paths, vocabulary, the key sets the editor manages | no |
| 02 | `02_unitfile.py` | unit-file escaping, parsing, merge-rewrite, atomic write | files |
| 03 | `03_timespans.py` | time spans and timestamps, wording | no |
| 04 | `04_systemd.py` | `systemctl` access, unit status, last run | systemctl |
| 05 | `05_schedule.py` | what a schedule means; rewrite of a hand-written timer | files, systemctl |
| 06 | `06_tasks.py` | reading tasks back from unit files, drop-ins, listing | files, systemctl |
| 07 | `07_write.py` | writing and removing units, enabling timers | files, systemctl |
| 08 | `08_support.py` | process runner, linger, journal, row text, `gather()` | processes |
| 09 | `09_menu.py` | app-menu entry | files |
| 10 | `10_gui.py` | the GTK4/libadwaita window | GTK |
| 11 | `11_cli.py` | command line, `main()` | calls the above |

The files that decide what ends up on disk or what systemd is asked to do are 02, 05, 06 and 07.
The only GLib/GTK-stack use outside layer 10 is a lazy `Gio` import in `build_exec` (06, to resolve a `.desktop`
file) and the availability probe in `cmd_gui` (11), so everything else runs, and is tested, without GTK.
