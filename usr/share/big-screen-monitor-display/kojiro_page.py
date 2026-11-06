"""Kojiro tab of the configuration window: Design Studio + inspector.

The page edits ``values["kojiro"]`` (all displays) or the Kojiro layout of
one display (``values["displays"][id]["kojiro"]``). Changes show at once in
the canvas; "Apply" (or Ctrl+S, or the "Live on the display" switch) sends
them to the service, which redraws without restarting.
"""

import copy
import json
import os
import threading

import psutil
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from bsmd import settings, telemetry  # noqa: E402
from bsmd.i18n import N_, _  # noqa: E402
from bsmd.kojiro import data as kdata  # noqa: E402
from bsmd.kojiro import model, presets, store, wallpaper  # noqa: E402
from bsmd.kojiro.engine import KojiroTheme  # noqa: E402
from bsmd.themes import REGISTRY  # noqa: E402
from kojiro_editor import DesignCanvas, EditorState, PreviewWorker  # noqa: E402

PREVIEW_SIZES = (("800x480", (800, 480)), ("480x320", (480, 320)), ("1024x600", (1024, 600)),
                 ("1280x720", (1280, 720)), ("1920x480 — ultrawide", (1920, 480)), ("480x480", (480, 480)),
                 ("160x80 — micro", (160, 80)))
STYLE_LABELS = {
    "ring": N_("Ring"), "semi": N_("Semicircle"), "arc": N_("Arc"), "double": N_("Double ring"),
    "gauge": N_("Gauge with needle"), "bar": N_("Bar"), "bar_segmented": N_("Segmented bar"),
    "bar_gradient": N_("Gradient bar"), "bar_vertical": N_("Vertical bar"), "thermo": N_("Thermometer"),
    "graph_line": N_("Line graph"), "graph_area": N_("Area graph"), "graph_bars": N_("Bar graph"),
    "sparkline": N_("Sparkline"), "text": N_("Text"), "hud": N_("HUD panel"), "icon": N_("Icon and text"),
    "frame": N_("Futuristic frame"), "plain": N_("Plain"), "digital": N_("Digital (7 segments)"),
    "logo_name": N_("Logo and name"), "logo": N_("Logo only"), "name": N_("Name only"), "bars": N_("Bars"),
    "grid": N_("Grid"), "list": N_("List"), "line": N_("Line"), "glow_line": N_("Light line"), "dots": N_("Dots"),
    "corners": N_("Corner brackets"), "box": N_("Box"),
}
ANCHOR_LABELS = (("auto", N_("Automatic")), ("tl", N_("Top left")), ("tc", N_("Top centre")),
                 ("tr", N_("Top right")), ("ml", N_("Middle left")), ("c", N_("Centre")),
                 ("mr", N_("Middle right")), ("bl", N_("Bottom left")), ("bc", N_("Bottom centre")),
                 ("br", N_("Bottom right")))
TEXT_STYLES = (("normal", N_("Normal")), ("mono", N_("Monospaced")), ("digital", N_("Digital")),
               ("pixel", N_("Pixel")))
PALETTES = (
    (N_("Cyberpunk"), ("#42E8FF", "#F044DB", "#FF475C", "#83EF4C", "#FFD94A")),
    (N_("Matrix"), ("#33FF77", "#1EDB5A", "#7CFFA8")),
    (N_("Amber"), ("#FFB000", "#FF8A00", "#FFD15C")),
    (N_("Ice"), ("#7FD6FF", "#B8F1FF", "#5AA9FF", "#E8F4FF")),
    (N_("Sunset"), ("#FF6B6B", "#FFA94D", "#FFD43B", "#F783AC")),
    (N_("Mono"), ("#E8F4FF", "#AEB8C4")),
)
OPTION_LABELS = {
    "show_temp": N_("Show temperature"), "show_freq": N_("Show frequency"), "show_model": N_("Show model"),
    "temp_sensor": N_("Temperature sensor"), "index": N_("GPU"), "show_clock": N_("Show clock speed"),
    "show_vram": N_("Show VRAM"), "show_power": N_("Show power"),
    "show_values": N_("Show used / total"), "show_percent": N_("Show percentage"),
    "hide_when_none": N_("Hide when the computer has no swap"), "fan": N_("Fan"), "spin": N_("Spinning animation"),
    "show_rpm": N_("Show RPM"), "mount": N_("Mount point"), "show_io": N_("Show read/write"),
    "show_space": N_("Show used / total"), "iface": N_("Network interface"), "h24": N_("24-hour clock"),
    "seconds": N_("Show seconds"), "date": N_("Show date"), "weekday": N_("Show weekday"),
    "blink": N_("Blinking colon"), "date_format": N_("Date format"), "logo": N_("Logo"),
    "name": N_("Name (empty = detected)"), "show_name": N_("Show name"), "circle": N_("Circular frame"),
    "max": N_("Cores shown"), "count": N_("Processes"), "sort": N_("Sort by"), "text": N_("Text"),
}
WALLPAPER_LABELS = {"cyberpunk": N_("Cyberpunk"), "neon_grid": N_("Neon grid"), "minimal": N_("Minimal"),
                    "matrix": N_("Matrix"), "retro": N_("Retro"), "dark": N_("Dark"), "glass": N_("Glass"),
                    "industrial": N_("Industrial")}
CHOICE_LABELS = {"auto": N_("Automatic"), "none": N_("None"), "cpu": N_("CPU"), "memory": N_("Memory"),
                 "dmy": N_("Day/Month/Year"), "mdy": N_("Month/Day/Year"), "ymd": N_("Year-Month-Day")}


def _rgba(hex_color):
    rgba = Gdk.RGBA()
    rgba.parse(hex_color)
    return rgba


def _hex(rgba):
    return "#{:02X}{:02X}{:02X}".format(int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255))


def _texture(image):
    image = image.convert("RGB")
    return Gdk.MemoryTexture.new(image.width, image.height, Gdk.MemoryFormat.R8G8B8,
                                 GLib.Bytes.new(image.tobytes()), image.width * 3)


def _store_writable():
    directory = os.path.dirname(settings.config_path())
    return bool(os.environ.get("BSM_CONFIG")) or (os.path.isdir(directory) and os.access(directory, os.W_OK))


class KojiroPage:
    def __init__(self, window, run_helper):
        self.window = window
        self.run_helper = run_helper
        self.target_id = None
        self._syncing = False
        self._live_source = None
        self.state = EditorState(self._config_from_values(), self._on_state_change)
        self.preview_size = self._initial_size()
        self.state.target = self.preview_size
        self.state.portrait = self.preview_size[1] > self.preview_size[0]
        self.worker = PreviewWorker(self._frame)
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # The tool row scrolls sideways on narrow windows instead of widening the window.
        self.widget.append(Gtk.ScrolledWindow(child=self._toolbar(), vscrollbar_policy=Gtk.PolicyType.NEVER,
                                              hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                              propagate_natural_height=True))
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True, vexpand=True)
        self.canvas = DesignCanvas(self.state, self._commit)
        self._canvas_actions()
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.append(self.canvas)
        self.status = Gtk.Label(xalign=0, css_classes=["dim-label", "caption"], margin_start=12, margin_end=12,
                                margin_bottom=6, ellipsize=3)
        left.append(self.status)
        paned.set_start_child(left)
        paned.set_resize_start_child(True)
        paned.set_shrink_start_child(False)
        paned.set_end_child(self._inspector())
        paned.set_resize_end_child(False)
        paned.set_shrink_end_child(False)
        paned.set_position(640)
        self.widget.append(paned)
        self.paned = paned
        from gui import components as ui
        ui.ADAPTIVE.add(paned)
        shortcuts = Gtk.ShortcutController(scope=Gtk.ShortcutScope.GLOBAL)
        shortcuts.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("<Control>s"),
                                                Gtk.CallbackAction.new(self._save_shortcut)))
        self.widget.add_controller(shortcuts)
        self.refresh_all()
        threading.Thread(target=self._build_thumbnails, daemon=True).start()

    # ---------------------------------------------------------- config plumbing
    def _config_from_values(self):
        values = self.window.values
        if self.target_id:
            entry = (values.get("displays") or {}).get(self.target_id) or {}
            if isinstance(entry.get("kojiro"), dict):
                return entry["kojiro"]
        return values.get("kojiro") or model.defaults()

    def _write_values(self):
        config = copy.deepcopy(self.state.config)
        if self.target_id:
            displays = copy.deepcopy(self.window.values.get("displays") or {})
            displays.setdefault(self.target_id, {})["kojiro"] = config
            self.window.values["displays"] = displays
        else:
            self.window.values["kojiro"] = config
        self.window._refresh_dirty()

    def reload(self):
        """Window values were replaced (discard, restore, applied)."""
        self.state.config = copy.deepcopy(self._config_from_values())
        self.state.selection = []
        self.state.undo_stack.clear()
        self.state.redo_stack.clear()
        self.refresh_all()

    def _initial_size(self):
        status = self.window.status or {}
        for display in status.get("displays") or []:
            device = display.get("device")
            if device:
                return (device["width"], device["height"])
        return tuple(self.state.config["ref"])

    # ---------------------------------------------------------- change flow
    def _on_state_change(self, kind):
        if self._syncing:
            return
        self._write_values()
        self.request_render()
        self.canvas.queue_draw()
        if kind in ("all", "selection"):
            self._rebuild_element()
            self._refresh_layers()
        elif kind == "layout":
            self._sync_geometry()
        elif kind == "style":
            self._refresh_layers()
        self._update_status()
        self._schedule_live()

    def _commit(self):
        self._update_status()

    def request_render(self):
        settings_extra = {"language": self.window.values.get("language")}
        needs = kdata.needs(self.state.widgets())
        collector = getattr(self.window, "collector", None)
        if collector is not None:
            collector.want_fans = collector.want_fans or needs["fans"]
            collector.want_disks = set(collector.want_disks) | needs["disks"]
            collector.want_processes = collector.want_processes or needs["processes"]
            collector.want_addrs = collector.want_addrs or needs["addrs"]
        self.worker.submit(self.state.config, self.preview_size, settings_extra)

    def _frame(self, image, size):
        self.canvas.set_frame(image, size)
        return False

    def refresh_all(self):
        self.state.target = self.preview_size
        self.state.portrait = self.preview_size[1] > self.preview_size[0]
        self.request_render()
        self.canvas.queue_draw()
        self._rebuild_element()
        self._refresh_layers()
        self._refresh_background()
        self._refresh_appearance()
        self._refresh_general()
        self._update_status()

    def set_active(self, active):
        self.worker.active = active
        if active:
            self.request_render()

    def _update_status(self):
        widget = self.state.primary()
        orientation = _("portrait") if self.state.portrait else _("landscape")
        auto = _(" (automatic layout)") if self.state.portrait and self.state.portrait_is_auto() else ""
        text = f"{self.preview_size[0]}×{self.preview_size[1]} · {orientation}{auto}"
        if widget:
            x, y, w, h = self.state.box(widget)
            text += f" · {widget['id']}: X {x:.0f}  Y {y:.0f}  W {w:.0f}  H {h:.0f}"
            text += f" ({x / self.preview_size[0] * 100:.1f}%, {y / self.preview_size[1] * 100:.1f}%)"
        else:
            text += " · " + _("click a widget to edit it; drag on empty space to select several")
        self.status.set_label(text)
        self.undo_button.set_sensitive(bool(self.state.undo_stack))
        self.redo_button.set_sensitive(bool(self.state.redo_stack))

    def _schedule_live(self):
        if not self.live_switch.get_active():
            return
        if self._live_source:
            GLib.source_remove(self._live_source)
        self._live_source = GLib.timeout_add(1200, self._live_apply)

    def _live_apply(self):
        self._live_source = None
        if self.window.apply_button.get_sensitive():
            self.window._apply()
        return False

    def _save_shortcut(self, *_args):
        if self.window.current_section == "kojiro" and self.window.apply_button.get_sensitive():
            self.window._apply()
            return True
        return False

    # ---------------------------------------------------------- toolbar
    def _button(self, icon, tooltip, callback, label=None):
        button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, css_classes=["flat"]) if not label else \
            Gtk.Button(label=label, tooltip_text=tooltip, css_classes=["flat"])
        button.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
        button.connect("clicked", lambda *_: callback())
        return button

    def _toolbar(self):
        bar = Gtk.Box(spacing=4, margin_start=8, margin_end=8, margin_top=6, margin_bottom=6)
        self.target_combo = Gtk.DropDown(tooltip_text=_("Which display this layout belongs to"))
        self.target_combo.connect("notify::selected", self._target_changed)
        bar.append(self.target_combo)
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        add_menu = Gio.Menu()
        groups = (("cpu", "gpu", "ram", "swap", "vram", "fan", "encdec", "disk", "net_down", "net_up"),
                  ("clock", "distro", "cores", "processes", "uptime", "hostname", "kernel", "ip", "battery", "power"),
                  ("text", "separator", "frame"))
        for group in groups:
            section = Gio.Menu()
            for widget_type in group:
                section.append(_(model.type_label(widget_type)), f"kojiro.add::{widget_type}")
            add_menu.append_section(None, section)
        add = Gtk.MenuButton(icon_name="list-add-symbolic", menu_model=add_menu, tooltip_text=_("Add widget"),
                             css_classes=["suggested-action"])
        add.update_property([Gtk.AccessibleProperty.LABEL], [_("Add widget")])
        bar.append(add)
        self.undo_button = self._button("edit-undo-symbolic", _("Undo (Ctrl+Z)"), self._undo)
        self.redo_button = self._button("edit-redo-symbolic", _("Redo (Ctrl+Shift+Z)"), self._redo)
        bar.append(self.undo_button)
        bar.append(self.redo_button)
        bar.append(self._button("edit-copy-symbolic", _("Duplicate (Ctrl+D)"), lambda: self._act("duplicate")))
        bar.append(self._button("user-trash-symbolic", _("Delete (Del)"), lambda: self._act("delete")))
        align_menu = Gio.Menu()
        for label, action in ((N_("Align left"), "left"), (N_("Centre horizontally"), "hcenter"),
                              (N_("Align right"), "right"), (N_("Align top"), "top"),
                              (N_("Centre vertically"), "vcenter"), (N_("Align bottom"), "bottom")):
            align_menu.append(_(label), f"kojiro.align::{action}")
        distribute = Gio.Menu()
        distribute.append(_("Distribute horizontally"), "kojiro.distribute::h")
        distribute.append(_("Distribute vertically"), "kojiro.distribute::v")
        align_menu.append_section(None, distribute)
        order = Gio.Menu()
        for label, action in ((N_("Bring to front"), "top"), (N_("Bring forward"), "up"),
                              (N_("Send backward"), "down"), (N_("Send to back"), "bottom")):
            order.append(_(label), f"kojiro.restack::{action}")
        align_menu.append_section(None, order)
        groupm = Gio.Menu()
        groupm.append(_("Group (Ctrl+G)"), "kojiro.group")
        groupm.append(_("Ungroup (Ctrl+Shift+G)"), "kojiro.ungroup")
        groupm.append(_("Copy style (Ctrl+Shift+C)"), "kojiro.copy_style")
        groupm.append(_("Paste style (Ctrl+Shift+V)"), "kojiro.paste_style")
        align_menu.append_section(None, groupm)
        bar.append(Gtk.MenuButton(icon_name="view-grid-symbolic", menu_model=align_menu,
                                  tooltip_text=_("Align, distribute, order and group")))
        # View options in one menu, so the studio fits narrower windows.
        view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=8, margin_bottom=8,
                       margin_start=8, margin_end=8)
        self.grid_toggle = Gtk.CheckButton(label=_("Show grid"))
        self.grid_toggle.connect("toggled", lambda b: self._canvas_flag("show_grid", b.get_active()))
        self.snap_toggle = Gtk.CheckButton(label=_("Snap to edges, centres and other widgets"), active=True)
        self.snap_toggle.connect("toggled", lambda b: self._canvas_flag("snap", b.get_active()))
        self.margin_toggle = Gtk.CheckButton(label=_("Show safe margins"), active=True)
        self.margin_toggle.connect("toggled", lambda b: self._canvas_flag("show_margins", b.get_active()))
        self.demo_toggle = Gtk.CheckButton(label=_("Demo data"),
                                           tooltip_text=_("Moving sample values instead of this computer's data"))
        self.demo_toggle.connect("toggled", self._demo_toggled)
        for widget in (self.grid_toggle, self.snap_toggle, self.margin_toggle, self.demo_toggle):
            view.append(widget)
        bar.append(Gtk.MenuButton(icon_name="view-reveal-symbolic", popover=Gtk.Popover(child=view),
                                  tooltip_text=_("View: grid, snapping, margins, demo data")))
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.size_combo = Gtk.DropDown(tooltip_text=_("Preview resolution"))
        self.size_combo.connect("notify::selected", self._size_changed)
        bar.append(self.size_combo)
        rotate = self._button("object-rotate-right-symbolic", _("Switch portrait / landscape"), self._rotate_preview)
        bar.append(rotate)
        spacer = Gtk.Box(hexpand=True)
        bar.append(spacer)
        live = Gtk.Box(spacing=6)
        live.append(Gtk.Label(label=_("Live")))
        self.live_switch = Gtk.Switch(valign=Gtk.Align.CENTER,
                                      tooltip_text=_("Apply every change to the connected display automatically"))
        live.append(self.live_switch)
        bar.append(live)
        self.actions = Gio.SimpleActionGroup()
        for name, callback in (("add", lambda p: self._add(p.get_string())),
                               ("align", lambda p: self._act("align", p.get_string())),
                               ("distribute", lambda p: self._act("distribute", p.get_string())),
                               ("restack", lambda p: self._act("restack", p.get_string()))):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", lambda _a, param, cb=callback: cb(param))
            self.actions.add_action(action)
        for name in ("group", "ungroup", "copy_style", "paste_style"):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, n=name: self._act(n))
            self.actions.add_action(action)
        self.window.insert_action_group("kojiro", self.actions)
        self._fill_targets()
        self._fill_sizes()
        return bar

    def _canvas_actions(self):
        group = self.canvas.menu_actions
        for name, handler in (("duplicate", lambda: self._act("duplicate")), ("delete", lambda: self._act("delete")),
                              ("front", lambda: self._act("restack", "top")),
                              ("back", lambda: self._act("restack", "bottom")),
                              ("lock", self._toggle_lock), ("hide", lambda: self._set_selected("visible", False)),
                              ("copy_style", lambda: self._act("copy_style")),
                              ("paste_style", lambda: self._act("paste_style")),
                              ("group", lambda: self._act("group")), ("ungroup", lambda: self._act("ungroup"))):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, h=handler: h())
            group.add_action(action)

    def _canvas_flag(self, name, value):
        setattr(self.canvas, name, value)
        self.canvas.queue_draw()

    def _act(self, name, arg=None):
        method = getattr(self.state, name)
        method(arg) if arg is not None else method()
        if name == "copy_style":
            self.window.toast(_("Style copied."))

    def _add(self, widget_type):
        if self.state.add(widget_type) is None:
            self.window.toast(_("Widget limit reached."))
        self.canvas.grab_focus()

    def _undo(self):
        self.state.undo()

    def _redo(self):
        self.state.redo()

    def _toggle_lock(self):
        primary = self.state.primary()
        if primary:
            self._set_selected("locked", not primary.get("locked"))

    def _set_selected(self, key, value):
        self.state.set_props_selected(key, value)

    def _fill_targets(self):
        self._targets = [(None, _("All displays"))]
        displays = self.window.values.get("displays") or {}
        names = {d.get("id"): d.get("name") for d in (self.window.status or {}).get("displays") or []}
        for display_id in sorted(set(displays) | set(names)):
            if display_id in names or isinstance((displays.get(display_id) or {}).get("kojiro"), dict):
                label = (displays.get(display_id) or {}).get("name") or names.get(display_id) or display_id
                own = isinstance((displays.get(display_id) or {}).get("kojiro"), dict)
                self._targets.append((display_id, label + ("" if own else _(" (uses the common layout)"))))
        self.target_combo.set_model(Gtk.StringList.new([label for _id, label in self._targets]))
        index = next((i for i, (tid, _l) in enumerate(self._targets) if tid == self.target_id), 0)
        self.target_combo.set_selected(index)

    def _target_changed(self, combo, _pspec):
        if not hasattr(self, "_targets"):
            return
        index = combo.get_selected()
        if index >= len(self._targets):
            return
        target = self._targets[index][0]
        if target == self.target_id:
            return
        self.target_id = target
        displays = self.window.values.get("displays") or {}
        if target and not isinstance((displays.get(target) or {}).get("kojiro"), dict):
            dialog = Adw.AlertDialog(heading=_("Create a layout for this display?"),
                                     body=_("This display uses the common Kojiro layout. A copy will be made that "
                                            "you can change without affecting the other displays."))
            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("copy", _("Create own layout"))
            dialog.set_response_appearance("copy", Adw.ResponseAppearance.SUGGESTED)

            def done(_d, response):
                if response == "copy":
                    self.state.config = copy.deepcopy(self.window.values.get("kojiro") or model.defaults())
                    self._write_values()
                    self._fill_targets()
                    for display in (self.window.status or {}).get("displays") or []:
                        if display.get("id") == target and display.get("device"):
                            self.preview_size = (display["device"]["width"], display["device"]["height"])
                    self.reload()
                else:
                    self.target_id = None
                    self.target_combo.set_selected(0)
            dialog.connect("response", done)
            dialog.present(self.window)
            return
        self.reload()

    def _fill_sizes(self):
        sizes = []
        for display in (self.window.status or {}).get("displays") or []:
            device = display.get("device")
            if device:
                sizes.append((f"{display.get('name') or device['model']} — {device['width']}x{device['height']}",
                              (device["width"], device["height"])))
        sizes += [(label, size) for label, size in PREVIEW_SIZES if size not in [s for _l, s in sizes]]
        self._sizes = sizes
        self._syncing_size = True
        self.size_combo.set_model(Gtk.StringList.new([label for label, _s in sizes]))
        landscape = tuple(sorted(self.preview_size, reverse=True))
        index = next((i for i, (_l, s) in enumerate(sizes) if tuple(sorted(s, reverse=True)) == landscape), 0)
        self.size_combo.set_selected(index)
        self._syncing_size = False

    def _size_changed(self, combo, _pspec):
        if getattr(self, "_syncing_size", False) or not hasattr(self, "_sizes"):
            return
        size = self._sizes[combo.get_selected()][1]
        if self.preview_size[1] > self.preview_size[0] and size[0] > size[1]:
            size = (size[1], size[0])
        self.preview_size = size
        self.state.selection = []
        self.refresh_all()

    def _rotate_preview(self):
        self.preview_size = (self.preview_size[1], self.preview_size[0])
        self.state.selection = []
        self.refresh_all()

    def _demo_toggled(self, button):
        self.worker.demo = button.get_active()
        self.request_render()

    # ---------------------------------------------------------- inspector
    def _inspector(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=320)
        self.inspector = Adw.ViewStack(vexpand=True)
        switcher = Adw.InlineViewSwitcher(stack=self.inspector, margin_start=8, margin_end=8, margin_top=4,
                                          display_mode=Adw.InlineViewSwitcherDisplayMode.ICONS)
        switcher.add_css_class("flat")
        box.append(switcher)
        box.append(self.inspector)
        self.element_page = Adw.PreferencesPage()
        self.layers_page = Adw.PreferencesPage()
        self.background_page = Adw.PreferencesPage()
        self.appearance_page = Adw.PreferencesPage()
        self.general_page = Adw.PreferencesPage()
        self.advanced_page = Adw.PreferencesPage()
        for page, name, title, icon in ((self.element_page, "element", _("Element"), "document-edit-symbolic"),
                                        (self.layers_page, "layers", _("Layers"), "view-list-symbolic"),
                                        (self.background_page, "background", _("Background"),
                                         "image-x-generic-symbolic"),
                                        (self.appearance_page, "appearance", _("Appearance"),
                                         "applications-graphics-symbolic"),
                                        (self.general_page, "general", _("General"), "emblem-system-symbolic"),
                                        (self.advanced_page, "advanced", _("Advanced"),
                                         "utilities-system-monitor-symbolic")):
            self.inspector.add_titled_with_icon(page, name, title, icon)
        self._element_groups = []
        self._layer_groups = []
        self._background_groups = []
        self._appearance_groups = []
        self._general_groups = []
        self._advanced_groups = []
        self.inspector.connect("notify::visible-child-name", lambda *_: self._refresh_advanced())
        return box

    @staticmethod
    def _clear(page, groups):
        for group in groups:
            page.remove(group)
        groups.clear()

    def _group(self, page, groups, title, description=None):
        group = Adw.PreferencesGroup(title=title)
        if description:
            group.set_description(description)
        page.add(group)
        groups.append(group)
        return group

    # -- generic rows
    def _switch_row(self, title, value, callback, subtitle=None):
        row = Adw.SwitchRow(title=title, active=bool(value))
        if subtitle:
            row.set_subtitle(subtitle)
        row.connect("notify::active", lambda r, _p: None if self._syncing else callback(r.get_active()))
        return row

    def _combo_row(self, title, options, current, callback, subtitle=None):
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for _v, label in options]))
        if subtitle:
            row.set_subtitle(subtitle)
        values = [v for v, _l in options]
        row.set_selected(values.index(current) if current in values else 0)
        row.connect("notify::selected", lambda r, _p: None if self._syncing else callback(values[r.get_selected()]))
        return row

    def _spin_row(self, title, low, high, step, value, callback, digits=0, subtitle=None):
        row = Adw.SpinRow.new_with_range(low, high, step)
        row.set_title(title)
        row.set_digits(digits)
        row.set_value(value)
        if subtitle:
            row.set_subtitle(subtitle)
        row.connect("notify::value", lambda r, _p: None if self._syncing else callback(
            r.get_value() if digits else int(r.get_value())))
        return row

    def _scale_row(self, title, low, high, value, callback, step=1):
        row = Adw.ActionRow(title=title)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
        scale.set_value(value)
        scale.set_hexpand(True)
        scale.set_size_request(150, -1)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.update_property([Gtk.AccessibleProperty.LABEL], [title])
        scale.connect("value-changed", lambda s: None if self._syncing else callback(int(s.get_value())))
        row.add_suffix(scale)
        return row

    def _color_row(self, title, value, callback):
        row = Adw.ActionRow(title=title)
        button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        button.set_rgba(_rgba(value))
        button.update_property([Gtk.AccessibleProperty.LABEL], [title])
        button.connect("notify::rgba", lambda b, _p: None if self._syncing else callback(_hex(b.get_rgba())))
        row.add_suffix(button)
        row.set_activatable_widget(button)
        return row

    def _entry_row(self, title, value, callback, limit=80):
        row = Adw.EntryRow(title=title, text=value or "", show_apply_button=True)
        row.connect("apply", lambda r: callback(r.get_text()[:limit]))
        return row

    def _font_row(self, title, value, callback):
        row = Adw.ActionRow(title=title, subtitle=_("Default") if value == "default" else value)
        button = Gtk.FontDialogButton(dialog=Gtk.FontDialog(), level=Gtk.FontLevel.FAMILY, valign=Gtk.Align.CENTER)
        button.update_property([Gtk.AccessibleProperty.LABEL], [title])

        def chosen(b, _p):
            if self._syncing or b.get_font_desc() is None:
                return
            family = b.get_font_desc().get_family() or "default"
            if family != "default" and not model.FONT_FAMILY.match(family):
                self.window.toast(_("This font name cannot be used; choose another font."))
                return
            row.set_subtitle(family)
            callback(family)
        button.connect("notify::font-desc", chosen)
        reset = Gtk.Button(icon_name="edit-clear-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                           tooltip_text=_("Use the default font"))
        reset.connect("clicked", lambda *_: (row.set_subtitle(_("Default")), callback("default")))
        row.add_suffix(button)
        row.add_suffix(reset)
        return row

    # -- element tab
    def _rebuild_element(self):
        self._syncing = True
        try:
            self._clear(self.element_page, self._element_groups)
            widget = self.state.primary()
            if widget is None:
                self._element_empty()
                return
            self._element_for(widget)
        finally:
            self._syncing = False

    def _element_empty(self):
        group = self._group(self.element_page, self._element_groups, _("No widget selected"),
                            _("Click a widget in the editor, or add one below. Drag to move, use the handles to "
                              "resize. Shift-click selects several."))
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, row_spacing=6,
                           column_spacing=6, margin_top=6)
        for widget_type in model.widget_types():
            button = Gtk.Button(label=_(model.type_label(widget_type)))
            button.connect("clicked", lambda _b, t=widget_type: self._add(t))
            flow.append(button)
        group.add(flow)

    def _element_for(self, w):
        wid = w["id"]
        widget_type = w["type"]
        set_prop = lambda key: (lambda value: self.state.set_prop(wid, key, value))  # noqa: E731
        set_opt = lambda key: (lambda value: self.state.set_opt(wid, key, value))   # noqa: E731
        count = len(self.state.selection)
        title = _(model.type_label(widget_type)) + (_(" (+{n} selected)").format(n=count - 1) if count > 1 else "")
        head = self._group(self.element_page, self._element_groups, title, wid)
        head.add(self._switch_row(_("Visible"), w.get("visible", True), set_prop("visible")))
        head.add(self._switch_row(_("Lock position"), w.get("locked"), set_prop("locked")))
        styles = model.WIDGET_TYPES[widget_type][1]
        if len(styles) > 1:
            head.add(self._combo_row(_("Style"), [(s, _(STYLE_LABELS.get(s, s))) for s in styles], w["style"],
                                     set_prop("style")))
        actions = Gtk.Box(spacing=6, halign=Gtk.Align.END, margin_top=6)
        for label, handler in ((_("Duplicate"), lambda: self._act("duplicate")),
                               (_("Reset style"), lambda: self._act("reset_widget")),
                               (_("Delete"), lambda: self._act("delete"))):
            button = Gtk.Button(label=label)
            if label == _("Delete"):
                button.add_css_class("destructive-action")
            button.connect("clicked", lambda _b, h=handler: h())
            actions.append(button)
        head.add(actions)

        geometry = self._group(self.element_page, self._element_groups, _("Position and size"),
                               _("In pixels of the preview resolution."))
        x, y, bw, bh = self.state.box(w)
        tw, th = self.preview_size
        self.geo_rows = {}
        for key, label, value, high in (("x", _("X"), x, tw), ("y", _("Y"), y, th), ("w", _("Width"), bw, tw),
                                        ("h", _("Height"), bh, th)):
            row = self._spin_row(label, -high, high * 2, 1, round(value), lambda v, k=key: self._geometry_edit(k, v))
            self.geo_rows[key] = row
            geometry.add(row)
        geometry.add(self._combo_row(_("Anchor"), [(k, _(v)) for k, v in ANCHOR_LABELS], w.get("anchor", "auto"),
                                     set_prop("anchor"),
                                     _("Corner or edge the widget stays attached to on other screen sizes.")))
        geometry.add(self._spin_row(_("Rotation"), -180, 180, 5, w.get("rotation", 0), set_prop("rotation")))
        center = Gtk.Box(spacing=6, halign=Gtk.Align.END, margin_top=6)
        for label, mode in ((_("Centre H"), "hcenter"), (_("Centre V"), "vcenter")):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _b, m=mode: self._act("align", m))
            center.append(button)
        geometry.add(center)

        colors = self._group(self.element_page, self._element_groups, _("Colours and effects"))
        colors.add(self._color_row(_("Main colour"), w["color"], set_prop("color")))
        colors.add(self._color_row(_("Secondary colour"), w["color2"], set_prop("color2")))
        colors.add(self._color_row(_("Text colour"), w["text_color"], set_prop("text_color")))
        colors.add(self._scale_row(_("Glow"), 0, 100, w["glow"], set_prop("glow")))
        colors.add(self._scale_row(_("Opacity"), 10, 100, w["opacity"], set_prop("opacity")))
        colors.add(self._switch_row(_("Shadow"), w["shadow"], set_prop("shadow")))

        text = self._group(self.element_page, self._element_groups, _("Text"))
        text.add(self._font_row(_("Font"), w.get("font", "default"), set_prop("font")))
        text.add(self._switch_row(_("Bold"), w.get("bold", True), set_prop("bold")))
        text.add(self._spin_row(_("Text size (%)"), 50, 200, 5, w.get("font_scale", 100), set_prop("font_scale")))
        text.add(self._combo_row(_("Text style"), [(k, _(v)) for k, v in TEXT_STYLES], w.get("text_style", "normal"),
                                 set_prop("text_style")))
        text.add(self._combo_row(_("Alignment"), [("left", _("Left")), ("center", _("Centre")), ("right", _("Right"))],
                                 w.get("align", "left"), set_prop("align")))
        text.add(self._entry_row(_("Label (empty = automatic)"), w.get("label", ""), set_prop("label"), 24))
        text.add(self._switch_row(_("Show label"), w.get("show_label", True), set_prop("show_label")))
        text.add(self._switch_row(_("Show icon"), w.get("show_icon", True), set_prop("show_icon")))
        if widget_type in ("cpu", "gpu", "ram", "swap", "vram"):
            text.add(self._spin_row(_("Decimals"), 0, 2, 1, w.get("decimals", 0), set_prop("decimals")))
        if widget_type in model.UNITS:
            units = model.UNITS[widget_type]
            labels = {"auto_bytes": _("Automatic (KB/s, MB/s)"), "c": _("Celsius"), "f": _("Fahrenheit")}
            text.add(self._combo_row(_("Unit"), [(u, labels.get(u, u)) for u in units], w.get("unit") or units[0],
                                     set_prop("unit")))

        panel = self._group(self.element_page, self._element_groups, _("Background panel"))
        panel.add(self._color_row(_("Panel colour"), w["bg"], set_prop("bg")))
        panel.add(self._scale_row(_("Panel opacity"), 0, 100, w["bg_opacity"], set_prop("bg_opacity")))
        panel.add(self._scale_row(_("Frosted glass (blur behind)"), 0, 20, w.get("frost", 0), set_prop("frost")))
        panel.add(self._spin_row(_("Border"), 0, 8, 1, w["border"], set_prop("border")))
        panel.add(self._color_row(_("Border colour"), w["border_color"], set_prop("border_color")))
        panel.add(self._scale_row(_("Corner radius (%)"), 0, 50, w["radius"], set_prop("radius")))

        opts = model.OPTIONS.get(widget_type, {})
        if opts or widget_type not in model.STATIC_TYPES:
            data_group = self._group(self.element_page, self._element_groups, _("Data"))
            for key, spec in opts.items():
                data_group.add(self._option_row(widget_type, key, spec, w["opts"].get(key, spec[2]), set_opt(key)))
            if widget_type not in model.STATIC_TYPES:
                data_group.add(self._spin_row(_("Update interval (s)"), 0, 60, 0.5, w.get("refresh", 0),
                                              set_prop("refresh"), digits=1,
                                              subtitle=_("0 = automatic ({s} s)").format(
                                                  s=model.default_refresh(widget_type))))
                data_group.add(self._switch_row(_("Hide when unavailable"), w.get("hide_unavailable"),
                                                set_prop("hide_unavailable")))
                data_group.add(self._switch_row(_("Smooth transitions"), w.get("smooth", True), set_prop("smooth")))
        if model.WIDGET_TYPES[widget_type][5]:
            alerts = self._group(self.element_page, self._element_groups, _("Alerts"),
                                 _("Colour changes gradually towards yellow and red. 0 = automatic: the hardware "
                                   "limit when the chip reports one."))
            alerts.add(self._switch_row(_("Alerts"), w.get("alerts", True), set_prop("alerts")))
            unit = "°C" if model.WIDGET_TYPES[widget_type][5] == "temp" else "%"
            alerts.add(self._spin_row(_("Warning from ({u})").format(u=unit), 0, 200, 1, w.get("warn", 0),
                                      set_prop("warn"), digits=0))
            alerts.add(self._spin_row(_("Critical from ({u})").format(u=unit), 0, 200, 1, w.get("crit", 0),
                                      set_prop("crit"), digits=0))
            alerts.add(self._switch_row(_("Blink when critical"), w.get("blink_critical", True),
                                        set_prop("blink_critical")))

    def _option_row(self, widget_type, key, spec, value, callback):
        kind, constraint, _default = spec
        label = _(OPTION_LABELS.get(key, key))
        stats = telemetry.snapshot()
        if key == "index":
            options = [(-1, _("Automatic (dedicated card)"))]
            options += [(i, f"{i}: {g.get('name', 'GPU')}") for i, g in enumerate(stats.get("gpus") or [])
                        if g.get("path")]
            return self._combo_row(label, options, value, callback)
        if key == "mount":
            mounts = sorted({p.mountpoint for p in psutil.disk_partitions(all=False)
                             if not p.mountpoint.startswith(("/boot", "/snap", "/run", "/var/lib/docker"))})
            mounts = mounts or ["/"]
            if value not in mounts:
                mounts.append(value)
            return self._combo_row(label, [(m, m) for m in mounts], value, callback)
        if key == "iface":
            names = sorted(psutil.net_if_addrs())
            options = [("auto", _("All interfaces"))] + [(n, n) for n in names if n != "lo"]
            return self._combo_row(label, options, value, callback)
        if key == "fan":
            fans = telemetry.find_fans()
            options = [("auto", _("First spinning fan"))] + [(f["id"], f["id"]) for f in fans]
            if value not in [o[0] for o in options]:
                options.append((value, value))
            return self._combo_row(label, options, value, callback)
        if key == "temp_sensor":
            options = [("auto", _("Automatic (CPU package)"))]
            try:
                for chip, entries in psutil.sensors_temperatures().items():
                    for entry in entries:
                        sensor = f"{chip}/{entry.label or chip}"
                        if model.FONT_FAMILY.match(sensor.replace("/", "_")) and len(sensor) <= 64:
                            options.append((sensor, f"{sensor} — {entry.current:.0f}°C"))
            except Exception:  # noqa: BLE001
                pass
            return self._combo_row(label, options, value, callback)
        if kind == "bool":
            return self._switch_row(label, value, callback)
        if kind == "int":
            return self._spin_row(label, constraint[0], constraint[1], 1, value, callback)
        if kind == "choice":
            return self._combo_row(label, [(c, _(CHOICE_LABELS.get(c, c))) for c in constraint], value, callback)
        return self._entry_row(label, value, callback, constraint)

    def _geometry_edit(self, key, value):
        widget = self.state.primary()
        if widget is None:
            return
        x, y, w, h = self.state.box(widget)
        box = {"x": x, "y": y, "w": w, "h": h}
        box[key] = max(4, value) if key in ("w", "h") else value
        self.state.snapshot((widget["id"], "geometry"))
        self.state.set_boxes({widget["id"]: (box["x"], box["y"], box["w"], box["h"])}, snapshot=False)

    def _sync_geometry(self):
        widget = self.state.primary()
        rows = getattr(self, "geo_rows", {})
        if widget is None or not rows:
            return
        x, y, w, h = self.state.box(widget)
        self._syncing = True
        try:
            for key, value in (("x", x), ("y", y), ("w", w), ("h", h)):
                if key in rows and abs(rows[key].get_value() - value) >= 0.5:
                    rows[key].set_value(round(value))
        finally:
            self._syncing = False

    # -- layers tab
    def _refresh_layers(self):
        self._clear(self.layers_page, self._layer_groups)
        group = self._group(self.layers_page, self._layer_groups, _("Layers"),
                            _("Top of the list is drawn on top. Click to select."))
        selected = set(self.state.selection)
        for widget in reversed(self.state.widgets()):
            wid = widget["id"]
            row = Adw.ActionRow(title=_(model.type_label(widget["type"])), subtitle=wid + (
                f" · {_('group')} {widget['group']}" if widget.get("group") else ""), activatable=True)
            if wid in selected:
                row.add_css_class("accent")
                row.add_prefix(Gtk.Image.new_from_icon_name("object-select-symbolic"))
            eye = Gtk.ToggleButton(icon_name="view-reveal-symbolic" if widget.get("visible", True)
                                   else "view-conceal-symbolic", active=widget.get("visible", True),
                                   valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text=_("Visible"))
            eye.connect("toggled", lambda b, i=wid: self.state.set_prop(i, "visible", b.get_active()))
            lock = Gtk.ToggleButton(icon_name="changes-prevent-symbolic" if widget.get("locked")
                                    else "changes-allow-symbolic", active=widget.get("locked", False),
                                    valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text=_("Lock position"))
            lock.connect("toggled", lambda b, i=wid: self.state.set_prop(i, "locked", b.get_active()))
            row.add_suffix(eye)
            row.add_suffix(lock)
            row.connect("activated", lambda _r, i=wid: self.state.select(i))
            group.add(row)
        buttons = Gtk.Box(spacing=6, halign=Gtk.Align.END, margin_top=6)
        for icon, tip, how in (("go-top-symbolic", _("Bring to front"), "top"), ("go-up-symbolic", _("Bring forward"), "up"),
                               ("go-down-symbolic", _("Send backward"), "down"),
                               ("go-bottom-symbolic", _("Send to back"), "bottom")):
            button = Gtk.Button(icon_name=icon, tooltip_text=tip)
            button.connect("clicked", lambda _b, h=how: self._act("restack", h))
            buttons.append(button)
        group.add(buttons)

    # -- background tab
    def _refresh_background(self):
        self._syncing = True
        try:
            self._clear(self.background_page, self._background_groups)
            wp = self.state.config["wallpaper"]
            setw = lambda key: (lambda value: self.state.set_section("wallpaper", key, value))  # noqa: E731
            gallery = self._group(self.background_page, self._background_groups, _("Wallpaper"),
                                  _("Built-in art, your own images, a colour or a gradient."))
            self.gallery = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                                       min_children_per_line=2, row_spacing=6, column_spacing=6, homogeneous=True)
            for name in model.BUILTIN_WALLPAPERS:
                self.gallery.append(self._wallpaper_tile(f"builtin:{name}", _(WALLPAPER_LABELS.get(name, name)),
                                                         wp["source"]))
            for image_id, _path, _mtime in store.list_wallpapers():
                self.gallery.append(self._wallpaper_tile(f"user:{image_id}", _("Imported"), wp["source"],
                                                         deletable=True))
            gallery.add(self.gallery)
            buttons = Gtk.Box(spacing=6, halign=Gtk.Align.END, margin_top=6)
            importer = Gtk.Button(label=_("Import image…"), css_classes=["suggested-action"])
            importer.connect("clicked", lambda *_: self._import_wallpaper())
            buttons.append(importer)
            gallery.add(buttons)
            solid = self._group(self.background_page, self._background_groups, _("Colour or gradient"))
            solid.add(self._combo_row(_("Use"), [("image", _("The image above")), ("color", _("Solid colour")),
                                                 ("gradient", _("Gradient"))],
                                      wp["source"] if wp["source"] in ("color", "gradient") else "image",
                                      self._solid_mode))
            solid.add(self._color_row(_("Colour"), wp["color"], setw("color")))
            solid.add(self._color_row(_("Second colour"), wp["color2"], setw("color2")))
            solid.add(self._spin_row(_("Gradient angle"), 0, 359, 15, wp["angle"], setw("angle")))
            fit = self._group(self.background_page, self._background_groups, _("Fit and position"))
            fit.add(self._combo_row(_("Fit"), [("cover", _("Fill the screen (crop)")), ("contain", _("Fit whole image")),
                                               ("stretch", _("Stretch")), ("center", _("Centre")),
                                               ("tile", _("Tile")), ("original", _("Original size"))],
                                    wp["fit"], setw("fit")))
            fit.add(self._scale_row(_("Zoom (%)"), 100, 400, wp["zoom"], setw("zoom")))
            fit.add(self._scale_row(_("Horizontal offset"), -100, 100, wp["offset_x"], setw("offset_x")))
            fit.add(self._scale_row(_("Vertical offset"), -100, 100, wp["offset_y"], setw("offset_y")))
            fit.add(self._combo_row(_("Rotation"), [(0, "0°"), (90, "90°"), (180, "180°"), (270, "270°")],
                                    wp["rotation"], setw("rotation")))
            fit.add(self._switch_row(_("Mirror"), wp["mirror"], setw("mirror")))
            fit.add(self._switch_row(_("Flip vertically"), wp["flip"], setw("flip")))
            adjust = self._group(self.background_page, self._background_groups, _("Adjustments"))
            for key, label, low, high in (("brightness", _("Brightness"), 0, 200), ("contrast", _("Contrast"), 0, 200),
                                          ("saturation", _("Saturation"), 0, 200), ("gamma", _("Gamma"), 50, 200),
                                          ("blur", _("Blur"), 0, 20), ("darken", _("Darken"), 0, 90),
                                          ("vignette", _("Vignette"), 0, 100)):
                adjust.add(self._scale_row(label, low, high, wp[key], setw(key)))
            adjust.add(self._color_row(_("Tint colour"), wp["tint"], setw("tint")))
            adjust.add(self._scale_row(_("Tint strength"), 0, 100, wp["tint_strength"], setw("tint_strength")))
            adjust.add(self._scale_row(_("Text protection gradient"), 0, 100, wp["protect"], setw("protect")))
            adjust.add(self._combo_row(_("Gradient side"), [("bottom", _("Bottom")), ("top", _("Top")),
                                                            ("left", _("Left")), ("right", _("Right")),
                                                            ("both", _("Top and bottom"))],
                                       wp["protect_side"], setw("protect_side")))
            reset = Gtk.Button(label=_("Reset adjustments"), halign=Gtk.Align.END, margin_top=6)
            reset.connect("clicked", lambda *_: self._reset_adjustments())
            adjust.add(reset)
        finally:
            self._syncing = False

    def _wallpaper_tile(self, source, label, current, deletable=False):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, height_request=64)
        picture.add_css_class("card")
        picture.set_alternative_text(label)
        self._tile_pictures = getattr(self, "_tile_pictures", {})
        self._tile_pictures[source] = picture
        cached = getattr(self, "_thumbs", {}).get(source)
        if cached is not None:
            picture.set_paintable(cached)
        else:
            threading.Thread(target=self._tile_thumbnail, args=(source,), daemon=True).start()
        button = Gtk.Button(child=picture, css_classes=["flat"], tooltip_text=label)
        if source == current:
            button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_: self.state.set_section("wallpaper", "source", source) or
                       self._refresh_background())
        box.append(button)
        row = Gtk.Box(spacing=2)
        row.append(Gtk.Label(label=label, css_classes=["caption"], hexpand=True, xalign=0, ellipsize=3))
        if deletable:
            delete = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat"],
                                tooltip_text=_("Remove this wallpaper"))
            delete.connect("clicked", lambda *_: self._delete_wallpaper(source[5:]))
            row.append(delete)
        box.append(row)
        return box

    def _tile_thumbnail(self, source):
        try:
            texture = _texture(wallpaper.thumbnail(source, (150, 90)))
        except Exception:  # noqa: BLE001
            return
        self._thumbs = getattr(self, "_thumbs", {})
        self._thumbs[source] = texture

        def apply():
            picture = self._tile_pictures.get(source)
            if picture is not None:
                picture.set_paintable(texture)
            return False
        GLib.idle_add(apply)

    def _solid_mode(self, mode):
        wp = self.state.config["wallpaper"]
        if mode == "image":
            source = wp["source"] if wp["source"] not in ("color", "gradient") else "builtin:cyberpunk"
        else:
            source = mode
        self.state.set_section("wallpaper", "source", source)
        self._refresh_background()

    def _reset_adjustments(self):
        self.state.snapshot()
        for key, spec in model.WALLPAPER.items():
            if key not in ("source", "color", "color2", "angle"):
                self.state.config["wallpaper"][key] = spec[2]
        self.state.on_change("style")
        self._refresh_background()

    def _import_wallpaper(self):
        dialog = Gtk.FileDialog(title=_("Choose a wallpaper"))
        image_filter = Gtk.FileFilter(name=_("Images"))
        for mime in ("image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif", "image/svg+xml", "image/tiff"):
            image_filter.add_mime_type(mime)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(image_filter)
        dialog.set_filters(filters)
        dialog.open(self.window, None, self._import_chosen)

    def _import_chosen(self, dialog, result):
        try:
            path = dialog.open_finish(result).get_path()
        except GLib.Error:
            return
        self.window.toast(_("Importing the image…"))

        def worker():
            try:
                png = store.normalize_image(path)
                if _store_writable():
                    image_id, error = store.save_wallpaper(png), None
                else:
                    ok, message = self.run_helper(["import-wallpaper"], png)
                    image_id, error = (message, None) if ok else (None, message)
            except store.StoreError as exc:
                image_id, error = None, str(exc)
            GLib.idle_add(self._imported, image_id, error)
        threading.Thread(target=worker, daemon=True).start()

    def _imported(self, image_id, error):
        if error or not image_id or not model.WALLPAPER_ID.match(image_id):
            self.window._error(_("The image could not be imported"), error or _("Unknown error"))
            return False
        wallpaper.clear_cache()
        self.state.set_section("wallpaper", "source", f"user:{image_id}")
        self._refresh_background()
        self.window.toast(_("Wallpaper imported. Your original file was not changed."))
        return False

    def _delete_wallpaper(self, image_id):
        def worker():
            try:
                if _store_writable():
                    store.delete_wallpaper(image_id)
                    ok, message = True, ""
                else:
                    ok, message = self.run_helper(["remove-wallpaper", image_id])
            except (store.StoreError, OSError) as error:
                ok, message = False, str(error)

            def done():
                if not ok:
                    self.window._error(_("The wallpaper could not be removed"), message)
                    return False
                if self.state.config["wallpaper"]["source"] == f"user:{image_id}":
                    self.state.set_section("wallpaper", "source", "builtin:cyberpunk")
                wallpaper.clear_cache()
                self._refresh_background()
                return False
            GLib.idle_add(done)
        threading.Thread(target=worker, daemon=True).start()

    # -- appearance tab
    def _refresh_appearance(self):
        self._syncing = True
        try:
            self._clear(self.appearance_page, self._appearance_groups)
            theme = self.state.config["theme"]
            sett = lambda key: (lambda value: self.state.set_section("theme", key, value))  # noqa: E731
            gallery = self._group(self.appearance_page, self._appearance_groups, _("Presets"),
                                  _("Replaces the widgets with a ready-made composition (Ctrl+Z undoes it). "
                                    "An imported wallpaper is kept."))
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2, min_children_per_line=2,
                               row_spacing=6, column_spacing=6, homogeneous=True)
            self._preset_pictures = {}
            for name in presets.names():
                title, description = presets.PRESETS[name]
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True, height_request=86)
                picture.add_css_class("card")
                picture.set_alternative_text(_(title))
                thumb = getattr(self, "_preset_thumbs", {}).get(name)
                if thumb is not None:
                    picture.set_paintable(thumb)
                self._preset_pictures[name] = picture
                button = Gtk.Button(child=picture, css_classes=["flat"], tooltip_text=_(description))
                if self.state.config.get("preset") == name:
                    button.add_css_class("suggested-action")
                button.connect("clicked", lambda _b, n=name: self._apply_preset(n))
                box.append(button)
                box.append(Gtk.Label(label=_(title).replace("Kojiro ", ""), css_classes=["caption"]))
                flow.append(box)
            gallery.add(flow)
            palette = self._group(self.appearance_page, self._appearance_groups, _("Colour palette"),
                                  _("Recolours every widget with a palette."))
            pal_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, row_spacing=6,
                                  column_spacing=6)
            for label, colors in PALETTES:
                button = Gtk.Button(label=_(label))
                button.connect("clicked", lambda _b, c=colors: self.state.recolor(list(c)))
                pal_box.append(button)
            palette.add(pal_box)
            text = self._group(self.appearance_page, self._appearance_groups, _("Text and background effect"))
            text.add(self._font_row(_("Font for all widgets"), theme.get("font", "default"), sett("font")))
            text.add(self._combo_row(_("Background effect"), [("none", _("None")), ("scanlines", _("Scanlines")),
                                                              ("grid", _("Grid")), ("dots", _("Dots"))],
                                     theme["bg_effect"], sett("bg_effect")))
            text.add(self._scale_row(_("Effect strength"), 0, 100, theme["bg_effect_strength"],
                                     sett("bg_effect_strength")))
            text.add(self._color_row(_("Effect colour"), theme["bg_effect_color"], sett("bg_effect_color")))
            text.add(self._combo_row(_("Readability panels"), [("auto", _("Automatic (bright or busy areas)")),
                                                               ("always", _("Always")), ("off", _("Never"))],
                                     theme["contrast_assist"], sett("contrast_assist"),
                                     _("Adds a dark translucent panel behind widgets that would be hard to read.")))
            anim = self._group(self.appearance_page, self._appearance_groups, _("Animations and alerts"))
            anim.add(self._switch_row(_("Animations"), theme["animations"], sett("animations"),
                                      _("Fan spin, smooth values and pulses.")))
            anim.add(self._switch_row(_("Reduce motion"), theme["reduce_motion"], sett("reduce_motion")))
            anim.add(self._scale_row(_("Animation speed (%)"), 25, 300, theme["speed"], sett("speed")))
            anim.add(self._switch_row(_("Pulse on critical values"), theme["pulse"], sett("pulse")))
            anim.add(self._switch_row(_("Alerts"), theme["alerts"], sett("alerts"),
                                      _("Turns every visual alert off when disabled.")))
            anim.add(self._spin_row(_("Hysteresis"), 0, 20, 1, theme["hysteresis"], sett("hysteresis"), digits=1,
                                    subtitle=_("How far a value must drop before an alert ends.")))
            anim.add(self._spin_row(_("Cooldown (s)"), 0, 120, 1, theme["cooldown"], sett("cooldown"), digits=0,
                                    subtitle=_("Minimum time before an alert can calm down.")))
        finally:
            self._syncing = False

    def _apply_preset(self, name):
        self.state.apply_preset(name)
        self._refresh_appearance()
        self._refresh_background()
        self.window.toast(_("Preset applied. Ctrl+Z restores the previous layout."))

    def _build_thumbnails(self):
        theme = KojiroTheme(REGISTRY["kojiro"])
        thumbs = {}

        class Ctx:
            demo = True
            target_fps = 8.0
        for name in presets.names():
            try:
                image = theme.render(400, 240, {"kojiro": presets.build(name)}, Ctx())
                thumbs[name] = _texture(image)
            except Exception:  # noqa: BLE001
                continue
        self._preset_thumbs = thumbs

        def apply():
            for name, picture in getattr(self, "_preset_pictures", {}).items():
                if name in thumbs:
                    picture.set_paintable(thumbs[name])
            return False
        GLib.idle_add(apply)

    # -- general tab
    def _refresh_general(self):
        self._syncing = True
        try:
            self._clear(self.general_page, self._general_groups)
            mine = self._group(self.general_page, self._general_groups, _("My presets"),
                               _("Saved on this computer for your user."))
            for name, path in store.list_user_presets():
                row = Adw.ActionRow(title=name)
                use = Gtk.Button(label=_("Use"), valign=Gtk.Align.CENTER)
                use.connect("clicked", lambda _b, p=path: self._load_preset(p))
                delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                                    tooltip_text=_("Delete preset"))
                delete.connect("clicked", lambda _b, p=path: self._delete_preset(p))
                row.add_suffix(use)
                row.add_suffix(delete)
                mine.add(row)
            save = Gtk.Button(label=_("Save current layout as preset…"), halign=Gtk.Align.END, margin_top=6)
            save.connect("clicked", lambda *_: self._save_preset())
            mine.add(save)
            share = self._group(self.general_page, self._general_groups, _("Import and export"),
                                _("Share layouts as a .json file, or as a package that can include the wallpaper."))
            for label, handler in ((_("Export layout (.json)…"), lambda: self._export(False)),
                                   (_("Export package (.kojiro.zip)…"), lambda: self._export(True)),
                                   (_("Import layout or package…"), self._import)):
                row = Adw.ActionRow(title=label, activatable=True)
                row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                row.connect("activated", lambda _r, h=handler: h())
                share.add(row)
            restore = Adw.ActionRow(title=_("Restore the default layout"), activatable=True)
            restore.add_suffix(Gtk.Image.new_from_icon_name("edit-undo-symbolic"))
            restore.connect("activated", lambda *_: self._apply_preset("cyberpunk"))
            share.add(restore)
            lay = self._group(self.general_page, self._general_groups, _("Layout"),
                              _("Positions are stored relative to a reference resolution; anchors keep widgets in "
                                "place on other screens."))
            ref = self.state.ref()
            lay.add(Adw.ActionRow(title=_("Reference resolution"), subtitle=f"{ref[0]}×{ref[1]}"))
            rebase = Adw.ActionRow(title=_("Use the preview resolution as reference"),
                                   subtitle=_("Keeps every widget where it is now"), activatable=True)
            rebase.connect("activated", lambda *_: (self.state.rebase(), self._refresh_general()))
            lay.add(rebase)
            portrait = Adw.ActionRow(
                title=_("Portrait layout"),
                subtitle=_("Automatic (rearranged from the landscape layout)") if self.state.portrait_is_auto()
                else _("Customised"))
            if not self.state.portrait_is_auto():
                reset = Gtk.Button(label=_("Back to automatic"), valign=Gtk.Align.CENTER)
                reset.connect("clicked", lambda *_: (self.state.reset_portrait(), self._refresh_general()))
                portrait.add_suffix(reset)
            lay.add(portrait)
            lay.add(self._spin_row(_("Grid size (px)"), 4, 64, 2, self.canvas.grid,
                                   lambda v: self._canvas_flag("grid", v)))
            lay.add(self._spin_row(_("Safe margin (px)"), 0, 64, 1, self.canvas.margin,
                                   lambda v: self._canvas_flag("margin", v)))
            lay.add(self._switch_row(_("Show overlaps of the selection"), self.canvas.show_overlaps,
                                     lambda v: self._canvas_flag("show_overlaps", v)))
            keys = self._group(self.general_page, self._general_groups, _("Keyboard"))
            for combo, action in (("← ↑ → ↓", _("Move 1 px (Shift: 10 px)")), ("Del", _("Delete")),
                                  ("Ctrl+Z / Ctrl+Shift+Z", _("Undo / redo")), ("Ctrl+D", _("Duplicate")),
                                  ("Ctrl+A", _("Select all")), ("Ctrl+G", _("Group (Shift: ungroup)")),
                                  ("Ctrl+Shift+C / V", _("Copy / paste style")),
                                  ("Page Up / Down", _("Layer order (Ctrl: to front/back)")),
                                  ("Ctrl+S", _("Apply to the display")), ("Esc", _("Clear selection"))):
                keys.add(Adw.ActionRow(title=action, subtitle=combo))
        finally:
            self._syncing = False

    def _save_preset(self):
        dialog = Adw.AlertDialog(heading=_("Save preset"), body=_("Name of the preset:"))
        entry = Gtk.Entry(text=_("My layout"), max_length=40, activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_default_response("save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def done(_d, response):
            name = entry.get_text().strip()
            if response == "save" and name:
                try:
                    store.save_user_preset(name, self.state.config)
                    self.window.toast(_("Preset saved."))
                except OSError as error:
                    self.window._error(_("Could not save the preset"), str(error))
                self._refresh_general()
        dialog.connect("response", done)
        dialog.present(self.window)

    def _load_preset(self, path):
        try:
            _name, config, problems = store.load_preset_file(path)
        except store.StoreError as error:
            self.window._error(_("Could not load the preset"), str(error))
            return
        self.state.replace(config)
        self._after_replace(problems)

    def _delete_preset(self, path):
        try:
            store.delete_user_preset(path)
        except (store.StoreError, OSError) as error:
            self.window._error(_("Could not delete the preset"), str(error))
        self._refresh_general()

    def _after_replace(self, problems):
        self._refresh_background()
        self._refresh_appearance()
        self._refresh_general()
        if problems:
            self.window.toast(_("Loaded; {n} invalid values were replaced by defaults.").format(n=len(problems)))
        else:
            self.window.toast(_("Layout loaded."))

    def _export(self, package):
        dialog = Gtk.FileDialog(title=_("Export Kojiro layout"),
                                initial_name="kojiro-layout.kojiro.zip" if package else "kojiro-layout.json")
        dialog.save(self.window, None, lambda d, r: self._export_to(d, r, package))

    def _export_to(self, dialog, result, package):
        try:
            path = dialog.save_finish(result).get_path()
        except GLib.Error:
            return
        name = self.state.config.get("preset") or "Kojiro"
        if not package:
            store.export_json(self.state.config, path, name)
            self.window.toast(_("Layout exported."))
            return
        wallpaper_id = model.uses_user_wallpaper(self.state.config)

        def write(include):
            def worker():
                try:
                    theme = KojiroTheme(REGISTRY["kojiro"])

                    class Ctx:
                        demo = True
                        target_fps = 8.0
                    import io
                    thumb = theme.render(400, 240, {"kojiro": self.state.config}, Ctx())
                    buffer = io.BytesIO()
                    thumb.save(buffer, format="PNG")
                    store.export_package(self.state.config, path, name, buffer.getvalue(), include)
                    GLib.idle_add(self.window.toast, _("Package exported."))
                except (OSError, store.StoreError) as error:
                    GLib.idle_add(self.window._error, _("Could not export"), str(error))
            threading.Thread(target=worker, daemon=True).start()
        if not wallpaper_id:
            write(False)
            return
        ask = Adw.AlertDialog(heading=_("Include your wallpaper?"),
                              body=_("The layout uses an image you imported. Include it only if you have the right "
                                     "to share it; otherwise the package uses a built-in wallpaper."))
        ask.add_response("no", _("Do not include"))
        ask.add_response("yes", _("Include the image"))
        ask.connect("response", lambda _d, r: write(r == "yes"))
        ask.present(self.window)

    def _import(self):
        dialog = Gtk.FileDialog(title=_("Import Kojiro layout"))
        layouts = Gtk.FileFilter(name=_("Kojiro layouts"))
        layouts.add_pattern("*.json")
        layouts.add_pattern("*.zip")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(layouts)
        dialog.set_filters(filters)
        dialog.open(self.window, None, self._import_chosen_layout)

    def _import_chosen_layout(self, dialog, result):
        try:
            path = dialog.open_finish(result).get_path()
        except GLib.Error:
            return

        def worker():
            try:
                if path.endswith(".zip"):
                    package = store.read_package(path)
                    config, problems = package["config"], package["problems"]
                    if package["wallpaper"]:
                        if _store_writable():
                            image_id = store.save_wallpaper(package["wallpaper"])
                        else:
                            ok, message = self.run_helper(["import-wallpaper"], package["wallpaper"])
                            if not ok:
                                raise store.StoreError(message)
                            image_id = message
                        config["wallpaper"]["source"] = f"user:{image_id}"
                else:
                    _name, config, problems = store.load_preset_file(path)
                GLib.idle_add(self._imported_layout, config, problems, None)
            except (store.StoreError, OSError) as error:
                GLib.idle_add(self._imported_layout, None, [], str(error))
        threading.Thread(target=worker, daemon=True).start()

    def _imported_layout(self, config, problems, error):
        if error:
            self.window._error(_("Could not import"), error)
            return False
        wallpaper.clear_cache()
        self.state.replace(config)
        self._after_replace(problems)
        return False

    # -- advanced tab
    def _refresh_advanced(self):
        if self.inspector.get_visible_child_name() != "advanced":
            return
        self._clear(self.advanced_page, self._advanced_groups)
        stats = telemetry.snapshot()
        sensors = self._group(self.advanced_page, self._advanced_groups, _("Sensors on this computer"),
                              _("What the widgets can show. Optional sensors are read only while a visible widget "
                                "uses them."))
        cpu_temp = stats.get("cpu_temp_value")
        crit = stats.get("cpu_temp_crit")
        sensors.add(Adw.ActionRow(title=_("CPU"), subtitle=f"{stats.get('cpu_model') or '?'} · "
                                  f"{kdata.temperature_text(cpu_temp)}"
                                  + (f" · {_('limit')} {crit:.0f}°C" if crit else f" · {_('no hardware limit reported')}")))
        for index, gpu in enumerate(stats.get("gpus") or []):
            if not gpu.get("path"):
                continue
            parts = [f"{gpu.get('percent', 0):.0f}%", kdata.temperature_text(gpu.get("temp_value"))]
            if gpu.get("mem_total_mb"):
                parts.append(f"VRAM {kdata.size_text(gpu['mem_total_mb'])}")
            parts.append(_("video engine: {v}").format(v=gpu.get("video_engine") or _("not reported")))
            sensors.add(Adw.ActionRow(title=f"GPU {index}: {gpu.get('name')}", subtitle=" · ".join(parts)))
        fans = telemetry.find_fans()
        sensors.add(Adw.ActionRow(title=_("Fans"), subtitle=", ".join(f["id"] for f in fans) or _("none reported")))
        disks = stats.get("disks") or {}
        for mount, entry in disks.items():
            if entry.get("available"):
                sensors.add(Adw.ActionRow(title=_("Disk {m}").format(m=mount), subtitle=(
                    f"{entry.get('device') or '?'} · {entry['percent']:.0f}% · "
                    + (kdata.temperature_text(entry.get("temp")) if entry.get("temp") is not None
                       else _("no temperature sensor")))))
        perf = self._group(self.advanced_page, self._advanced_groups, _("Rendering"))
        perf.add(Adw.ActionRow(title=_("Last preview frame"), subtitle=f"{self.worker.render_ms:.1f} ms"))
        perf.add(Adw.ActionRow(title=_("Cached widget layers"), subtitle=str(len(self.worker.theme.layers))))
        needs = kdata.needs(self.state.widgets())
        wanted = [name for name, on in (("fans", needs["fans"]), ("processes", needs["processes"]),
                                        ("sensors", needs["sensors"]), ("addresses", needs["addrs"])) if on]
        wanted += [f"disk {m}" for m in sorted(needs["disks"])]
        perf.add(Adw.ActionRow(title=_("Optional collectors used"), subtitle=", ".join(wanted) or _("none")))
        perf.add(Adw.ActionRow(title=_("Settings size"), subtitle=f"{len(json.dumps(self.state.config)) / 1024:.1f} KB"))
        refresh = Gtk.Button(label=_("Refresh"), halign=Gtk.Align.END, margin_top=6)
        refresh.connect("clicked", lambda *_: self._refresh_advanced())
        perf.add(refresh)

    def close(self):
        self.worker.stop()
