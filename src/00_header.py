#: layer 00: shebang, module docstring, imports
#!/usr/bin/env python3
"""Task Scheduler: a small GTK4/libadwaita front end for systemd user timers.

systemd is the only store: every task is a plain .timer (and, for apps and commands, a .service)
in ~/.config/systemd/user. Nothing else is kept on disk, and the timers never call this program.

  reveille              open the window
  reveille install      add it to the app menu (copies itself to ~/.local/share/reveille)
  reveille uninstall    remove it from the app menu
  reveille services     list what the service picker finds (for troubleshooting)
  reveille list         print every task with its schedule, next run and last result
  reveille run NAME     run a task or service now
  reveille import-cron  turn crontab entries into tasks (preview; --apply creates them)
  reveille --version
"""
import argparse, datetime, os, re, shlex, shutil, subprocess, sys, tempfile, threading, time

