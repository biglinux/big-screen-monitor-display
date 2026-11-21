import os
import sys

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "usr", "share",
                                       "big-screen-monitor-display"))
sys.path.insert(0, APP_DIR)
os.environ.pop("NOTIFY_SOCKET", None)
os.environ.pop("WATCHDOG_USEC", None)


def pixels(image):
    """Pixel values of a Pillow image (``getdata`` is deprecated from Pillow 12.1)."""
    flattened = getattr(image, "get_flattened_data", None)
    return flattened() if flattened else image.getdata()
