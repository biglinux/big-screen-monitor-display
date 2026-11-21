import os
import sys


APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "usr", "share",
                                       "big-screen-monitor-display"))
sys.path.insert(0, APP_DIR)
os.environ.pop("NOTIFY_SOCKET", None)
os.environ.pop("WATCHDOG_USEC", None)


def pytest_configure(config):
    # Deprecations raised inside PyGObject itself (gi/overrides, gi/events) on
    # Python 3.14, not by this project's code: keep the test output meaningful.
    config.addinivalue_line("filterwarnings", r"ignore:GLib\.unix_signal_add_full is deprecated")
    config.addinivalue_line("filterwarnings",
                            r"ignore:'asyncio\.(get_event_loop_policy|AbstractEventLoopPolicy)' is deprecated")
