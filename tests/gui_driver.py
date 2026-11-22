"""Drives the real configuration window and reports what it observed (JSON).

Run by tests/test_gui.py inside ``dbus-run-session`` with a temporary
settings file (BSM_CONFIG), a fake service status (BSM_STATUS), memory
GSettings and private XDG directories. Never touches the desktop or /etc.

    python3 tests/gui_driver.py APP_DIR SCENARIO
"""

import json
import os
import sys
import time
import traceback

APP, SCENARIO = sys.argv[1], sys.argv[2]
sys.path.insert(0, APP)

import config_gui  # noqa: E402
from gi.repository import GLib  # noqa: E402

from bsmd import settings  # noqa: E402
from bsmd.displays import discovery  # noqa: E402

# The displays come from the fake status only: whatever is plugged into the
# machine running the tests must not appear (an unidentified USB device made
# the "needs your choice" card show up and failed the dashboard checks).
discovery.scan_usb = lambda sysfs=None: []

context = GLib.MainContext.default()
result = {"errors": [], "checks": {}}
_hook = sys.excepthook


def excepthook(kind, value, tb):
    result["errors"].append("".join(traceback.format_exception(kind, value, tb))[-1500:])
    _hook(kind, value, tb)


sys.excepthook = excepthook


def pump(seconds):
    end = time.monotonic() + seconds
    status = os.environ.get("BSM_STATUS")
    if SCENARIO != "stopped" and status and os.path.exists(status):
        os.utime(status)                    # a running service rewrites it every 2 s
    while time.monotonic() < end:
        context.iteration(False)
        time.sleep(0.003)


def check(name, value):
    result["checks"][name] = value


def saved_value(key):
    with open(os.environ["BSM_CONFIG"], encoding="utf-8") as handle:
        return json.load(handle).get(key)


def frames(window):
    return sum(entry["renderer"].frames for entry in window._previews)


def run_main(window):
    pump(1.5)
    check("sections", window.section_keys())
    built = []
    for key in window.section_keys():
        window.show_section(key)
        pump(0.8)
        built.append(key in window.sections and window.content_stack.get_visible_child_name() == key)
    check("all_sections_built", all(built))
    check("collapsed_at_default_width", window.split.get_collapsed())

    # Unfocused window: the visible preview shows a still frame and does not animate.
    window.show_section("brother_away")
    pump(1.5)
    real_focused = window._focused
    window._focused = lambda: False
    window._focus_changed()
    pump(0.5)
    before = frames(window)
    pump(1.5)
    check("unfocused_preview_still", frames(window) <= before + 1 and frames(window) > 0)
    window._focused = real_focused                  # BSM_PREVIEW_ALWAYS: behave as focused
    window._focus_changed()
    # Previews only render while visible.
    pump(1.0)
    before = frames(window)
    pump(1.0)
    check("visible_preview_renders", frames(window) > before)
    window.show_section("preferences")
    pump(0.6)
    before = frames(window)
    pump(1.5)
    check("hidden_previews_idle", frames(window) == before)
    check("renderers_inactive", not any(e["renderer"].active for e in window._previews))
    trays = window.preferences_page.trays
    check("tray_switches", sorted(trays.rows) == ["big-screen-monitor-deepcool", "big-screen-monitor-tray"]
          and not any(row.get_active() for row in trays.rows.values()))
    # Window open with Preferences already built: the tray switched on by the
    # first-run offer must show on its switch (host and start simulated here).
    from gui import preferences_page, tray_settings
    from traykit import autostart, session
    saved = (session.qt_available, session.tray_host_available, session.start, window.status)
    session.qt_available, session.tray_host_available = (lambda: True), (lambda: True)
    session.start = lambda app_id: True
    os.environ.pop("BSM_NO_TRAY_START", None)
    window.status = {"displays": [{"id": "usb-1-2", "source": {"profile": "turing_rev_a"},
                                   "capabilities": {"output": "raster"}}]}
    tray_settings.ensure_running(window, preferences_page.load_gui_settings, preferences_page.save_gui_settings)
    pump(0.2)
    check("tray_switch_follows_window_open", trays.rows["big-screen-monitor-tray"].get_active()
          and not trays.rows["big-screen-monitor-deepcool"].get_active())
    autostart.disable("big-screen-monitor-tray")
    load, save = preferences_page.load_gui_settings, preferences_page.save_gui_settings

    def offer(done):
        data = load()
        data[session.OFFER_KEY] = done
        save(data)

    # A cooler plugged in after the window opened gets the first-run offer too.
    offer(False)
    window.tray_kinds = set()
    window.status = {"displays": [{"id": "usb-1-3", "source": {"profile": "deepcool_ak"},
                                   "capabilities": {"output": "segment"}}]}
    tray_settings.status_changed(window, load, save)
    pump(0.2)
    check("tray_offer_follows_new_device", autostart.is_enabled("big-screen-monitor-deepcool")
          and trays.rows["big-screen-monitor-deepcool"].get_active() and load()[session.OFFER_KEY] is True)
    trays._updating = True
    trays.rows["big-screen-monitor-deepcool"].set_active(False)
    trays._updating = False
    autostart.disable("big-screen-monitor-deepcool")
    # A switch flipped before any offer is the user's choice: no offer afterwards.
    offer(False)
    saved_send = session.send

    class Launch:
        def __init__(self):
            self.alive, self.terminated = True, False

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.terminated, self.alive = True, False

    launch = Launch()
    session.start = lambda app_id: launch
    session.send = lambda app_id, command: False          # still starting: no socket yet
    switch = trays.rows["big-screen-monitor-tray"]
    switch.set_active(True)
    switch.set_active(False)
    check("tray_switch_is_a_choice", load()[session.OFFER_KEY] is True
          and not autostart.is_enabled("big-screen-monitor-tray"))
    # Switched off while it was starting: it is ended, not left running.
    trays._stop_launch("big-screen-monitor-tray", 1)
    check("tray_switch_off_while_starting", launch.terminated and "big-screen-monitor-tray" not in trays.launches)
    session.send = saved_send
    session.qt_available, session.tray_host_available, session.start, window.status = saved
    os.environ["BSM_NO_TRAY_START"] = "1"
    trays.refresh()

    # Edit -> pending bar -> apply -> saved.
    window.show_section("home")
    pump(0.3)
    check("bar_hidden_initially", not window.pending_revealer.get_reveal_child())
    window._set("std_scheme", "nord")
    check("bar_shown_after_edit", window.pending_revealer.get_reveal_child())
    check("apply_enabled", window.apply_button.get_sensitive())
    window._apply()
    pump(1.5)
    check("applied_value_saved", saved_value("std_scheme") == "nord")
    check("bar_hidden_after_apply", not window.pending_revealer.get_reveal_child())

    # Discard.
    window._set("std_scheme", "dracula")
    window._revert()
    pump(0.3)
    check("discard_restores", window.values["std_scheme"] == "nord" and saved_value("std_scheme") == "nord")

    # Shared controls stay in sync (dashboard brightness and the defaults group).
    window._set("brightness", 35)
    scales = [w for w, extra in window._widgets["brightness"] if extra == "scale"]
    check("brightness_controls", len(scales))
    check("brightness_synced", all(int(s.get_value()) == 35 for s in scales))
    window._revert()

    # Restore defaults: nothing saved until Apply.
    window._set("std_scheme", "solarized")
    window._apply()
    pump(1.5)
    window._restore()
    pump(0.3)
    check("restore_loads_defaults", window.values["std_scheme"] == settings.defaults()["std_scheme"])
    check("restore_not_saved", saved_value("std_scheme") == "solarized")
    window._revert()

    # Theme gallery: every card, every detail page, "Use this theme".
    window.show_section("themes")
    pump(2.5)
    gallery = window.theme_gallery
    check("theme_cards", sorted(gallery.grid.cards))
    textured = 0
    for card in gallery.grid.cards.values():
        textured += card.picture.get_paintable() is not None
    check("theme_thumbnails", textured)
    for theme_id in gallery.grid.cards:
        gallery.open_theme(theme_id)
        pump(0.4)
        window.sections["themes"].pop()
        pump(0.2)
    gallery.open_theme("planet")
    pump(0.3)
    gallery._use("planet")
    check("use_theme_selects", window.values["theme"] == "planet")
    window.sections["themes"].pop()
    gallery.search.set_text("planet")
    pump(0.5)
    visible = [key for key in gallery.grid.cards if gallery._matches_id(key)]
    check("search_filters", visible == ["planet"])
    gallery.search.set_text("")
    window._revert()

    # Brother Away stories.
    window.show_section("brother_away")
    pump(2.5)
    page = window.brother_away_page
    check("story_cards", len(page.grid.cards))
    check("story_thumbnails", sum(c.picture.get_paintable() is not None for c in page.grid.cards.values()))
    seeks = []
    theme = page.renderer.theme
    original_seek = theme.debug_seek
    theme.debug_seek = lambda *args, **kwargs: (seeks.append(args[1] if len(args) > 1 else None),
                                                original_seek(*args, **kwargs))
    page.play("ufo")
    pump(1.0)
    check("story_queued", seeks == ["ufo"] and "ufo" not in page.live.caption.get_label())

    # Big Media Player.
    window.show_section("big_media_player")
    pump(2.0)
    media = window.media_page
    check("skin_cards", len(media.grid.cards))
    media._on_skin_card("big_wave")
    check("skin_selected", window.values["bmp_skin"] == "big_wave")
    media.open_options()
    pump(0.6)
    check("media_options_page", window.sections["big_media_player"].get_visible_page() is media.options_page)
    window.sections["big_media_player"].pop()
    window._revert()

    # Displays (fake status: two simulated panels).
    window.show_section("displays")
    pump(2.0)
    displays = window.displays_page
    check("display_cards_include_status", all(d in displays.grid.cards for d in ("simulated", "simulated-1")))
    displays.open_display("simulated-1")
    pump(0.6)
    check("display_detail_open", window.sections["displays"].get_visible_page() is displays.details["simulated-1"])
    displays._set("simulated-1", "theme", "planet")
    check("display_override", window.values["displays"]["simulated-1"]["theme"] == "planet")
    window._revert()

    # Dashboard with two displays.
    window.show_section("home")
    pump(0.6)
    check("dashboard_selector_visible", window.dashboard.display_combo.get_visible())
    check("dashboard_state_hidden", not window.dashboard.state_card.get_visible())

    # Kojiro activity follows the section.
    window.show_section("kojiro")
    pump(0.8)
    check("kojiro_active", window.kojiro_page.worker.active)
    window.show_section("performance")
    pump(0.3)
    check("kojiro_inactive", not window.kojiro_page.worker.active)
    window.profile_buttons["economy"].set_active(True)
    check("profile_card_sets_value", window.values["performance_profile"] == "economy")
    window._revert()
    check("profile_card_reverted", window.profile_buttons["auto"].get_active())

    window.close()
    pump(0.5)
    check("renderers_stopped", all(e["renderer"]._stop.is_set() for e in window._previews))
    check("status_timer_removed", window._closed)


def run_stopped(window):
    pump(1.5)
    window.show_section("home")
    pump(0.5)
    card = window.dashboard.state_card
    check("state_card_visible", card.get_visible())
    check("state_card_title", card.title.get_label())
    check("sidebar_status", window.status_label.get_label())
    window.show_section("diagnostics")
    pump(0.5)
    check("diag_card_title", window.diag_card.title.get_label())
    window.close()


def run_narrow(window):
    pump(1.5)
    check("width", window.get_width())
    check("collapsed", window.split.get_collapsed())
    check("adaptive_narrow", config_gui.ui.ADAPTIVE.narrow)
    window.show_section("themes")
    pump(1.0)
    window.theme_gallery.open_theme("standard")
    pump(1.0)
    check("min_width_fits", window.get_width() <= 420)
    window.close()


def run_deepcool(window):
    """A DeepCool cooler (telemetry device, no pixels) next to a simulated panel."""
    pump(1.5)
    window.show_section("displays")
    pump(2.0)
    displays = window.displays_page
    card = displays.grid.cards.get("usb-3-2")
    check("cooler_card", card is not None)
    pump(1.5)
    check("cooler_card_text", card.subtitle.get_label() if card else "")
    check("cooler_card_thumbnail", bool(card and card.picture.get_paintable() is not None))
    displays.open_display("usb-3-2")
    pump(0.8)
    page = displays.details.get("usb-3-2")
    detail = getattr(page, "deepcool", None)
    check("cooler_detail", detail is not None and window.sections["displays"].get_visible_page() is page)
    check("cooler_live_badge", detail.preview.badge.get_label() if detail else "")
    check("cooler_values", detail.values_row.get_subtitle() if detail else "")
    check("cooler_missing", detail.diag["missing"].get_subtitle() if detail else "")
    displays._set("usb-3-2", "dc_preset", "guardian")
    check("cooler_override", window.values["displays"]["usb-3-2"]["dc_preset"] == "guardian")
    report = json.loads(detail.diagnostics_text()) if detail else {}
    check("cooler_diagnostics", report.get("family") == "deepcool_ak_pro" and "rows" in report)
    window._revert()
    displays.open_display("simulated")
    pump(0.6)
    check("panel_detail_still_raster", getattr(displays.details.get("simulated"), "deepcool", None) is None)
    window.show_section("home")
    pump(0.5)
    dashboard = window.dashboard
    index = dashboard._ids.index("usb-3-2")
    dashboard.display_combo.set_selected(index)
    pump(2.5)
    renderer = window.renderer_of(dashboard.preview)
    check("dashboard_face", renderer.face is not None and renderer.frames > 0)
    check("dashboard_resolution", dashboard.rows["resolution"].get_subtitle())
    window.close()


def run_android(window):
    """An Android phone next to a simulated panel; a pairing request waiting."""
    import glob
    pump(1.5)
    window.show_section("displays")
    pump(2.0)
    displays = window.displays_page
    group = displays.android
    check("android_group", group.group.get_visible())
    card = displays.grid.cards.get("android-0123456789ab")
    check("android_card", card is not None)
    check("android_card_title", card.title.get_label() if card else "")
    check("android_card_subtitle", card.subtitle.get_label() if card else "")
    check("android_request_rows", len(group.dynamic))
    check("android_state", group.state_row.get_subtitle())
    spool = os.path.join(os.path.dirname(os.environ["BSM_STATUS"]), "commands")
    group._decide("0011223344556677", True)
    pump(1.0)
    sent = [json.load(open(path)) for path in sorted(glob.glob(os.path.join(spool, "*.json")))]
    check("android_approve_sent", [c.get("action") for c in sent])
    for path in glob.glob(os.path.join(spool, "*.json")):
        os.unlink(path)
    displays.open_display("android-0123456789ab")
    pump(0.8)
    page = displays.details.get("android-0123456789ab")
    check("android_detail", page is not None)
    check("android_connection", page.rows["connection"].get_subtitle() if page else "")
    check("android_protocol", page.rows["protocol"].get_subtitle() if page else "")
    group.open_pairing()
    pump(1.5)
    dialog = group.dialog
    check("android_qr", bool(dialog and dialog.picture.get_paintable() is not None and dialog.picture.get_visible()))
    check("android_address", dialog.address_row.get_subtitle() if dialog else "")
    check("android_steps", dialog.steps.get_label() if dialog else "")
    # the download URL wraps inside the 560 px dialog instead of widening it
    check("android_steps_width", dialog.steps.get_width() if dialog else -1)
    sent = [json.load(open(path)) for path in sorted(glob.glob(os.path.join(spool, "*.json")))]
    opened = [c for c in sent if c.get("action") == "android_pair_open"]
    check("android_pair_open", bool(opened) and len(opened[0].get("secret", "")) >= 22)
    status = open(os.environ["BSM_STATUS"]).read()
    check("android_secret_not_in_status", bool(opened) and opened[0]["secret"] not in status)
    dialog.dialog.close()
    pump(1.0)
    sent = [json.load(open(path)) for path in sorted(glob.glob(os.path.join(spool, "*.json")))]
    check("android_pair_closed", any(c.get("action") == "android_pair_close" for c in sent))
    window.close()


SCENARIOS = {"main": run_main, "stopped": run_stopped, "narrow": run_narrow, "deepcool": run_deepcool,
             "android": run_android}
original = config_gui.ConfigWindow.__init__


def patched(self, *args, **kwargs):
    original(self, *args, **kwargs)
    if SCENARIO == "narrow":
        self.set_default_size(400, 800)

    def go(window):
        try:
            SCENARIOS[SCENARIO](window)
        except Exception:  # noqa: BLE001 - reported to the test
            result["errors"].append(traceback.format_exc()[-2000:])
        print("RESULT " + json.dumps(result), flush=True)
        os._exit(0)
    self.connect("map", lambda w: GLib.timeout_add(1, lambda: go(w) and False))


config_gui.ConfigWindow.__init__ = patched
config_gui.main([sys.argv[0]])
