import os
import sys

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "usr", "share",
                                       "big-screen-monitor-display"))
sys.path.insert(0, APP_DIR)
os.environ.pop("NOTIFY_SOCKET", None)
os.environ.pop("WATCHDOG_USEC", None)
