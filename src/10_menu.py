#: layer 10: app-menu entry install and removal
# ---------------------------------------------------------------- app menu
def menu_installed():
    return os.path.isfile(DESKTOP)

def refresh_desktop_db():
    try: subprocess.run(["update-desktop-database", os.path.dirname(DESKTOP)], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired): pass

def install_menu():
    """Copy the program to a stable place and add an entry to the app menu. Returns an error text or None."""
    try:
        os.makedirs(os.path.dirname(INSTALLED), exist_ok=True)
        if os.path.realpath(SELF) != os.path.realpath(INSTALLED):
            shutil.copyfile(SELF, INSTALLED + ".tmp"); os.chmod(INSTALLED + ".tmp", 0o755)
            os.replace(INSTALLED + ".tmp", INSTALLED)
        os.makedirs(os.path.dirname(DESKTOP), exist_ok=True)
        cmd = f'"{sys.executable}" "{INSTALLED}"'
        with open(DESKTOP, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Task Scheduler\n"
                    "Comment=Run apps and commands on a schedule\n"
                    f"Exec={cmd}\nIcon=preferences-system-time\nTerminal=false\n"
                    "Categories=Utility;System;\nKeywords=schedule;timer;cron;task;\n")
    except OSError as e:
        return e.strerror or str(e)
    refresh_desktop_db()
    return None

def uninstall_menu():
    for p in (DESKTOP, INSTALLED):
        try: os.unlink(p)
        except OSError: pass
    refresh_desktop_db()


