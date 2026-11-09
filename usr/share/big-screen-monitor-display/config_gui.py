#!/usr/bin/env python3
"""Big Screen Monitor Display - configuration window (GTK4 / libadwaita).

Layout (AshyWall design family): a sidebar with grouped sections, and a
content area where each section is an ``Adw.NavigationView`` (galleries
push detail pages). Sections are built the first time they are shown.

Editing model: every control edits ``self.values`` (a copy of the settings);
previews follow at once; a bar at the bottom shows pending changes, and
"Apply" saves them through the polkit helper (validated, atomic). The
service reloads the file within a second, so nothing restarts.
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
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from bsmd import (APP_ID, SERVICE_NAME, __version__, dashboard, diagnostics, runtime, settings, sound,  # noqa: E402
                  telemetry, themes)
from bsmd.i18n import N_, _  # noqa: E402
from displays_page import DisplaysPage  # noqa: E402
from gui import components as ui  # noqa: E402
from gui import deepcool_page, smartmonitor_view  # noqa: E402
from gui.brother_away_page import BrotherAwayPage  # noqa: E402
from gui.dashboard import Dashboard  # noqa: E402
from gui.preferences_page import PreferencesPage, apply_style, load_gui_settings  # noqa: E402
from gui.theme_gallery import ThemeGallery  # noqa: E402

HELPER = "/usr/lib/big-screen-monitor-display/bsm-helper"
# (key, sidebar group, title, icon) in sidebar order.
SECTIONS = (
    ("home", N_("Overview"), N_("Home"), "go-home-symbolic"),
    ("displays", N_("Overview"), N_("My Displays"), "video-display-symbolic"),
    ("themes", N_("Customise"), N_("Theme Gallery"), "view-grid-symbolic"),
    ("kojiro", N_("Customise"), N_("Kojiro Design Studio"), "applications-graphics-symbolic"),
    ("big_media_player", N_("Customise"), N_("Big Media Player"), "audio-x-generic-symbolic"),
    ("brother_away", N_("Customise"), N_("Brother Away"), "weather-clear-symbolic"),
    ("performance", N_("System"), N_("Performance"), "speedometer-symbolic"),
    ("diagnostics", N_("System"), N_("Diagnostics"), "utilities-system-monitor-symbolic"),
    ("preferences", N_("System"), N_("Preferences"), "preferences-system-symbolic"),
)
SECTION_TITLES = {key: title for key, _group, title, _icon in SECTIONS}
PREVIEW_SIZES = {"3.5": (480, 320), "5": (800, 480), "8.8": (480, 320), "2.1": (480, 480)}
# Expected effect of each profile (limits from the code, not measurements).
PROFILE_EFFECT = {
    "auto": N_("Up to {fps:g} frames per second in animated themes, less on slow serial panels, on battery or "
               "when the computer is busy. Hardware data every {telemetry:g} s."),
    "economy": N_("Up to {fps:g} frames per second; dashboards redrawn every {period:g} s; hardware data every "
                  "{telemetry:g} s. Lowest CPU use."),
    "balanced": N_("Up to {fps:g} frames per second; dashboards redrawn every {period:g} s; hardware data every "
                   "{telemetry:g} s."),
    "fluid": N_("Up to {fps:g} frames per second for smoother animation; dashboards every {period:g} s; hardware "
                "data every {telemetry:g} s. Uses more CPU."),
}
PROFILE_TITLE = {"auto": N_("Automatic"), "economy": N_("Economy"), "balanced": N_("Balanced"), "fluid": N_("Fluid")}
PROFILE_ICON = {"auto": "emblem-system-symbolic", "economy": "power-profile-power-saver-symbolic",
                "balanced": "power-profile-balanced-symbolic", "fluid": "power-profile-performance-symbolic"}


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


class _Groups(list):
    """Collects the PreferencesGroups a theme option builder creates."""

    def add(self, group):
        self.append(group)


# ------------------------------------------------------------------ preview

class PreviewRenderer:
    """Renders a theme in a worker thread for a Gtk.Picture.

    Sleeps (no wake-ups at all) while ``active`` is False: the window turns
    it on only while its picture is on screen.
    """

    def __init__(self, picture, max_fps=None):
        self.picture = picture
        self.max_fps = max_fps
        self.values = None
        self.face = None            # telemetry devices (DeepCool): callable drawing the cooler's face
        self.theme = None
        self.theme_key = None
        self.ctx = runtime.RenderContext(preview=True)
        self.size = (480, 320)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._pending_story = None
        self.active = True
        self.still = False
        self._stale = True
        self._player = None
        self._sound_seq = 0
        self._rng = __import__("random").Random()
        self.frames = 0
        threading.Thread(target=self._loop, name="preview", daemon=True).start()

    def update(self, values, size):
        self.values = dict(values)
        self.size = size
        self._stale = True
        self._wake.set()

    def set_active(self, active, still=False):
        """``active``: animate. ``still``: on screen but paused (window unfocused): draw the
        current state once per change, then sleep."""
        self.active = active
        self.still = still
        self._stale = True
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
            if values is None or not (self.active or (self.still and self._stale)):
                self._wake.wait()
                self._wake.clear()
                continue
            self._stale = False
            face = self.face
            if face is not None:
                try:
                    texture = ui.texture_from_image(face())
                except Exception as error:  # noqa: BLE001 - show the failure instead of crashing the window
                    print(f"preview failed: {error!r}", file=sys.stderr)
                    texture = None
                if texture is not None:
                    self.frames += 1
                    GLib.idle_add(self.picture.set_paintable, texture)
                self._wake.wait(1.0)
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
                if self.max_fps:
                    # Overview previews: dashboards (no animation) once per second, the clock's pace.
                    fps = self.max_fps if self.theme.info.animated else min(self.max_fps, 1.0)
                    interval = max(interval, 1.0 / fps)
            except Exception as error:  # noqa: BLE001 - show the failure instead of crashing the window
                print(f"preview failed: {error!r}", file=sys.stderr)
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            self._play_sounds(values)
            texture = ui.texture_from_image(image)
            self.frames += 1
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
        self.set_size_request(360, 480)
        ui.load_css()
        apply_style(load_gui_settings().get("style", "system"))
        self.saved = settings.load()
        self.values = copy.deepcopy(self.saved)
        self.status = runtime.read_status()
        self.service_fresh = self._status_fresh()
        self._loading = True
        self._widgets = {}
        self._previews = []
        self._banners = {}
        self._closed = False
        self.welcome_dismissed = False
        self.current_section = None
        self.sections = {}
        self.thumbnailer = ui.Thumbnailer()
        self.worker = ui.SerialWorker()
        self.collector = telemetry.Collector(interval=2.0)
        self.collector.want_sensors = True      # GKrellM preview lists real sensors
        self.collector.start()

        self.startup_row = Adw.SwitchRow(title=_("Start with the computer"),
                                         subtitle=_("Runs the monitor service at boot"))
        self.startup_row.connect("notify::active", self._on_startup_toggled)
        self.worker.submit("startup", lambda: diagnostics.systemctl_query("is-enabled"),
                           self._startup_state)

        self.displays_page = DisplaysPage(self, run_helper)
        self.displays_page.add_defaults(self._global_display_group())

        self.content_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120,
                                       hhomogeneous=False, vhomogeneous=False)
        content = Adw.ToolbarView(content=self.content_stack)
        content.add_bottom_bar(self._pending_bar())
        self.content_page = Adw.NavigationPage(child=content, title=_("Home"))
        self.split = Adw.NavigationSplitView(sidebar=self._build_sidebar(), content=self.content_page,
                                             min_sidebar_width=220, max_sidebar_width=280)
        ui.ADAPTIVE.attach(self, collapse_targets=[(self.split, "collapsed", True)])
        self.toasts = Adw.ToastOverlay(child=self.split)
        self.set_content(self.toasts)
        self._install_actions()

        self._loading = False
        self.show_section("home")
        self._refresh_dirty()
        self._refresh_status()
        self._status_source = GLib.timeout_add_seconds(2, self._refresh_status)
        self.connect("close-request", self._on_close)
        # Previews pause while the window is in the background or minimised.
        self.connect("notify::is-active", lambda *_: self._focus_changed())
        self.connect("notify::suspended", lambda *_: self._focus_changed())

    def _focused(self):
        suspended = self.get_suspended() if hasattr(self, "get_suspended") else False
        return (self.is_active() or os.environ.get("BSM_PREVIEW_ALWAYS")) and not suspended

    def _focus_changed(self):
        focused = self._focused()
        for entry in self._previews:
            mapped = entry.get("mapped", False)
            entry["renderer"].set_active(mapped and focused, still=mapped)

    # ---------------------------------------------------------- sidebar
    def _build_sidebar(self):
        self.sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.sidebar.add_css_class("navigation-sidebar")
        set_accessible_label(self.sidebar, _("Sections"))
        self.sidebar_rows = {}
        self.sidebar_suffix = {}
        for key, group, title, icon in SECTIONS:
            box = Gtk.Box(spacing=12)
            box.append(Gtk.Image(icon_name=icon))
            box.append(Gtk.Label(label=_(title), xalign=0, hexpand=True))
            suffix = Gtk.Label(visible=False)
            suffix.add_css_class("dim-label")
            suffix.add_css_class("numeric")
            box.append(suffix)
            row = Gtk.ListBoxRow(child=box)
            row.key, row.group = key, group
            set_accessible_label(row, _(title))
            self.sidebar_rows[key] = row
            self.sidebar_suffix[key] = suffix
            self.sidebar.append(row)
        self.sidebar.set_header_func(self._sidebar_header)
        self.sidebar.connect("row-activated", lambda _l, row: self.show_section(row.key))

        menu = Gio.Menu()
        main = Gio.Menu()
        main.append(_("Restore Defaults…"), "win.restore")
        main.append(_("Preferences"), "win.section::preferences")
        menu.append_section(None, main)
        app = Gio.Menu()
        app.append(_("About Big Screen Monitor Display"), "app.about")
        app.append(_("Quit"), "app.quit")
        menu.append_section(None, app)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=_("Big Screen Monitor")))
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text=_("Main Menu")))

        self.status_dot = Gtk.Box(valign=Gtk.Align.CENTER)
        self.status_dot.add_css_class("sidebar-dot")
        self.status_label = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.status_label.add_css_class("caption")
        status = Gtk.Box(spacing=10)
        status.add_css_class("sidebar-status")
        status.append(self.status_dot)
        status.append(self.status_label)
        status_button = Gtk.Button(child=status, tooltip_text=_("Open the diagnostics"))
        status_button.add_css_class("flat")
        status_button.connect("clicked", lambda _b: self.show_section("diagnostics"))

        toolbar = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=self.sidebar,
                                                             hscrollbar_policy=Gtk.PolicyType.NEVER))
        toolbar.add_top_bar(header)
        toolbar.add_bottom_bar(status_button)
        return Adw.NavigationPage(child=toolbar, title=_("Big Screen Monitor"))

    @staticmethod
    def _sidebar_header(row, before):
        if before is not None and before.group == row.group:
            row.set_header(None)
            return
        label = Gtk.Label(label=_(row.group), xalign=0, margin_start=12, margin_top=12 if before else 6,
                          margin_bottom=6)
        label.add_css_class("heading")
        label.add_css_class("dim-label")
        row.set_header(label)

    # ---------------------------------------------------------- sections
    def section_keys(self):
        return [key for key, *_rest in SECTIONS]

    def show_section(self, key):
        if key not in SECTION_TITLES:
            return
        if key not in self.sections:
            nav = Adw.NavigationView()
            nav.add(self._build_section(key, nav))
            self.sections[key] = nav
            self.content_stack.add_named(nav, key)
        previous, self.current_section = self.current_section, key
        self.content_stack.set_visible_child_name(key)
        self.content_page.set_title(_(SECTION_TITLES[key]))
        self.sidebar.select_row(self.sidebar_rows[key])
        self.split.set_show_content(True)
        if previous == "kojiro" and key != "kojiro":
            self.kojiro_page.set_active(False)
        if key == "kojiro":
            self.kojiro_page.set_active(True)
        if hasattr(self, "media_page"):
            self.media_page.set_active(key == "big_media_player")
        if key == "home":
            self.dashboard.update()
        elif key == "diagnostics":
            self._refresh_diagnostics()
        elif key == "performance":
            self._refresh_perf()

    def _build_section(self, key, nav):
        if key == "home":
            self.dashboard = Dashboard(self)
            return self.dashboard.page
        if key == "displays":
            self.displays_page.nav = nav
            return self.displays_page.page
        if key == "themes":
            self.theme_gallery = ThemeGallery(self, nav)
            return self.theme_gallery.page
        if key == "kojiro":
            from kojiro_page import KojiroPage
            self.kojiro_page = KojiroPage(self, run_helper)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.append(self.theme_banner("kojiro"))
            self.kojiro_page.widget.set_vexpand(True)
            box.append(self.kojiro_page.widget)
            return ui.navigation_page(_("Kojiro Design Studio"), box, tag="kojiro")
        if key == "big_media_player":
            from media_player_page import MediaPlayerPage
            self.media_page = MediaPlayerPage(self, run_helper, nav)
            return self.media_page.page
        if key == "brother_away":
            self.brother_away_page = BrotherAwayPage(self)
            return self.brother_away_page.page
        if key == "performance":
            return self._page_performance()
        if key == "diagnostics":
            return self._page_diagnostics()
        self.preferences_page = PreferencesPage(self)
        return self.preferences_page.page

    def theme_banner(self, theme_id):
        """'This theme is not on any display' banner with a one-click choice."""
        banner = Adw.Banner(title=_("This theme is not in use on any display."), button_label=_("Use It"))
        banner.connect("button-clicked", lambda _b: (self._set("theme", theme_id),
                                                     self.toast(_("Theme selected. Press Apply to send it to the "
                                                                  "display."))))
        self._banners[theme_id] = banner
        self._update_banner(theme_id)
        return banner

    @staticmethod
    def _theme_used(theme_id, values):
        return values.get("theme") == theme_id or any(
            isinstance(entry, dict) and entry.get("theme") == theme_id
            for entry in (values.get("displays") or {}).values())

    def _update_banner(self, theme_id):
        banner = self._banners.get(theme_id)
        if banner is not None:
            banner.set_revealed(not self._theme_used(theme_id, self.values))

    # ---------------------------------------------------------- previews
    def live_preview(self, theme_id, description, height=300, follow_display=False, max_fps=None):
        """A display preview rendered by the real theme engine; it renders only while on screen."""
        frame = ui.DisplayPreview(description, height=height)
        renderer = PreviewRenderer(frame.picture, max_fps)
        renderer.active = False
        entry = {"frame": frame, "renderer": renderer, "theme": theme_id, "display": None,
                 "follow": follow_display}
        entry["mapped"] = False

        def visible_changed(_frame, visible):
            entry["mapped"] = visible
            renderer.set_active(visible and self._focused(), still=visible)
        frame.connect("visible-changed", visible_changed)
        self._previews.append(entry)
        self._update_preview(entry)
        return frame

    def renderer_of(self, frame):
        return next(entry["renderer"] for entry in self._previews if entry["frame"] is frame)

    def set_preview_display(self, frame, display_id):
        for entry in self._previews:
            if entry["frame"] is frame:
                entry["display"] = display_id
                self._update_preview(entry)

    def _display_size(self, display_id):
        for display in (self.status or {}).get("displays") or []:
            device = display.get("device") if display.get("id") == display_id else None
            if device and device.get("width") and device.get("height"):
                return device["width"], device["height"]
        return None

    def _update_preview(self, entry):
        face = deepcool_page.face_renderer(self, entry["display"]) if entry["display"] else None
        face_size = deepcool_page.PREVIEW_SIZE
        if face is None and entry["display"]:
            face = smartmonitor_view.face_renderer(self, entry["display"])
            face_size = smartmonitor_view.PREVIEW_SIZE
        entry["renderer"].face = face
        if face is not None:
            entry["frame"].set_ratio(*face_size)
            entry["renderer"].update(settings.merged(self.values, entry["display"]), face_size)
            return
        size = self._display_size(entry["display"]) if entry["display"] else None
        if entry["display"]:
            values = settings.merged(self.values, entry["display"])
        elif entry["theme"]:
            values = dict(self.values, theme=entry["theme"])
        else:
            values = self.values
        size = size or self._device_size()
        width, height = size
        if str(values.get("orientation")).startswith("vertical") and width > height:
            width, height = height, width
        entry["frame"].set_ratio(width, height)
        entry["renderer"].update(values, size)

    # ---------------------------------------------------------- building helpers
    def _register(self, key, widget, extra):
        self._widgets.setdefault(key, []).append((widget, extra))

    def _combo(self, key, title, options, subtitle=None):
        labels = [label for _value, label in options]
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels))
        if subtitle:
            row.set_subtitle(subtitle)
        values = [value for value, _label in options]
        current = self.values.get(key)
        row.set_selected(values.index(current) if current in values else 0)
        row.connect("notify::selected", lambda r, _p: self._set(key, values[r.get_selected()]))
        self._register(key, row, values)
        return row

    def _switch(self, key, title, subtitle=None):
        row = Adw.SwitchRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        row.set_active(bool(self.values.get(key)))
        row.connect("notify::active", lambda r, _p: self._set(key, r.get_active()))
        self._register(key, row, None)
        return row

    def _scale(self, key, title, low, high, step, subtitle=None):
        row = Adw.ActionRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
        scale.set_value(self.values.get(key, low))
        scale.set_hexpand(True)
        scale.set_size_request(200, -1)
        scale.set_valign(Gtk.Align.CENTER)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        set_accessible_label(scale, title)
        scale.connect("value-changed", lambda s: self._set(key, int(s.get_value())))
        row.add_suffix(scale)
        row.set_activatable_widget(scale)
        self._register(key, scale, "scale")
        return row

    @staticmethod
    def _group(title, description=None):
        group = Adw.PreferencesGroup(title=title)
        if description:
            group.set_description(description)
        return group

    def _global_display_group(self):
        group = self._group(_("Defaults for all displays"),
                            _("Used by every display that does not set its own value."))
        group.add(self._combo("orientation", _("Orientation"), [
            ("horizontal", _("Horizontal (landscape)")), ("vertical", _("Vertical (portrait)")),
            ("horizontal_flipped", _("Horizontal, upside down")), ("vertical_flipped", _("Vertical, upside down"))]))
        group.add(self._scale("brightness", _("Brightness"), 0, 100, 5))
        group.add(self._combo("performance_profile", _("Performance"), [
            ("auto", _("Automatic (recommended)")), ("economy", _("Economy")),
            ("balanced", _("Balanced")), ("fluid", _("Fluid"))]))
        group.add(self._combo("model", _("Automatic detection"), [
            ("auto", _("All supported models")), ("ax206", _("Only AX206 (USB photo frame)")),
            ("turing", _("Only Turing Smart Screen 3.5\" (USB serial)"))],
            _("Limits which detected displays start automatically.")))
        group.add(self._combo("size", _("Preview size"), [
            ("3.5", "3.5\""), ("5", "5\""), ("8.8", "8.8\""), ("2.1", "2.1\" / 2.8\"")],
            _("Used for the previews while no display is connected.")))
        return group

    def _pending_bar(self):
        bar = Gtk.Box(spacing=12)
        bar.add_css_class("toolbar")
        bar.add_css_class("pending-bar")
        icon = Gtk.Image(icon_name="document-edit-symbolic")
        icon.add_css_class("accent")
        self.changes_label = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.changes_label.add_css_class("heading")
        self.revert_button = Gtk.Button(label=_("Discard"), tooltip_text=_("Discard unsaved changes"))
        self.revert_button.connect("clicked", lambda *_: self._revert())
        self.apply_spinner = Adw.Spinner(visible=False)
        self.apply_button = Gtk.Button(label=_("Apply"), tooltip_text=_("Save and send to the displays (Ctrl+S)"))
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", lambda *_: self._apply())
        for widget in (icon, self.changes_label, self.apply_spinner, self.revert_button, self.apply_button):
            bar.append(widget)
        self.pending_revealer = Gtk.Revealer(child=bar, transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                                             reveal_child=False)
        return self.pending_revealer

    def _install_actions(self):
        for name, callback in (("restore", lambda *_: self._confirm_restore()),
                               ("apply", lambda *_: self.apply_button.get_sensitive() and self._apply()),
                               ("search", lambda *_: self._search_themes()),
                               ("back", lambda *_: self._go_back())):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        section = Gio.SimpleAction.new("section", GLib.VariantType.new("s"))
        section.connect("activate", lambda _a, param: self.show_section(param.get_string()))
        self.add_action(section)
        story = Gio.SimpleAction.new("story", GLib.VariantType.new("s"))
        story.connect("activate", lambda _a, param: (self.show_section("brother_away"),
                                                     self.brother_away_page.play(param.get_string())))
        self.add_action(story)

    def _search_themes(self):
        self.show_section("themes")
        self.sections["themes"].pop_to_tag("themes")
        self.theme_gallery.search_button.set_active(True)
        self.theme_gallery.search.grab_focus()

    def _go_back(self):
        nav = self.sections.get(self.current_section)
        if nav is not None and nav.get_navigation_stack().get_n_items() > 1:
            nav.pop()

    # ---------------------------------------------------------- theme options
    def theme_option_groups(self, theme_id):
        return list(getattr(self, f"_options_{theme_id}")())

    def _options_standard(self):
        page = _Groups()
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

    def _options_gkrellm(self):
        page = _Groups()
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

    def _options_planet(self):
        page = _Groups()
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

    def _options_old_computer(self):
        page = _Groups()
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

    def _options_brother_away(self):
        page = _Groups()
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

    # ---------------------------------------------------------- performance
    def _page_performance(self):
        cards = Gtk.FlowBox(homogeneous=True, min_children_per_line=1, max_children_per_line=4,
                            selection_mode=Gtk.SelectionMode.NONE, column_spacing=12, row_spacing=12)
        self.profile_buttons = {}
        first = None
        for key in ("auto", "economy", "balanced", "fluid"):
            effect = _(PROFILE_EFFECT[key]).format(
                fps=runtime.FPS_PROFILES[key], telemetry=runtime.TELEMETRY_INTERVAL[key],
                period=min(1.0, 0.5 * themes.STATIC_PERIOD_FACTOR[key]))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            head = Gtk.Box(spacing=8)
            head.append(Gtk.Image(icon_name=PROFILE_ICON[key]))
            title = Gtk.Label(label=_(PROFILE_TITLE[key]), xalign=0)
            title.add_css_class("heading")
            head.append(title)
            box.append(head)
            box.append(ui.caption(effect))
            button = Gtk.ToggleButton(child=box)
            button.add_css_class("card")
            button.add_css_class("choice-card")
            set_accessible_label(button, f"{_(PROFILE_TITLE[key])}. {effect}")
            if first is None:
                first = button
            else:
                button.set_group(first)
            button.set_active(self.values.get("performance_profile") == key)
            button.connect("toggled", lambda b, k=key: b.get_active() and self._set("performance_profile", k))
            self.profile_buttons[key] = button
            cards.append(button)
        self._register("performance_profile", self.profile_buttons, "profile")
        profile_group = self._group(_("Profile for all displays"),
                                    _("How often the displays are redrawn and the hardware is read. These are limits "
                                      "set by the profile, not measurements; what the service measures is shown "
                                      "below. A display can use its own profile in My Displays."))
        live = self._group(_("Measured now"), _("Reported by the running service."))
        self.perf_rows = {}
        for key, title in (("cpu", _("Service CPU")), ("ram", _("Service memory")), ("fps", _("Frames per second")),
                           ("usb", _("Transfer time")), ("data", _("Data sent")), ("drop", _("Frames skipped"))):
            row = Adw.ActionRow(title=title, subtitle="—")
            row.add_css_class("property")
            row.set_subtitle_selectable(True)
            self.perf_rows[key] = row
            live.add(row)
        content = ui.page_layout(profile_group, cards, live, maximum=1100)
        return ui.navigation_page(_("Performance"), content, tag="performance")

    # ---------------------------------------------------------- diagnostics
    def _page_diagnostics(self):
        self.diag_card = ui.StateCard()
        state = self._group(_("Current state"))
        self.diag_rows = {}
        for key, title in (("service", _("Service")), ("device", _("Display")),
                           ("last", _("Last confirmed transfer")), ("recoveries", _("Automatic recoveries")),
                           ("pipeline", _("Pipeline"))):
            row = Adw.ActionRow(title=title, subtitle="—")
            row.add_css_class("property")
            self.diag_rows[key] = row
            state.add(row)

        tools = self._group(_("Tools"))
        for title, subtitle, icon, callback in (
                (_("Recover the display now"), _("Reconnects and redraws without restarting the service."),
                 "view-refresh-symbolic", lambda *_: self._helper_action(["recover"], _("Recovery requested."))),
                (_("Restart the service"), _("Use if the display stays frozen."), "system-reboot-symbolic",
                 lambda *_: self._helper_action(["service", "restart"], _("Service restarted."))),
                (_("Export diagnostics"), _("Saves a report to share when asking for help."),
                 "document-save-symbolic", lambda *_: self._export())):
            row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", callback)
            tools.add(row)

        self.results_group = self._group(_("Diagnosis"))
        self.results_group.set_visible(False)
        self._result_rows = []
        self.diag_spinner = Adw.Spinner(visible=False)
        self.results_group.set_header_suffix(self.diag_spinner)

        self.incidents_group = self._group(_("Recent events"))
        self._incident_rows = []
        diagnose = Gtk.Button(label=_("Diagnose"), tooltip_text=_("Check service, permissions, displays and "
                                                                  "settings"))
        diagnose.add_css_class("suggested-action")
        diagnose.connect("clicked", lambda *_: self._run_diagnostics())
        content = ui.page_layout(self.diag_card, self.results_group, state, tools, self.incidents_group,
                                 maximum=900)
        return ui.navigation_page(_("Diagnostics"), content, tag="diagnostics", header_end=[diagnose])

    def diagnose(self):
        self.show_section("diagnostics")
        self._run_diagnostics()

    # ---------------------------------------------------------- state
    def _set(self, key, value):
        if self._loading:
            return
        self.values[key] = value
        self._sync_widgets(key)
        self._refresh_dirty()
        if key.startswith("bmp_") and hasattr(self, "media_page"):
            self.media_page.values_changed()

    def _sync_widgets(self, key):
        """Several controls may edit the same key (dashboard and defaults): keep them equal."""
        entries = self._widgets.get(key, [])
        if len(entries) < 2:
            return
        loading, self._loading = self._loading, True
        try:
            for widget, extra in entries:
                self._set_widget(widget, extra, self.values.get(key))
        finally:
            self._loading = loading

    @staticmethod
    def _set_widget(widget, extra, value):
        if extra == "scale":
            if widget.get_value() != value:
                widget.set_value(value)
        elif extra == "entry":
            if widget.get_text() != (value or ""):
                widget.set_text(value or "")
        elif extra == "profile":
            if value in widget and not widget[value].get_active():
                widget[value].set_active(True)
        elif extra is None:
            if widget.get_active() != bool(value):
                widget.set_active(bool(value))
        else:
            index = extra.index(value) if value in extra else 0
            if widget.get_selected() != index:
                widget.set_selected(index)

    def _refresh_dirty(self):
        dirty = {k for k in self.values if self.values[k] != self.saved.get(k)}
        applying = self.apply_spinner.get_visible()
        self.apply_button.set_sensitive(bool(dirty) and not applying)
        self.revert_button.set_sensitive(bool(dirty) and not applying)
        self.changes_label.set_label(_("Unsaved changes ({count})").format(count=len(dirty)) if dirty else
                                     (_("Applying…") if applying else ""))
        self.pending_revealer.set_reveal_child(bool(dirty) or applying)
        for entry in self._previews:
            self._update_preview(entry)
        for theme_id in self._banners:
            self._update_banner(theme_id)
        if hasattr(self, "theme_gallery"):
            self.theme_gallery.values_changed()
        if hasattr(self, "dashboard") and self.current_section == "home":
            self.dashboard.update()

    def _device_size(self):
        device = (self.status or {}).get("device")
        if device and device.get("width") and device.get("height"):     # coolers report no pixel size
            return device["width"], device["height"]
        return PREVIEW_SIZES.get(self.values.get("size"), (480, 320))

    def _reload_widgets(self):
        self._loading = True
        for key, entries in self._widgets.items():
            for widget, extra in entries:
                self._set_widget(widget, extra, self.values.get(key))
        self._loading = False
        self.displays_page.refresh(force=True)
        if hasattr(self, "kojiro_page"):
            self.kojiro_page.reload()
        if hasattr(self, "media_page"):
            self.media_page.sync_skin()
            self.media_page.reload()
        self._refresh_dirty()

    def _revert(self):
        self.values = copy.deepcopy(self.saved)
        self._reload_widgets()
        self.toast(_("Changes discarded."))

    def _confirm_restore(self):
        dialog = Adw.AlertDialog(heading=_("Restore defaults?"),
                                 body=_("Every theme, display and performance option goes back to its original "
                                        "value, including the names and themes of each display and the Kojiro "
                                        "layout. Nothing changes on the displays until you press Apply."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("restore", _("Restore"))
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", lambda _d, response: response == "restore" and self._restore())
        dialog.present(self)

    def _restore(self):
        self.values = settings.defaults()
        self._reload_widgets()
        self.toast(_("Defaults loaded. Press Apply to use them."))

    def _apply(self):
        values = copy.deepcopy(self.values)
        self.apply_spinner.set_visible(True)
        self._refresh_dirty()

        def worker():
            ok, message = save_settings(values)
            GLib.idle_add(self._applied, ok, message, values)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _applied(self, ok, message, values):
        self.apply_spinner.set_visible(False)
        if ok:
            theme_changed = values.get("theme") != self.saved.get("theme")
            self.saved = values
            self._refresh_dirty()
            self._update_sound_agent(values)
            self._update_media_agent(values)
            toast = Adw.Toast(title=_("Settings applied. The display updates in a moment."), timeout=4)
            if theme_changed and values.get("theme") in ("kojiro", "big_media_player", "brother_away"):
                target = values["theme"]
                toast.set_button_label(_("Customise"))
                toast.connect("button-clicked", lambda *_: self.show_section(target))
            self.toasts.add_toast(toast)
            if message:
                self.toast(_("Some values were corrected: {details}").format(details=message))
            if values.get("ui_sound_feedback"):
                play_success_sound()
        else:
            self._refresh_dirty()
            self._error(_("Could not apply the settings"), message)
        return False

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

    def _update_media_agent(self, values):
        """The session agent feeds the display; start it when a display uses the theme
        (it is also autostarted at login and exits by itself when unused)."""
        from bsmd.media import agent as media_agent
        if media_agent.theme_in_use(values):
            main_py = os.path.join(BASE_DIR, "main.py")
            try:
                subprocess.Popen([sys.executable, main_py, "--media-agent"], start_new_session=True,
                                 stdout=subprocess.DEVNULL)
            except OSError as error:
                self.toast(_("Could not start the media agent: {error}").format(error=error))

    def _helper_action(self, args, success):
        def worker():
            ok, message = run_helper(args)
            GLib.idle_add(lambda: (self.toast(success) if ok else self._error(_("Operation failed"), message))
                          and False)
        threading.Thread(target=worker, daemon=True).start()

    def _startup_state(self, state, _error):
        self._loading, loading = True, self._loading
        self.startup_row.set_active(state == "enabled")
        self._loading = loading

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

    # ---------------------------------------------------------- status
    def _status_fresh(self):
        path = runtime.find_status_file()
        try:
            return self.status is not None and path is not None and time.time() - os.path.getmtime(path) < 15
        except OSError:
            return False

    def _refresh_status(self):
        if self._closed:
            return False
        self.status = runtime.read_status()
        self.service_fresh = self._status_fresh()
        self.displays_page.refresh()
        self._update_sidebar_status()
        if self.current_section == "home" and hasattr(self, "dashboard"):
            self.dashboard.update()
        if hasattr(self, "diag_rows") and self.current_section == "diagnostics":
            self._refresh_diagnostics()
        if hasattr(self, "perf_rows") and self.current_section == "performance":
            self._refresh_perf()
        return True

    def _update_sidebar_status(self):
        status = self.status if self.service_fresh else None
        for kind in ("success", "warning", "error"):
            self.status_dot.remove_css_class(kind)
        displays = (status or {}).get("displays") or []
        connected = [d for d in displays if d.get("connected")]
        if status is None:
            kind, text = "error", _("Service stopped")
        elif not connected:
            kind, text = "warning", _("Waiting for a display")
        elif status.get("state") == "healthy":
            kind, text = "success", _("Running · {count} display(s)").format(count=len(connected))
        else:
            kind, text = "warning", diagnostics.describe_state(status)
        self.status_dot.add_css_class(kind)
        self.status_label.set_label(text)
        count = self.sidebar_suffix["displays"]
        count.set_visible(bool(displays))
        count.set_label(str(len(connected)))
        problems = self.sidebar_suffix["diagnostics"]
        problems.set_visible(kind == "error")
        problems.set_label("!")

    def _refresh_perf(self):
        status = self.status if self.service_fresh else None
        if status is None:
            for row in self.perf_rows.values():
                row.set_subtitle(_("The service is not running."))
            return
        stats, proc = status.get("stats", {}), status.get("process", {})
        self.perf_rows["cpu"].set_subtitle(f"{proc.get('cpu_percent', 0):.1f} %")
        self.perf_rows["ram"].set_subtitle(f"{proc.get('rss_mb', 0):.0f} MB")
        self.perf_rows["fps"].set_subtitle(_("{fps:.1f} (target {target:g})").format(
            fps=min(stats.get("fps", 0), stats.get("target_fps", 0) or 99), target=stats.get("target_fps", 0)))
        self.perf_rows["usb"].set_subtitle(f"{stats.get('transfer_ms', 0):.1f} ms")
        self.perf_rows["data"].set_subtitle(f"{stats.get('bytes_sent', 0) / 1048576:.1f} MB · "
                                            + _("{frames} frames").format(frames=stats.get("frames_sent", 0)))
        self.perf_rows["drop"].set_subtitle(str(stats.get("frames_dropped", 0)))

    def _refresh_diagnostics(self):
        status = self.status if self.service_fresh else None
        if status is None:
            self.diag_card.show("error", "dialog-error-symbolic", _("The monitor service is not running"),
                                _("Run the diagnosis to find out why, or start the service."),
                                [(_("Start Service"), lambda: self._helper_action(["service", "start"],
                                                                                 _("Service started.")))])
            for row in self.diag_rows.values():
                row.set_subtitle("—")
            self.worker.submit("is-active", lambda: diagnostics.systemctl_query("is-active"),
                               lambda state, _e: self.diag_rows["service"].set_subtitle(state or "—"))
            self._show_incidents([])
            return
        state = status.get("state")
        description = diagnostics.describe_state(status)
        if state == "healthy" and not status.get("stalled"):
            self.diag_card.show("accent", "emblem-ok-symbolic", _("Everything is working"), description, [])
        else:
            self.diag_card.show("warning", "dialog-warning-symbolic", _("Attention needed"), description,
                                [(_("Diagnose"), self._run_diagnostics)])
        stats = status.get("stats", {})
        device = status.get("device") or {}
        self.diag_rows["service"].set_subtitle(_("Running for {time}").format(
            time=_duration(status.get("uptime_s", 0))))
        location = f" · {device['location']}" if device.get("location") else ""
        self.diag_rows["device"].set_subtitle(description.rstrip(".") + location)
        age = stats.get("last_transfer_age_s")
        self.diag_rows["last"].set_subtitle(_("{seconds:.0f} s ago").format(seconds=age) if age is not None
                                            else _("Nothing sent yet"))
        self.diag_rows["recoveries"].set_subtitle(str(status.get("recoveries", 0)))
        self.diag_rows["pipeline"].set_subtitle(_("A thread stopped making progress.") if status.get("stalled")
                                                else _("Telemetry, rendering and transfer are progressing."))
        self._show_incidents(status.get("incidents", []))

    def _show_incidents(self, incidents):
        signature = tuple((i.get("time"), i.get("message")) for i in incidents[-12:])
        if getattr(self, "_incident_signature", None) == signature and self._incident_rows:
            return
        self._incident_signature = signature
        for row in self._incident_rows:
            self.incidents_group.remove(row)
        self._incident_rows = []
        for incident in list(reversed(incidents))[:12]:
            icon = {"info": "emblem-ok-symbolic", "warning": "dialog-warning-symbolic"}.get(
                incident.get("severity"), "dialog-error-symbolic")
            row = Adw.ActionRow(title=GLib.markup_escape_text(incident.get("message", "")),
                                subtitle=incident.get("time", "")[:19].replace("T", " "))
            row.set_title_lines(2)
            image = Gtk.Image.new_from_icon_name(icon)
            set_accessible_label(image, incident.get("severity", ""))
            row.add_prefix(image)
            self.incidents_group.add(row)
            self._incident_rows.append(row)
        if not incidents:
            row = Adw.ActionRow(title=_("No events recorded."))
            self.incidents_group.add(row)
            self._incident_rows.append(row)

    def _run_diagnostics(self):
        if not hasattr(self, "diag_spinner"):
            self.show_section("diagnostics")
        self.diag_spinner.set_visible(True)
        self.results_group.set_visible(True)
        self.worker.submit("diagnose", diagnostics.run_checks, self._show_report)

    def _show_report(self, report, error):
        self.diag_spinner.set_visible(False)
        if error is not None:
            self._error(_("The diagnosis failed"), repr(error))
            return
        for row in self._result_rows:
            self.results_group.remove(row)
        self._result_rows = []
        for check in report["checks"]:
            icon = "emblem-ok-symbolic" if check["ok"] else (
                "dialog-error-symbolic" if check["severity"] == "error" else "dialog-warning-symbolic")
            row = Adw.ActionRow(title=GLib.markup_escape_text(check["title"]),
                                subtitle=GLib.markup_escape_text(check["detail"]))
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
        self._closed = True
        GLib.source_remove(self._status_source)
        for entry in self._previews:
            entry["renderer"].stop()
        self.thumbnailer.stop()
        if hasattr(self, "kojiro_page"):
            self.kojiro_page.close()
        if hasattr(self, "media_page"):
            self.media_page.close()
        self.collector.stop()
        return False


def _duration(seconds):
    seconds = int(seconds or 0)
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


# 4.x tab names accepted by --page.
LEGACY_PAGES = {"display": "displays", "theme_kojiro": "kojiro", "theme_big_media_player": "big_media_player",
                "theme_brother_away": "brother_away", "theme_standard": "themes", "theme_gkrellm": "themes",
                "theme_planet": "themes", "theme_old_computer": "themes"}


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
            self.set_accels_for_action("win.apply", ["<Control>s"])
            self.set_accels_for_action("win.search", ["<Control>f"])
            self.set_accels_for_action("win.back", ["<Alt>Left"])
            for index, (key, *_rest) in enumerate(SECTIONS, start=1):
                self.set_accels_for_action(f"win.section::{key}", [f"<Control>{index}"])
            if self.page:
                window.show_section(LEGACY_PAGES.get(self.page, self.page))
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
            comments=_("Free hardware monitor for small USB displays, with themes, the Brother Away island, "
                       "the Kojiro studio and the Big Media Player."))
        about.add_acknowledgement_section(_("Testing"), [
            "Cristian Philipe (@Criatianphilipe)",
            "Reinaldo Nunes Rodrigues Junior <reinaldodeuseamor8@gmail.com>",
        ])
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
