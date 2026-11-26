"""Big Screen Monitor Display core package.

The package is intentionally free of GTK imports so that the system service,
the configuration window and the test-suite can share it.
"""

__version__ = "5.6.0"

APP_ID = "big-screen-monitor-display"          # program name, X11 WM_CLASS, icon name
# D-Bus/GApplication id of the configuration window. GTK publishes it as the
# Wayland app_id (and _GTK_APPLICATION_ID on X11); docks, task bars and
# compositors look up "<id>.desktop" with it, so the launcher carries this name.
APPLICATION_ID = "br.com.biglinux.BigScreenMonitorDisplay"
DESKTOP_FILE = APPLICATION_ID + ".desktop"
SERVICE_NAME = "big-screen-monitor-display.service"
# Where development, releases and issues live (the APK link and "Report a problem").
PROJECT_URL = "https://github.com/ruscher/big-screen-monitor-display"
ISSUES_NEW_URL = PROJECT_URL + "/issues/new/choose"
HARDWARE_REPORT_URL = PROJECT_URL + "/issues/new?template=1-hardware.yml"
