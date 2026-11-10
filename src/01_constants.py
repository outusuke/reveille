#: layer 01: paths, vocabulary and the key sets the editor manages
VERSION = "0.1.0"

HOME = os.path.expanduser("~")
CONF = os.environ.get("XDG_CONFIG_HOME", f"{HOME}/.config")
UNITS = f"{CONF}/systemd/user"
SELF = os.path.realpath(__file__)
APPS = os.environ.get("XDG_DATA_HOME", f"{HOME}/.local/share")
INSTALLED = f"{APPS}/reveille/reveille"          # stable copy for the app-menu entry
DESKTOP = f"{APPS}/applications/io.github.reveille.desktop"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAYS = DAYS[:5]
TRIGGERS = ["Daily", "Weekdays", "Weekly", "Monthly", "Last day of the month", "Several times a day",
            "At an interval", "At login", "Custom"]
TRIGGER_IDS = ["daily", "weekdays", "weekly", "monthly", "lastday", "times", "interval", "login", "custom"]
CALENDAR_TYPES = {"daily", "weekdays", "weekly", "monthly", "lastday", "times", "custom"}   # the ones written as OnCalendar=
INTERVAL_UNITS = {"s": 1, "min": 60, "h": 3600, "d": 86400}      # in seconds; the editor offers them in this order
EVERY_NAMES = {"s": ("second", "seconds"), "min": ("minute", "minutes"), "h": ("hour", "hours"), "d": ("day", "days")}
MAX_EVERY = 9999                    # what the "Every" box can hold; a longer interval isn't shown, so it isn't edited
DEFAULT_TR = {"type": "daily", "hour": 3, "minute": 0, "days": ["Mon"], "dom": 1, "every": 30, "unit": "min", "expr": "",
              "times": ["09:00", "17:00"], "login_sec": 10}

SCHEDULE_KEYS = ("OnCalendar", "OnBootSec", "OnStartupSec", "OnUnitActiveSec", "OnActiveSec", "OnUnitInactiveSec",
                 "Persistent", "RandomizedDelaySec")
TIMER_KEYS = set(SCHEDULE_KEYS) | {"AccuracySec"}              # what a save of the schedule may rewrite
# Settings the editor manages in the service. A drop-in that sets one of them makes what the editor shows untrue.
UNIT_KEYS = {"ConditionACPower", "Wants", "After", "ConditionPathExists", "OnSuccess", "OnFailure",
             "StartLimitIntervalSec", "StartLimitBurst"}
SERVICE_KEYS = {"WorkingDirectory", "Environment", "TimeoutStartSec", "Restart", "RestartSec", "Nice", "IOSchedulingClass"}
SERVICE_DROPIN_KEYS = {"Unit": UNIT_KEYS, "Service": SERVICE_KEYS | {"ExecStart", "KillMode"}}
TIMER_DROPIN_KEYS = {"Timer": set(SCHEDULE_KEYS) | {"Unit"}, "Unit": {"Description"}}
ONLINE = "network-online.target"
BOOT_OK = {"enabled", "enabled-runtime", "indirect", "alias"}     # UnitFileState values that survive a restart


