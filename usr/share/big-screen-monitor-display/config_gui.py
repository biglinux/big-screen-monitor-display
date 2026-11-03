#!/usr/bin/env python3
"""Big Screen Monitor Display - configuration window (GTK4 / libadwaita).

The window edits a copy of the settings, previews it live with the very same
theme renderer the service uses, and applies it through the polkit helper.
The service reloads the file within a second, so no restart is needed.
"""

import copy
import json
import os
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault("GSK_RENDERER", "cairo")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from bsmd import (APP_ID, SERVICE_NAME, __version__, dashboard, diagnostics, runtime, settings, sound,  # noqa: E402
                  telemetry, themes)
from bsmd.i18n import N_, _  # noqa: E402
from displays_page import DisplaysPage  # noqa: E402
from kojiro_page import KojiroPage  # noqa: E402

HELPER = "/usr/lib/big-screen-monitor-display/bsm-helper"
# (theme id, page builder, icon) - one customisation tab per theme
THEME_PAGES = (
    ("standard", "_page_standard", "utilities-system-monitor-symbolic"),
    ("gkrellm", "_page_gkrellm", "utilities-terminal-symbolic"),
    ("planet", "_page_planet", "weather-clear-night-symbolic"),
    ("old_computer", "_page_old_computer", "computer-symbolic"),
    ("brother_away", "_page_brother_away", "weather-clear-symbolic"),
    ("kojiro", "_page_kojiro", "image-x-generic-symbolic"),
)
SHORT_NAMES = {"brother_away": N_("Brother Away"), "kojiro": N_("Kojiro")}
OWN_PREVIEW = {"kojiro"}      # theme tabs that draw their own preview (the Design Studio)
PREVIEW_SIZES = {"3.5": (480, 320), "5": (800, 480), "8.8": (480, 320), "2.1": (480, 480)}


# ------------------------------------------------------------------ helpers

def run_helper(args, payload=None, timeout=120):
    """Run the privileged helper via pkexec. Returns (ok, message)."""
    if not os.path.exists(HELPER):
        return False, _("The administrative helper is not installed ({path}).").format(path=HELPER)
    binary = isinstance(payload, bytes)
    try:
        result = subprocess.run(["pkexec", HELPER, *args], input=payload, capture_output=True,
                                text=not binary, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if binary:
        result.stdout = result.stdout.decode("utf-8", "replace")
        result.stderr = result.stderr.decode("utf-8", "replace")
    if result.returncode in (126, 127):
        return False, _("Authorization was cancelled or denied.")
    try:
        reply = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        reply = {"ok": result.returncode == 0, "error": result.stderr.strip()}
    if reply.get("ok"):
        if "id" in reply:
            return True, reply["id"]
        problems = reply.get("problems") or []
        return True, "; ".join(problems)
    return False, reply.get("error") or result.stderr.strip() or _("Unknown error")


def save_settings(values):
    """Persist settings: directly when writable (development), else via helper."""
    path = settings.config_path()
    directory = os.path.dirname(path)
    if os.environ.get("BSM_CONFIG") or (os.path.isdir(directory) and os.access(directory, os.W_OK)):
        try:
            _clean, problems = settings.save(values, path)
            return True, "; ".join(problems)
        except OSError as error:
            return False, str(error)
    return run_helper(["apply-settings"], json.dumps(values))


def play_success_sound():
    for command in (["canberra-gtk-play", "-i", "complete"], ["canberra-gtk-play", "-i", "message"]):
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue


def set_accessible_label(widget, text):
    widget.update_property([Gtk.AccessibleProperty.LABEL], [text])


# ------------------------------------------------------------------ preview

class PreviewRenderer:
    """Renders the selected theme in a worker thread for a Gtk.Picture."""

    def __init__(self, picture):
        self.picture = picture
        self.values = None
        self.theme = None
        self.theme_key = None
        self.ctx = runtime.RenderContext(preview=True)
        self.size = (480, 320)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._pending_story = None
        self.active = True
        self._player = None
        self._sound_seq = 0
        self._rng = __import__("random").Random()
        threading.Thread(target=self._loop, name="preview", daemon=True).start()

    def update(self, values, size):
        self.values = dict(values)
        self.size = size
        self._wake.set()

    def play_story(self, story):
        self._pending_story = story
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _play_sounds(self, values):
        events = getattr(self.theme, "sound_events", None)
        if not events:
            return
        new = [(seq, event) for seq, event in list(events) if seq > self._sound_seq]
        if new:
            self._sound_seq = new[-1][0]
        if not values.get("sound_enabled"):
            return
        if self._player is None:
            self._player = sound.Player()
        for _seq, event in new:
            kind = sound.sound_for(event, values.get("ba_dialogue_frequency", "normal"), self._rng)
            if kind:
                self._player.play(kind, values.get("sound_volume", 40))

    def _loop(self):
        while not self._stop.is_set():
            values = self.values
            if values is None or not self.active:
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            width, height = self.size
            if str(values.get("orientation")).startswith("vertical") and width > height:
                width, height = height, width
            key = (values.get("theme"), width, height)
            if key != self.theme_key:
                if self.theme:
                    self.theme.close()
                self.theme = themes.create(values.get("theme"), self.ctx)
                self.theme_key = key
            if self._pending_story and hasattr(self.theme, "debug_seek"):
                self.theme.debug_seek(0.1, self._pending_story)
                self._pending_story = None
            started = time.monotonic()
            try:
                image = themes.render_for_panel(self.theme, width, height, values, self.ctx)
                interval = self.theme.frame_interval(values, self.ctx)
            except Exception as error:  # noqa: BLE001 - show the failure instead of crashing the window
                print(f"preview failed: {error!r}", file=sys.stderr)
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            self._play_sounds(values)
            data = GLib.Bytes.new(image.tobytes())
            texture = Gdk.MemoryTexture.new(image.width, image.height, Gdk.MemoryFormat.R8G8B8, data,
                                            image.width * 3)
            GLib.idle_add(self.picture.set_paintable, texture)
            remaining = max(0.05, interval - (time.monotonic() - started))
            self._wake.wait(min(remaining, 1.0))
            self._wake.clear()


# ------------------------------------------------------------------ window

class ConfigWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(_("Big Screen Monitor Display"))
        self.set_default_size(1180, 800)
        self.saved = settings.load()
        self.values = copy.deepcopy(self.saved)
        self.status = runtime.read_status()
        self._loading = True
        self._widgets = {}

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)

        header = Adw.HeaderBar()
        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        header.pack_end(self._menu_button())
        toolbar.add_top_bar(header)

        self.banner = Adw.Banner()
        self.banner.set_button_label(_("Diagnose"))
        self.banner.connect("button-clicked", lambda *_: self._show_diagnostics())
        toolbar.add_top_bar(self.banner)

        toolbar.set_content(self.stack)
        toolbar.add_bottom_bar(self._action_bar())

        # One preview for the gallery (follows the selection) and one per theme tab.
        self.pictures = {"themes": self._picture(_("Preview of the selected theme"))}
        for theme_id, _builder, _icon in THEME_PAGES:
            if theme_id in OWN_PREVIEW:
                continue
            self.pictures[theme_id] = self._picture(
                _("Preview of {theme}").format(theme=_(themes.REGISTRY[theme_id].name)))
        self.previews = {name: PreviewRenderer(picture) for name, picture in self.pictures.items()}
        self.preview_ba = self.previews["brother_away"]
        self.collector = telemetry.Collector(interval=2.0)
        self.collector.want_sensors = True      # GKrellM preview lists real sensors
        self.collector.start()

        self.stack.add_titled_with_icon(self._page_display(), "display", _("My Displays"), "video-display-symbolic")
        self.stack.add_titled_with_icon(self._page_themes(), "themes", _("Themes"), "applications-graphics-symbolic")
        # Each theme has its own customisation tab, shown only while that theme is applied.
        self.theme_pages = {}
        for theme_id, builder, icon in THEME_PAGES:
            self.theme_pages[theme_id] = self.stack.add_titled_with_icon(
                getattr(self, builder)(), f"theme_{theme_id}", _(SHORT_NAMES.get(theme_id, themes.REGISTRY[theme_id].name)),
                icon)
        self.stack.add_titled_with_icon(self._page_performance(), "performance", _("Performance"),
                                        "speedometer-symbolic")
        self.stack.add_titled_with_icon(self._page_diagnostics(), "diagnostics", _("Diagnostics"),
                                        "dialog-information-symbolic")
        self.stack.connect("notify::visible-child-name", self._on_page_changed)

        self._loading = False
        self._update_theme_pages()
        self._refresh_dirty()
        self._refresh_status()
        self._on_page_changed()
        GLib.timeout_add_seconds(2, self._refresh_status)
        self.connect("close-request", self._on_close)

    # ---------------------------------------------------------- building
    def _picture(self, description):
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
        picture.set_size_request(-1, 220)
        picture.set_alternative_text(description)
        picture.add_css_class("card")
        return picture

    def _menu_button(self):
        menu = Gio.Menu()
        menu.append(_("Restore defaults"), "win.restore")
        menu.append(_("About"), "app.about")
        menu.append(_("Quit"), "app.quit")
        button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text=_("Main menu"))
        set_accessible_label(button, _("Main menu"))
        action = Gio.SimpleAction.new("restore", None)
        action.connect("activate", lambda *_: self._confirm_restore())
        self.add_action(action)
        return button

    def _action_bar(self):
        bar = Gtk.ActionBar()
        self.changes_label = Gtk.Label(css_classes=["dim-label"])
        bar.pack_start(self.changes_label)
        self.revert_button = Gtk.Button(label=_("Discard"), tooltip_text=_("Discard unsaved changes"))
        self.revert_button.connect("clicked", lambda *_: self._revert())
        self.apply_button = Gtk.Button(label=_("Apply"), css_classes=["suggested-action"])
        self.apply_button.set_tooltip_text(_("Save and apply to the display without restarting"))
        self.apply_button.connect("clicked", lambda *_: self._apply())
        self.apply_spinner = Adw.Spinner(visible=False) if hasattr(Adw, "Spinner") else Gtk.Spinner(visible=False)
        bar.pack_end(self.apply_button)
        bar.pack_end(self.apply_spinner)
        bar.pack_end(self.revert_button)
        return bar

    def _combo(self, key, title, options, subtitle=None):
        labels = [label for _value, label in options]
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels))
        if subtitle:
            row.set_subtitle(subtitle)
        values = [value for value, _label in options]
        current = self.values.get(key)
        row.set_selected(values.index(current) if current in values else 0)
        row.connect("notify::selected", lambda r, _p: self._set(key, values[r.get_selected()]))
        self._widgets[key] = (row, values)
        return row

    def _switch(self, key, title, subtitle=None):
        row = Adw.SwitchRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        row.set_active(bool(self.values.get(key)))
        row.connect("notify::active", lambda r, _p: self._set(key, r.get_active()))
        self._widgets[key] = (row, None)
        return row

    def _scale(self, key, title, low, high, step, subtitle=None):
        row = Adw.ActionRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
        scale.set_value(self.values.get(key, low))
        scale.set_hexpand(True)
        scale.set_size_request(220, -1)
        scale.set_valign(Gtk.Align.CENTER)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        set_accessible_label(scale, title)
        scale.connect("value-changed", lambda s: self._set(key, int(s.get_value())))
        row.add_suffix(scale)
        row.set_activatable_widget(scale)
        self._widgets[key] = (scale, "scale")
        return row

    @staticmethod
    def _group(title, description=None):
        group = Adw.PreferencesGroup(title=title)
        if description:
            group.set_description(description)
        return group

    def _page_display(self):
        self.displays_page = DisplaysPage(self, run_helper)
        page = self.displays_page.page
        group = self._group(_("All displays"), _("Defaults for every display; each display above can override them."))
        self.connection_row = Adw.ActionRow(title=_("Service"), subtitle=_("Checking..."))
        self.connection_icon = Gtk.Image.new_from_icon_name("content-loading-symbolic")
        self.connection_row.add_prefix(self.connection_icon)
        group.add(self.connection_row)
        group.add(self._combo("orientation", _("Orientation"), [
            ("horizontal", _("Horizontal (landscape)")), ("vertical", _("Vertical (portrait)")),
            ("horizontal_flipped", _("Horizontal, upside down")), ("vertical_flipped", _("Vertical, upside down"))]))
        group.add(self._scale("brightness", _("Brightness"), 0, 100, 5))
        group.add(self._combo("model", _("Automatic detection"), [
            ("auto", _("All supported models")), ("ax206", _("Only AX206 (USB photo frame)")),
            ("turing", _("Only Turing Smart Screen 3.5\" (USB serial)"))],
            _("Limits which detected displays start automatically.")))
        group.add(self._combo("size", _("Preview size"), [
            ("3.5", "3.5\""), ("5", "5\""), ("8.8", "8.8\""), ("2.1", "2.1\" / 2.8\"")],
            _("Used for the preview while no display is connected.")))
        page.add(group)

        startup = self._group(_("Startup"))
        self.startup_row = Adw.SwitchRow(title=_("Start with the computer"),
                                         subtitle=_("Runs the monitor service at boot"))
        self.startup_row.set_active(diagnostics.systemctl_query("is-enabled") == "enabled")
        self.startup_row.connect("notify::active", self._on_startup_toggled)
        startup.add(self.startup_row)
        page.add(startup)
        return page

    def _page_themes(self):
        page = Adw.PreferencesPage()
        preview = self._group(_("Preview"))
        preview.add(self.pictures["themes"])
        page.add(preview)
        gallery = self._group(_("Gallery"), _("Choose a look for the display. After applying, the theme gets "
                                              "its own tab with every option."))
        self.theme_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.theme_checks = {}
        first = None
        for info in themes.available():
            row = Adw.ActionRow(title=GLib.markup_escape_text(_(info.name)),
                                subtitle=GLib.markup_escape_text(_(info.description)))
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if first is None:
                first = check
            else:
                check.set_group(first)
            check.set_active(self.values.get("theme") == info.id)
            check.connect("toggled", self._on_theme_toggled, info.id)
            set_accessible_label(check, _(info.name))
            row.add_prefix(check)
            row.set_activatable_widget(check)
            if info.animated:
                badge = Gtk.Label(label=_("Animated"), css_classes=["accent", "caption-heading"])
                row.add_suffix(badge)
            self.theme_checks[info.id] = check
            self.theme_list.append(row)
        gallery.add(self.theme_list)
        page.add(gallery)

        return page

    # ---------------------------------------------------------- theme tabs
    def _theme_preview_group(self, theme_id, title, description):
        group = self._group(title, description)
        group.add(self.pictures[theme_id])
        return group

    def _page_standard(self):
        page = Adw.PreferencesPage()
        page.add(self._theme_preview_group("standard", _("Standard"),
                                           _("One clean dashboard, measured so that nothing overlaps.")))
        look = self._group(_("Appearance"))
        look.add(self._combo("std_scheme", _("Colour scheme"),
                             [(key, _(scheme["name"])) for key, scheme in dashboard.SCHEMES.items()]))
        look.add(self._combo("std_text_size", _("Text size"), [
            ("small", _("Small")), ("normal", _("Normal")), ("large", _("Large"))]))
        look.add(self._combo("std_bar_style", _("Bar style"), [
            ("rounded", _("Rounded")), ("flat", _("Flat")), ("segmented", _("Segmented"))]))
        look.add(self._switch("std_colored_labels", _("Coloured labels")))
        look.add(self._switch("std_alert_colors", _("Alert colours"),
                              _("Bars turn orange above 75% and red above 90%.")))
        look.add(self._switch("std_history", _("History in the background"),
                              _("A faint graph of the last 30 seconds behind each item.")))
        page.add(look)

        header = self._group(_("Header"))
        header.add(self._switch("std_header", _("Show header")))
        header.add(self._switch("std_logo", _("Distribution logo")))
        header.add(self._switch("std_host_line", _("Host name and kernel")))
        header.add(self._switch("std_date", _("Date")))
        header.add(self._switch("std_clock_24h", _("24-hour clock")))
        header.add(self._switch("std_seconds", _("Show seconds")))
        page.add(header)

        items = self._group(_("Information"))
        for key, title in (("std_show_cpu", _("CPU usage and temperature")), ("std_show_ram", _("Memory")),
                           ("std_show_swap", _("Swap")), ("std_show_disk", _("Disk")),
                           ("std_show_gpu", _("GPU usage and temperature")),
                           ("std_gpu_details", _("Video memory (VRAM)")), ("std_network", _("Network traffic"))):
            items.add(self._switch(key, title))
        items.add(self._combo("std_values", _("Show values as"), [
            ("absolute", _("Used / total")), ("percent", _("Percentage"))]))
        items.add(self._combo("std_temp_unit", _("Temperature unit"), [("c", "°C"), ("f", "°F")]))
        page.add(items)

        side = self._group(_("Side panel"), _("Below the information in portrait orientation."))
        side.add(self._combo("std_side_panel", _("Content"), [
            ("processes", _("Top processes")), ("graphs", _("Graphs")), ("none", _("Nothing"))]))
        side.add(self._combo("std_process_count", _("Processes listed"),
                             [("5", "5"), ("8", "8"), ("10", "10"), ("12", "12")]))
        side.add(self._combo("std_process_sort", _("Order processes by"), [
            ("cpu", _("CPU usage")), ("memory", _("Memory usage"))]))
        side.add(self._switch("std_footer", _("Footer"), _("Uptime, load, process count and power profile.")))
        page.add(side)
        return page

    def _page_gkrellm(self):
        page = Adw.PreferencesPage()
        page.add(self._theme_preview_group("gkrellm", "GKrellM",
                                           _("Stacked monitors in the style of the classic GKrellM.")))
        look = self._group(_("Appearance"))
        look.add(self._combo("gk_theme_color", _("Visual style"), [
            ("urlicht", "Urlicht (Neon Blue)"), ("classic", _("Classic (green phosphor)")),
            ("cyber_red", "Cyber-Red")]))
        look.add(self._combo("gk_columns", _("Columns"), [
            ("auto", _("Automatic")), ("1", "1"), ("2", "2"), ("3", "3"), ("4", "4")]))
        look.add(self._combo("gk_text_size", _("Text size"), [
            ("small", _("Small")), ("normal", _("Normal")), ("large", _("Large"))]))
        look.add(self._combo("gk_chart_height", _("Chart height"), [
            ("small", _("Small")), ("normal", _("Normal")), ("large", _("Large"))]))
        look.add(self._combo("gk_disk_count", _("Partitions listed"), [("1", "1"), ("2", "2"), ("3", "3"),
                                                                      ("4", "4")]))
        page.add(look)
        modules = self._group(_("Modules"), _("Modules that do not fit on the display are skipped."))
        for key, title in (
                ("gk_show_host", _("Host name and kernel")), ("gk_show_date", _("Date")), ("gk_show_time", _("Time")),
                ("gk_show_uptime", _("Uptime")), ("gk_show_cpu", _("CPU usage")), ("gk_show_cores", _("CPU cores")),
                ("gk_show_proc", _("Processes and load")), ("gk_show_temp", _("Temperatures")),
                ("gk_show_hda", _("Disk I/O")), ("gk_show_eth0", _("Main network interface")),
                ("gk_show_inet", _("Other network interfaces")), ("gk_show_mem", _("Memory")),
                ("gk_show_swap", _("Swap")), ("gk_show_disk", _("Partitions")), ("gk_show_gpu", _("GPU")),
                ("gk_show_battery", _("Battery")), ("gk_show_sys", _("Fans and power")),
                ("gk_show_docker", _("Docker containers")), ("gk_show_devices", _("Removable media")),
                ("gk_show_media", _("Media player"))):
            modules.add(self._switch(key, title))
        page.add(modules)
        return page

    def _page_planet(self):
        page = Adw.PreferencesPage()
        page.add(self._theme_preview_group("planet", _("Planet"),
                                           _("The Earth as it is lit right now, with the real Sun and Moon positions.")))
        look = self._group(_("Appearance"))
        look.add(self._combo("planet_accent", _("Accent colour"), [
            ("blue", _("Blue")), ("green", _("Green")), ("amber", _("Amber")), ("violet", _("Violet")),
            ("red", _("Red"))]))
        look.add(self._switch("planet_seconds", _("Show seconds")))
        page.add(look)
        globe = self._group(_("Globe"))
        globe.add(self._switch("planet_night", _("Night side"), _("Shade the half of the Earth without sunlight.")))
        globe.add(self._switch("planet_city_lights", _("City lights")))
        globe.add(self._switch("planet_show_paths", _("Sun and Moon tracks"),
                               _("Where they were and will be over 24 hours.")))
        globe.add(self._switch("planet_show_moon", _("Moon")))
        page.add(globe)
        return page

    def _page_old_computer(self):
        page = Adw.PreferencesPage()
        page.add(self._theme_preview_group("old_computer", _("Old Computer"),
                                           _("A system monitor window from the classic desktop era.")))
        look = self._group(_("Appearance"))
        look.add(self._combo("oc_scheme", _("Colour scheme"), [
            ("classic", _("Classic grey")), ("slate", _("Slate (dark)")), ("amber", _("Amber")),
            ("plum", _("Plum"))]))
        look.add(self._switch("oc_titlebar", _("Title bar")))
        look.add(self._switch("oc_statusbar", _("Status bar")))
        look.add(self._switch("oc_seconds", _("Show seconds")))
        page.add(look)
        cards = self._group(_("Cards"), _("CPU and memory are always shown."))
        cards.add(self._switch("oc_show_gpu", _("GPU and video memory")))
        cards.add(self._switch("oc_show_storage", _("Disk and swap")))
        page.add(cards)
        return page

    def _page_brother_away(self):
        page = Adw.PreferencesPage()
        preview = self._group(_("Brother Away — The Perplexed Castaway!"),
                              _("A castaway with opinions about everything, on the island inside your display."))
        preview.add(self.pictures["brother_away"])
        actions = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=8)
        story_button = Gtk.MenuButton(label=_("Watch a story"), css_classes=["pill"])
        menu = Gio.Menu()
        for story_id, label in (("coconut_tree", _("The rebellious palm tree")), ("shark", _("The mocking shark")),
                                ("raft", _("The impossible raft")), ("ufo", _("The extraterrestrial encounter")),
                                ("philosopher", _("The philosopher palm tree")),
                                ("crab_glasses", _("The crab and the glasses")),
                                ("gull_lunch", _("The seagull's lunch")),
                                ("message_bottle", _("Message in a bottle"))):
            menu.append(label, f"win.story::{story_id}")
        story_button.set_menu_model(menu)
        action = Gio.SimpleAction.new("story", GLib.VariantType.new("s"))
        action.connect("activate", lambda _a, param: self.preview_ba.play_story(param.get_string()))
        self.add_action(action)
        actions.append(story_button)
        preview.add(actions)
        page.add(preview)

        anim = self._group(_("Animation"))
        anim.add(self._switch("ba_animation", _("Animate"),
                              _("When off, a still island is shown and only the data updates.")))
        anim.add(self._combo("ba_event_frequency", _("Events"), [
            ("low", _("Rare")), ("normal", _("Normal")), ("high", _("Frequent"))]))
        anim.add(self._switch("ba_day_night", _("Day and night cycle"), _("Follows the computer clock.")))
        anim.add(self._switch("ba_weather", _("Weather"), _("Wind, rain, storms, fog and rainbows (simulated).")))
        anim.add(self._switch("ba_story_continuity", _("Story continuity"),
                              _("The raft and the souvenirs are kept between sessions.")))
        anim.add(self._switch("ba_telemetry_reactions", _("React to the computer"),
                              _("Heat, busy memory, full disk and a busy GPU change the island.")))
        page.add(anim)

        humor = self._group(_("Humour and speech"))
        humor.add(self._combo("ba_humor", _("Humour"), [
            ("family", _("Family")), ("classic", _("Classic")), ("adult", _("Sarcastic"))]))
        humor.add(self._switch("ba_catchphrases", _("Classic catchphrases"),
                               _("Tributes such as \"AWAAAAAY!\" and \"morô?\".")))
        humor.add(self._switch("ba_subtitles", _("Speech balloons")))
        page.add(humor)

        audio = self._group(_("Sound"), _("Played by this computer: the display has no speaker. Off by default."))
        audio.add(self._switch("sound_enabled", _("Retro sound effects")))
        audio.add(self._scale("sound_volume", _("Volume"), 0, 100, 5))
        audio.add(self._combo("ba_dialogue_frequency", _("Speech sounds"), [
            ("low", _("Rare")), ("normal", _("Normal")), ("high", _("Frequent"))]))
        page.add(audio)

        hud = self._group(_("Telemetry overlay"), _("Clock, CPU, RAM, disk and GPU over the scene."))
        hud.add(self._switch("overlay_enabled", _("Show overlay")))
        hud.add(self._combo("overlay_size", _("Size"), [("expanded", _("Expanded")), ("compact", _("Compact"))]))
        hud.add(self._combo("overlay_position", _("Position"), [
            ("top_left", _("Top left")), ("top_right", _("Top right")),
            ("bottom_left", _("Bottom left")), ("bottom_right", _("Bottom right"))]))
        hud.add(self._scale("overlay_opacity", _("Background opacity"), 0, 100, 5))
        hud.add(self._switch("overlay_auto_dim", _("Shrink during stories"),
                             _("The overlay becomes compact while something important happens.")))
        sensors = Adw.ExpanderRow(title=_("Visible information"))
        for key, title in (("overlay_show_clock", _("Clock")), ("overlay_show_cpu", "CPU"),
                           ("overlay_show_ram", "RAM"), ("overlay_show_disk", _("Disk")),
                           ("overlay_show_gpu", "GPU")):
            sensors.add_row(self._switch(key, title))
        hud.add(sensors)
        page.add(hud)
        return page

    def _page_kojiro(self):
        self.kojiro_page = KojiroPage(self, run_helper)
        return self.kojiro_page.widget

    def _page_performance(self):
        page = Adw.PreferencesPage()
        group = self._group(_("Performance"))
        group.add(self._combo("performance_profile", _("Profile"), [
            ("auto", _("Automatic (recommended)")), ("economy", _("Economy")),
            ("balanced", _("Balanced")), ("fluid", _("Fluid"))],
            _("Automatic adapts the frame rate to the panel speed, the computer and battery use.")))
        page.add(group)
        live = self._group(_("Measured now"), _("Reported by the running service."))
        self.perf_rows = {}
        for key, title in (("cpu", _("Service CPU")), ("ram", _("Service memory")), ("fps", _("Frames per second")),
                           ("usb", _("Transfer time")), ("data", _("Data sent")), ("drop", _("Frames skipped"))):
            row = Adw.ActionRow(title=title, subtitle="—")
            row.set_subtitle_selectable(True)
            self.perf_rows[key] = row
            live.add(row)
        page.add(live)
        return page

    def _page_diagnostics(self):
        page = Adw.PreferencesPage()
        state = self._group(_("Current state"))
        self.diag_rows = {}
        for key, title in (("service", _("Service")), ("device", _("Display")),
                           ("last", _("Last confirmed transfer")), ("recoveries", _("Automatic recoveries")),
                           ("pipeline", _("Pipeline"))):
            row = Adw.ActionRow(title=title, subtitle="—")
            self.diag_rows[key] = row
            state.add(row)
        page.add(state)

        tools = self._group(_("Tools"))
        diagnose = Adw.ButtonRow(title=_("Diagnose my display")) if hasattr(Adw, "ButtonRow") else None
        if diagnose is not None:
            diagnose.add_css_class("suggested-action")
            diagnose.connect("activated", lambda *_: self._run_diagnostics())
            tools.add(diagnose)
        else:
            button = Gtk.Button(label=_("Diagnose my display"), css_classes=["suggested-action"])
            button.connect("clicked", lambda *_: self._run_diagnostics())
            tools.add(button)
        for title, subtitle, callback in (
                (_("Recover the display now"), _("Reconnects and redraws without restarting the service."),
                 lambda *_: self._helper_action(["recover"], _("Recovery requested."))),
                (_("Restart the service"), _("Use if the display stays frozen."),
                 lambda *_: self._helper_action(["service", "restart"], _("Service restarted."))),
                (_("Export diagnostics"), _("Saves a report to share when asking for help."),
                 lambda *_: self._export())):
            row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", callback)
            tools.add(row)
        page.add(tools)

        self.results_group = self._group(_("Diagnosis"))
        self.results_group.set_visible(False)
        page.add(self.results_group)
        self._result_rows = []

        self.incidents_group = self._group(_("Recent events"))
        self._incident_rows = []
        page.add(self.incidents_group)

        feedback = self._group(_("Feedback"))
        feedback.add(self._switch("ui_sound_feedback", _("Sound after applying"),
                                  _("Plays a short system sound when settings are applied.")))
        page.add(feedback)
        return page

    # ---------------------------------------------------------- state
    def _set(self, key, value):
        if self._loading:
            return
        self.values[key] = value
        self._refresh_dirty()

    def _on_theme_toggled(self, check, theme_id):
        if check.get_active():
            self._set("theme", theme_id)

    def _refresh_dirty(self):
        dirty = {k for k in self.values if self.values[k] != self.saved.get(k)}
        self.apply_button.set_sensitive(bool(dirty))
        self.revert_button.set_sensitive(bool(dirty))
        self.changes_label.set_label(_("Unsaved changes") if dirty else "")
        size = self._device_size()
        self.previews["themes"].update(self.values, size)
        for theme_id, _builder, _icon in THEME_PAGES:
            if theme_id in self.previews:
                self.previews[theme_id].update(dict(self.values, theme=theme_id), size)

    def _device_size(self):
        device = (self.status or {}).get("device")
        if device:
            return device["width"], device["height"]
        return PREVIEW_SIZES.get(self.values.get("size"), (480, 320))

    def _reload_widgets(self):
        self._loading = True
        for key, (widget, extra) in self._widgets.items():
            value = self.values.get(key)
            if extra == "scale":
                widget.set_value(value)
            elif extra is None:
                widget.set_active(bool(value))
            else:
                widget.set_selected(extra.index(value) if value in extra else 0)
        for theme_id, check in self.theme_checks.items():
            check.set_active(self.values.get("theme") == theme_id)
        self._loading = False
        self.displays_page.refresh(force=True)
        if hasattr(self, "kojiro_page"):
            self.kojiro_page.reload()
        self._refresh_dirty()

    def _revert(self):
        self.values = copy.deepcopy(self.saved)
        self._reload_widgets()

    def _confirm_restore(self):
        dialog = Adw.AlertDialog(heading=_("Restore defaults?"),
                                 body=_("All options go back to their original values. "
                                        "Nothing changes on the display until you press Apply."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("restore", _("Restore"))
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", lambda _d, response: response == "restore" and self._restore())
        dialog.present(self)

    def _restore(self):
        self.values = settings.defaults()
        self._reload_widgets()
        self.toast(_("Defaults loaded. Press Apply to use them."))

    def _apply(self):
        values = copy.deepcopy(self.values)
        self.apply_button.set_sensitive(False)
        self.apply_spinner.set_visible(True)
        if isinstance(self.apply_spinner, Gtk.Spinner):
            self.apply_spinner.start()

        def worker():
            ok, message = save_settings(values)
            GLib.idle_add(self._applied, ok, message, values)

        threading.Thread(target=worker, daemon=True).start()

    def _applied(self, ok, message, values):
        self.apply_spinner.set_visible(False)
        if ok:
            theme_changed = values.get("theme") != self.saved.get("theme")
            self.saved = values
            self._update_theme_pages(announce=theme_changed)
            self._refresh_dirty()
            self._update_sound_agent(values)
            self.toast(_("Settings applied. The display updates in a moment."))
            if message:
                self.toast(_("Some values were corrected: {details}").format(details=message))
            if values.get("ui_sound_feedback"):
                play_success_sound()
        else:
            self._refresh_dirty()
            self._error(_("Could not apply the settings"), message)

    def _update_sound_agent(self, values):
        enabled = bool(values.get("sound_enabled"))
        main_py = os.path.join(BASE_DIR, "main.py")
        try:
            sound.set_autostart(enabled, main_py)
            if enabled:
                subprocess.Popen([sys.executable, main_py, "--sound-agent"], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            self.toast(_("Could not configure the sound agent: {error}").format(error=error))

    def _helper_action(self, args, success):
        def worker():
            ok, message = run_helper(args)
            GLib.idle_add(lambda: self.toast(success) if ok else self._error(_("Operation failed"), message))
        threading.Thread(target=worker, daemon=True).start()

    def _on_startup_toggled(self, row, _pspec):
        if self._loading:
            return
        verb = "enable" if row.get_active() else "disable"
        row.set_sensitive(False)

        def worker():
            ok, message = run_helper(["service", verb])

            def done():
                row.set_sensitive(True)
                if ok:
                    self.toast(_("The service will start with the computer.") if verb == "enable"
                               else _("The service will no longer start with the computer."))
                else:
                    self._loading = True
                    row.set_active(not row.get_active())
                    self._loading = False
                    self._error(_("Could not change the startup setting"), message)
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=4))

    def _error(self, heading, body):
        dialog = Adw.AlertDialog(heading=heading, body=body or _("Unknown error"))
        dialog.add_response("ok", _("Close"))
        dialog.present(self)

    def _on_page_changed(self, *_args):
        name = self.stack.get_visible_child_name()
        for key, preview in self.previews.items():
            preview.active = name == ("themes" if key == "themes" else f"theme_{key}")
            preview._wake.set()
        if hasattr(self, "kojiro_page"):
            self.kojiro_page.set_active(name == "theme_kojiro")

    def _update_theme_pages(self, announce=False):
        """Show only the customisation tab of the applied (saved) theme."""
        applied = self.saved.get("theme")
        per_display = {entry.get("theme") for entry in (self.saved.get("displays") or {}).values()
                       if isinstance(entry, dict)}
        for theme_id, page in self.theme_pages.items():
            page.set_visible(theme_id == applied or theme_id in per_display)
        if self.stack.get_visible_child_name() not in (None, f"theme_{applied}") and \
                self.stack.get_visible_child_name().startswith("theme_"):
            self.stack.set_visible_child_name("themes")
        if announce and applied in self.theme_pages:
            toast = Adw.Toast(title=_("Theme applied. Customise it in the “{name}” tab.").format(
                name=_(SHORT_NAMES.get(applied, themes.REGISTRY[applied].name))), timeout=6)
            toast.set_button_label(_("Customise"))
            toast.connect("button-clicked", lambda *_: self.stack.set_visible_child_name(f"theme_{applied}"))
            self.toasts.add_toast(toast)

    # ---------------------------------------------------------- status
    def _refresh_status(self):
        self.status = runtime.read_status()
        status = self.status
        self.displays_page.refresh()
        path = runtime.find_status_file()
        fresh = status is not None and path is not None and time.time() - os.path.getmtime(path) < 15
        if not fresh:
            self.connection_row.set_subtitle(_("The service is not running."))
            self.connection_icon.set_from_icon_name("dialog-warning-symbolic")
            self.banner.set_title(_("The monitor service is not running."))
            self.banner.set_revealed(True)
            for row in self.diag_rows.values():
                row.set_subtitle("—")
            self.diag_rows["service"].set_subtitle(diagnostics.systemctl_query("is-active"))
            return True
        state = status.get("state")
        description = diagnostics.describe_state(status)
        ok = state == "healthy"
        self.connection_row.set_subtitle(description)
        self.connection_icon.set_from_icon_name("emblem-ok-symbolic" if ok else "dialog-warning-symbolic")
        self.banner.set_title(description)
        self.banner.set_revealed(state in ("disconnected", "retrying", "failed") or bool(status.get("stalled")))
        stats, proc = status.get("stats", {}), status.get("process", {})
        device = status.get("device") or {}
        self.diag_rows["service"].set_subtitle(_("Running for {time}").format(time=_duration(status.get("uptime_s", 0))))
        location = f" · {device['location']}" if device.get("location") else ""
        self.diag_rows["device"].set_subtitle(description.rstrip(".") + location)
        age = stats.get("last_transfer_age_s")
        self.diag_rows["last"].set_subtitle(_("{seconds:.0f} s ago").format(seconds=age) if age is not None
                                            else _("Nothing sent yet"))
        self.diag_rows["recoveries"].set_subtitle(str(status.get("recoveries", 0)))
        self.diag_rows["pipeline"].set_subtitle(_("A thread stopped making progress.") if status.get("stalled")
                                                else _("Telemetry, rendering and transfer are progressing."))
        self.perf_rows["cpu"].set_subtitle(f"{proc.get('cpu_percent', 0):.1f} %")
        self.perf_rows["ram"].set_subtitle(f"{proc.get('rss_mb', 0):.0f} MB")
        self.perf_rows["fps"].set_subtitle(_("{fps:.1f} (target {target:g})").format(
            fps=min(stats.get("fps", 0), stats.get("target_fps", 0) or 99), target=stats.get("target_fps", 0)))
        self.perf_rows["usb"].set_subtitle(f"{stats.get('transfer_ms', 0):.1f} ms")
        self.perf_rows["data"].set_subtitle(f"{stats.get('bytes_sent', 0) / 1048576:.1f} MB · "
                                            + _("{frames} frames").format(frames=stats.get("frames_sent", 0)))
        self.perf_rows["drop"].set_subtitle(str(stats.get("frames_dropped", 0)))
        self._show_incidents(status.get("incidents", []))
        return True

    def _show_incidents(self, incidents):
        for row in self._incident_rows:
            self.incidents_group.remove(row)
        self._incident_rows = []
        for incident in list(reversed(incidents))[:12]:
            icon = {"info": "emblem-ok-symbolic", "warning": "dialog-warning-symbolic"}.get(
                incident.get("severity"), "dialog-error-symbolic")
            row = Adw.ActionRow(title=incident.get("message", ""), subtitle=incident.get("time", "")[:19].replace("T", " "))
            row.set_title_lines(2)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            self.incidents_group.add(row)
            self._incident_rows.append(row)
        if not incidents:
            row = Adw.ActionRow(title=_("No events recorded."))
            self.incidents_group.add(row)
            self._incident_rows.append(row)

    def _show_diagnostics(self):
        self.stack.set_visible_child_name("diagnostics")
        self._run_diagnostics()

    def _run_diagnostics(self):
        def worker():
            report = diagnostics.run_checks()
            GLib.idle_add(self._show_report, report)
        threading.Thread(target=worker, daemon=True).start()

    def _show_report(self, report):
        for row in self._result_rows:
            self.results_group.remove(row)
        self._result_rows = []
        for check in report["checks"]:
            icon = "emblem-ok-symbolic" if check["ok"] else (
                "dialog-error-symbolic" if check["severity"] == "error" else "dialog-warning-symbolic")
            row = Adw.ActionRow(title=check["title"], subtitle=check["detail"])
            row.set_subtitle_lines(3)
            image = Gtk.Image.new_from_icon_name(icon)
            set_accessible_label(image, _("OK") if check["ok"] else _("Problem"))
            row.add_prefix(image)
            fix = check.get("fix")
            if fix:
                labels = {"restart": _("Restart service"), "recover": _("Recover"), "enable": _("Enable"),
                          "migrate": _("Import")}
                args = {"restart": ["service", "restart"], "recover": ["recover"], "enable": ["service", "enable"],
                        "migrate": ["migrate"]}[fix]
                button = Gtk.Button(label=labels[fix], valign=Gtk.Align.CENTER)
                button.connect("clicked", lambda _b, a=args: self._helper_action(a, _("Done.")))
                row.add_suffix(button)
            self.results_group.add(row)
            self._result_rows.append(row)
        self.results_group.set_visible(True)
        problems = sum(1 for c in report["checks"] if not c["ok"])
        self.toast(_("No problems found.") if not problems else
                   _("{count} item(s) need attention.").format(count=problems))

    def _export(self):
        dialog = Gtk.FileDialog(title=_("Export diagnostics"),
                                initial_name=f"big-screen-monitor-{time.strftime('%Y%m%d-%H%M%S')}.txt")
        dialog.save(self, None, self._export_finish)

    def _export_finish(self, dialog, result):
        try:
            target = dialog.save_finish(result)
        except GLib.Error:
            return
        path = target.get_path()

        def worker():
            report = diagnostics.run_checks()
            parts = [f"Big Screen Monitor Display {__version__}", time.strftime("%Y-%m-%d %H:%M:%S"), "",
                     diagnostics.format_report(report), "", "== status.json ==",
                     json.dumps(report.get("status"), indent=2, ensure_ascii=False), "", "== journal =="]
            try:
                parts.append(subprocess.run(["journalctl", "-u", SERVICE_NAME, "-n", "300", "--no-pager"],
                                            capture_output=True, text=True, timeout=10, check=False).stdout
                             or _("(journal not readable by this user)"))
            except (OSError, subprocess.SubprocessError) as error:
                parts.append(str(error))
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("\n".join(parts))
                GLib.idle_add(self.toast, _("Report saved to {path}").format(path=path))
            except OSError as error:
                GLib.idle_add(self._error, _("Could not save the report"), str(error))
        threading.Thread(target=worker, daemon=True).start()

    def _on_close(self, *_args):
        for preview in self.previews.values():
            preview.stop()
        if hasattr(self, "kojiro_page"):
            self.kojiro_page.close()
        self.collector.stop()
        return False


def _duration(seconds):
    seconds = int(seconds or 0)
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


class ConfigApp(Adw.Application):
    def __init__(self, screenshot=None, page=None):
        super().__init__(application_id="br.com.biglinux.BigScreenMonitorDisplay",
                         flags=Gio.ApplicationFlags.NON_UNIQUE if screenshot else Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_prgname(APP_ID)
        GLib.set_application_name(_("Big Screen Monitor Display"))
        self.screenshot = screenshot
        self.page = page

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = ConfigWindow(application=self)
            for name, callback in (("about", self._about), ("quit", lambda *_: window.close())):
                action = Gio.SimpleAction.new(name, None)
                action.connect("activate", callback)
                self.add_action(action)
            self.set_accels_for_action("app.quit", ["<Control>q"])
            if self.page:
                window.stack.set_visible_child_name(self.page)
        window.present()
        if self.screenshot:
            GLib.timeout_add(2500, self._save_screenshot, window)

    def _save_screenshot(self, window):
        """Development helper (--screenshot): render the window to a PNG."""
        paintable = Gtk.WidgetPaintable.new(window)
        width, height = window.get_width(), window.get_height()
        snapshot = Gtk.Snapshot()
        paintable.snapshot(snapshot, width, height)
        node = snapshot.to_node()
        if node is not None:
            texture = window.get_native().get_renderer().render_texture(node, None)
            texture.save_to_png(self.screenshot)
        self.quit()
        return False

    def _about(self, *_args):
        about = Adw.AboutDialog(
            application_name=_("Big Screen Monitor Display"), application_icon=APP_ID, version=__version__,
            developers=["Rafael Ruscher", "BigLinux Team"], copyright="© 2026 BigLinux Team",
            license_type=Gtk.License.GPL_3_0, website="https://github.com/biglinux/big-screen-monitor-display",
            issue_url="https://github.com/biglinux/big-screen-monitor-display/issues",
            comments=_("Free hardware monitor for small USB displays, with themes and the Brother Away island."))
        about.present(self.props.active_window)


def main(argv):
    screenshot = page = None
    args = list(argv[1:])
    if "--screenshot" in args:
        index = args.index("--screenshot")
        screenshot = args[index + 1]
        del args[index:index + 2]
    if "--page" in args:
        index = args.index("--page")
        page = args[index + 1]
        del args[index:index + 2]
    return ConfigApp(screenshot, page).run([argv[0], *args])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
