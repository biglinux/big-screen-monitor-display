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
    check("collapsed", window.split.get_collapsed())
    check("adaptive_narrow", config_gui.ui.ADAPTIVE.narrow)
    window.show_section("themes")
    pump(1.0)
    window.theme_gallery.open_theme("standard")
    pump(1.0)
    check("min_width_fits", window.get_width() <= 420)
    window.close()


SCENARIOS = {"main": run_main, "stopped": run_stopped, "narrow": run_narrow}
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
