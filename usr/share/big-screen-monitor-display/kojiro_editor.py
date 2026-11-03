"""Kojiro Design Studio: editor state and the interactive canvas.

``EditorState`` owns the working copy of a Kojiro configuration, the
selection and the undo/redo history; every change goes through it so the
canvas, the inspector and the window's "unsaved changes" stay in sync.

``DesignCanvas`` shows the real engine output (rendered off the GTK thread
at the panel's resolution) and draws the editing aids on top with Cairo:
selection and handles, hover, grid, safe margins, snap guides and overlap
warnings. Widgets are moved and resized directly with the mouse or the
keyboard.
"""

import copy
import threading
import time

import cairo
import numpy as np
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from bsmd import telemetry  # noqa: E402
from bsmd.i18n import _  # noqa: E402
from bsmd.kojiro import layout, model, presets  # noqa: E402
from bsmd.kojiro.engine import KojiroTheme  # noqa: E402
from bsmd.themes import REGISTRY  # noqa: E402

HANDLE = 7          # handle size in screen pixels
MIN_SIZE = 10       # minimum widget size in panel pixels
SNAP_SCREEN = 7     # snap distance in screen pixels
UNDO_LIMIT = 100


class EditorState:
    """Working copy of one Kojiro configuration + selection + history."""

    def __init__(self, config, on_change):
        self.config = copy.deepcopy(config)
        self.on_change = on_change          # callback(kind) kind: "layout" | "style" | "selection" | "all"
        self.selection = []
        self.undo_stack = []
        self.redo_stack = []
        self.style_clipboard = None
        self.portrait = False
        self.target = (800, 480)
        self._coalesce = (None, 0.0)

    # ---------------------------------------------------------- layout access
    def widgets(self):
        """Widgets of the orientation being edited (portrait is materialised lazily)."""
        layouts = self.config["layouts"]
        if self.portrait:
            if layouts.get("portrait") is None:
                return model.layout_for(self.config, True)[0]
            return layouts["portrait"]
        return layouts["landscape"]

    def editable_widgets(self):
        layouts = self.config["layouts"]
        if self.portrait and layouts.get("portrait") is None:
            layouts["portrait"] = copy.deepcopy(model.layout_for(self.config, True)[0])
        return layouts["portrait"] if self.portrait else layouts["landscape"]

    def ref(self):
        return tuple(self.config["ref_portrait"] if self.portrait else self.config["ref"])

    def widget(self, widget_id):
        return next((w for w in self.widgets() if w["id"] == widget_id), None)

    def box(self, widget):
        return layout.to_pixels(widget, self.target, self.ref())

    def primary(self):
        return self.widget(self.selection[-1]) if self.selection else None

    def selected(self):
        ids = set(self.selection)
        return [w for w in self.widgets() if w["id"] in ids]

    def portrait_is_auto(self):
        return self.config["layouts"].get("portrait") is None

    # ---------------------------------------------------------- history
    def snapshot(self, key=None):
        """Remember the current state before a change (rapid edits of one key coalesce)."""
        now = time.monotonic()
        if key is not None and self._coalesce[0] == key and now - self._coalesce[1] < 1.0:
            self._coalesce = (key, now)
            return
        self._coalesce = (key, now)
        self.undo_stack.append((copy.deepcopy(self.config), list(self.selection)))
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append((copy.deepcopy(self.config), list(self.selection)))
        self.config, self.selection = self.undo_stack.pop()
        self._coalesce = (None, 0.0)
        self.on_change("all")
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append((copy.deepcopy(self.config), list(self.selection)))
        self.config, self.selection = self.redo_stack.pop()
        self._coalesce = (None, 0.0)
        self.on_change("all")
        return True

    def replace(self, config, kind="all"):
        self.snapshot()
        self.config = copy.deepcopy(config)
        ids = {w["id"] for w in self.widgets()}
        self.selection = [i for i in self.selection if i in ids]
        self.on_change(kind)

    # ---------------------------------------------------------- selection
    def select(self, widget_id, toggle=False):
        group = self._group_of(widget_id)
        if toggle:
            if widget_id in self.selection:
                self.selection = [i for i in self.selection if i not in group]
            else:
                self.selection += [i for i in group if i not in self.selection]
        else:
            self.selection = [i for i in group if i != widget_id] + [widget_id] if widget_id else []
        self.on_change("selection")

    def select_many(self, ids):
        self.selection = list(ids)
        self.on_change("selection")

    def _group_of(self, widget_id):
        widget = self.widget(widget_id) if widget_id else None
        if widget is None or not widget.get("group"):
            return [widget_id] if widget_id else []
        return [w["id"] for w in self.widgets() if w.get("group") == widget["group"]]

    # ---------------------------------------------------------- edits
    def set_boxes(self, boxes, snapshot=True):
        """{id: pixel box} -> normalised geometry."""
        if snapshot:
            self.snapshot()
        for widget in self.editable_widgets():
            if widget["id"] in boxes:
                widget.update(layout.from_pixels(widget, boxes[widget["id"]], self.target, self.ref()))
        self.on_change("layout")

    def set_prop(self, widget_id, key, value):
        widget = next((w for w in self.editable_widgets() if w["id"] == widget_id), None)
        if widget is None or widget.get(key) == value:
            return
        self.snapshot((widget_id, key))
        widget[key] = value
        self.on_change("layout" if key in ("anchor", "rotation", "visible") else "style")

    def set_props_selected(self, key, value):
        ids = set(self.selection)
        changed = [w for w in self.editable_widgets() if w["id"] in ids and w.get(key) != value]
        if not changed:
            return
        self.snapshot(("selection", key))
        for widget in changed:
            widget[key] = value
        self.on_change("style")

    def set_opt(self, widget_id, key, value):
        widget = next((w for w in self.editable_widgets() if w["id"] == widget_id), None)
        if widget is None or widget["opts"].get(key) == value:
            return
        self.snapshot((widget_id, "opts", key))
        widget["opts"][key] = value
        self.on_change("style")

    def set_section(self, section, key, value):
        if self.config[section].get(key) == value:
            return
        self.snapshot((section, key))
        self.config[section][key] = value
        self.on_change("style")

    def add(self, widget_type):
        widgets = self.editable_widgets()
        if len(widgets) >= model.MAX_WIDGETS:
            return None
        self.snapshot()
        ref = self.ref()
        widget = model.new_widget(widget_type, model.next_id(widgets, widget_type))
        # Default sizes are designed for 800x480: keep their proportion to the short side.
        factor = min(ref) / 480
        widget["w"] = min(0.9, widget["w"] * 800 * factor / ref[0])
        widget["h"] = min(0.9, widget["h"] * 480 * factor / ref[1])
        widget["x"], widget["y"] = 0.5 - widget["w"] / 2, 0.5 - widget["h"] / 2
        widgets.append(widget)
        self.selection = [widget["id"]]
        self.on_change("all")
        return widget

    def duplicate(self):
        widgets = self.editable_widgets()
        chosen = [w for w in widgets if w["id"] in self.selection]
        if not chosen or len(widgets) + len(chosen) > model.MAX_WIDGETS:
            return
        self.snapshot()
        new_ids = []
        shift = 12 / max(1, self.target[0])
        for widget in chosen:
            clone = copy.deepcopy(widget)
            clone["id"] = model.next_id(widgets, widget["type"])
            clone["x"] += shift
            clone["y"] += shift * self.target[0] / max(1, self.target[1])
            clone["group"] = ""
            clone["locked"] = False
            widgets.append(clone)
            new_ids.append(clone["id"])
        self.selection = new_ids
        self.on_change("all")

    def delete(self):
        if not self.selection:
            return
        self.snapshot()
        ids = set(self.selection)
        widgets = self.editable_widgets()
        widgets[:] = [w for w in widgets if w["id"] not in ids]
        self.selection = []
        self.on_change("all")

    def restack(self, how):
        """how: up, down, top, bottom (list order is the z-order)."""
        widgets = self.editable_widgets()
        ids = set(self.selection)
        if not ids:
            return
        self.snapshot()
        chosen = [w for w in widgets if w["id"] in ids]
        rest = [w for w in widgets if w["id"] not in ids]
        if how == "top":
            widgets[:] = rest + chosen
        elif how == "bottom":
            widgets[:] = chosen + rest
        else:
            order = list(widgets)
            indices = [i for i, w in enumerate(order) if w["id"] in ids]
            step = 1 if how == "up" else -1
            for i in (reversed(indices) if step > 0 else indices):
                j = i + step
                if 0 <= j < len(order) and order[j]["id"] not in ids:
                    order[i], order[j] = order[j], order[i]
            widgets[:] = order
        self.on_change("all")

    def align(self, mode):
        chosen = [w for w in self.selected() if not w.get("locked")]
        if not chosen:
            return
        boxes = layout.align({w["id"]: self.box(w) for w in chosen}, mode, self.target)
        self.set_boxes(boxes)

    def distribute(self, axis):
        chosen = [w for w in self.selected() if not w.get("locked")]
        if len(chosen) < 3:
            return
        self.set_boxes(layout.distribute({w["id"]: self.box(w) for w in chosen}, axis))

    def nudge(self, dx, dy):
        chosen = [w for w in self.selected() if not w.get("locked")]
        if not chosen:
            return
        self.snapshot(("nudge",))
        boxes = {}
        for widget in chosen:
            x, y, w, h = self.box(widget)
            boxes[widget["id"]] = (x + dx, y + dy, w, h)
        self.set_boxes(boxes, snapshot=False)

    def group(self):
        if len(self.selection) < 2:
            return
        self.snapshot()
        name = f"g{int(time.time() * 1000) % 100000}"
        for widget in self.editable_widgets():
            if widget["id"] in self.selection:
                widget["group"] = name
        self.on_change("style")

    def ungroup(self):
        self.snapshot()
        for widget in self.editable_widgets():
            if widget["id"] in self.selection:
                widget["group"] = ""
        self.on_change("style")

    STYLE_KEYS = ("color", "color2", "text_color", "bg", "bg_opacity", "frost", "border", "border_color", "radius",
                  "opacity", "glow", "shadow", "font", "bold", "font_scale", "text_style", "align")

    def copy_style(self):
        widget = self.primary()
        if widget:
            self.style_clipboard = {k: widget[k] for k in self.STYLE_KEYS if k in widget}

    def paste_style(self):
        if not self.style_clipboard or not self.selection:
            return
        self.snapshot()
        for widget in self.editable_widgets():
            if widget["id"] in self.selection:
                widget.update(self.style_clipboard)
        self.on_change("style")

    def reset_widget(self):
        widget = self.primary()
        if widget is None:
            return
        self.snapshot()
        fresh = model.new_widget(widget["type"], widget["id"])
        for key in ("x", "y", "w", "h", "anchor", "group", "locked"):
            fresh[key] = widget[key]
        target = next(w for w in self.editable_widgets() if w["id"] == widget["id"])
        target.clear()
        target.update(fresh)
        self.on_change("style")

    def apply_preset(self, name):
        config = presets.build(name)
        config["wallpaper"] = self.config["wallpaper"] if self.config["wallpaper"]["source"].startswith("user:") \
            else config["wallpaper"]
        self.selection = []
        self.replace(config)

    def recolor(self, palette):
        """Spread a palette over the widgets (each widget keeps its own colour slot)."""
        self.snapshot()
        for index, widget in enumerate(self.editable_widgets()):
            widget["color"] = palette[index % len(palette)]
            widget["border_color"] = widget["color"]
        self.on_change("style")

    def reset_portrait(self):
        self.snapshot()
        self.config["layouts"]["portrait"] = None
        self.on_change("all")

    def rebase(self):
        """Make the current preview size the reference (geometry recomputed exactly)."""
        self.snapshot()
        widgets = self.editable_widgets()
        boxes = {w["id"]: self.box(w) for w in widgets}
        key = "ref_portrait" if self.portrait else "ref"
        self.config[key] = list(self.target)
        for widget in widgets:
            widget["anchor"] = widget.get("anchor", "auto")
            widget.update(layout.from_pixels(widget, boxes[widget["id"]], self.target, self.target))
        self.on_change("all")


def pil_to_surface(image):
    """PIL RGB/RGBA -> (cairo ARGB32 surface, backing array); keep the array while the surface lives."""
    array = np.asarray(image.convert("RGBA"))
    bgra = np.ascontiguousarray(array[..., [2, 1, 0, 3]])
    height, width = bgra.shape[:2]
    surface = cairo.ImageSurface.create_for_data(memoryview(bgra), cairo.FORMAT_ARGB32, width, height, width * 4)
    return surface, bgra


class PreviewWorker:
    """Renders the Kojiro engine off the GTK thread (latest request wins)."""

    def __init__(self, on_frame):
        self.on_frame = on_frame
        self.theme = KojiroTheme(REGISTRY["kojiro"])
        self.request = None
        self.demo = False
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.active = True
        self.render_ms = 0.0
        threading.Thread(target=self._loop, name="kojiro-preview", daemon=True).start()

    def submit(self, config, size, settings_extra=None):
        self.request = (copy.deepcopy(config), tuple(size), dict(settings_extra or {}))
        self.wake.set()

    def stop(self):
        self.stop_event.set()
        self.wake.set()

    def _loop(self):
        last = None
        while not self.stop_event.is_set():
            self.wake.wait(timeout=1.0)
            self.wake.clear()
            if not self.active:
                continue
            request = self.request or last
            if request is None:
                continue
            self.request = None
            last = request
            config, size, extra = request
            ctx = _Ctx(self.demo)
            try:
                image = self.theme.render(size[0], size[1], dict(extra, kojiro=config), ctx)
            except Exception as error:  # noqa: BLE001 - keep the editor alive
                print(f"kojiro preview failed: {error!r}")
                continue
            self.render_ms = self.theme.render_ms
            GLib.idle_add(self.on_frame, image, size)
            if self.theme.animating:
                self.wake.set()
                self.stop_event.wait(1 / 8)


class _Ctx:
    preview = True
    target_fps = 8.0

    def __init__(self, demo):
        self.demo = demo

    @staticmethod
    def telemetry():
        return telemetry.snapshot()


class DesignCanvas(Gtk.DrawingArea):
    """The editing surface."""

    def __init__(self, state, on_commit):
        super().__init__(hexpand=True, vexpand=True, focusable=True, can_focus=True)
        self.state = state
        self.on_commit = on_commit
        self.surface = None
        self.surface_size = None
        self.show_grid = False
        self.snap = True
        self.grid = 16
        self.margin = 8
        self.show_margins = True
        self.show_overlaps = True
        self.hover = None
        self.drag = None
        self.guides = []
        self.marquee = None
        self.set_size_request(360, 220)
        self.set_draw_func(self._draw)
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             [_("Kojiro editor: click a widget to select it, drag to move, use the arrow keys "
                                "to nudge")])
        drag = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.add_controller(drag)
        context = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        context.connect("pressed", self._context_menu)
        self.add_controller(context)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", lambda *_: self._set_hover(None))
        self.add_controller(motion)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self.menu_actions = Gio.SimpleActionGroup()
        self.insert_action_group("canvas", self.menu_actions)

    # ---------------------------------------------------------- geometry
    def transform(self):
        """(scale, offset_x, offset_y) from panel pixels to widget pixels."""
        width, height = self.get_width(), self.get_height()
        tw, th = self.state.target
        scale = min((width - 24) / tw, (height - 24) / th)
        scale = max(0.05, scale)
        return scale, (width - tw * scale) / 2, (height - th * scale) / 2

    def to_panel(self, x, y):
        scale, ox, oy = self.transform()
        return (x - ox) / scale, (y - oy) / scale

    def boxes(self):
        return [(w, self.state.box(w)) for w in self.state.widgets() if w.get("visible", True)]

    def hit(self, px, py):
        for widget, (x, y, w, h) in reversed(self.boxes()):
            if x <= px <= x + w and y <= py <= y + h:
                return widget
        return None

    def handle_at(self, sx, sy):
        primary = self.state.primary()
        if primary is None or primary.get("locked") or len(self.state.selection) != 1:
            return None
        scale, ox, oy = self.transform()
        x, y, w, h = self.state.box(primary)
        for name, (hx, hy) in self._handles(x, y, w, h).items():
            if abs(sx - (ox + hx * scale)) <= HANDLE and abs(sy - (oy + hy * scale)) <= HANDLE:
                return name
        return None

    @staticmethod
    def _handles(x, y, w, h):
        return {"nw": (x, y), "n": (x + w / 2, y), "ne": (x + w, y), "e": (x + w, y + h / 2), "se": (x + w, y + h),
                "s": (x + w / 2, y + h), "sw": (x, y + h), "w": (x, y + h / 2)}

    # ---------------------------------------------------------- frames
    def set_frame(self, image, size):
        if tuple(size) != tuple(self.state.target):
            return False
        self.surface, self._surface_data = pil_to_surface(image)
        self.surface_size = size
        self.queue_draw()
        return False

    # ---------------------------------------------------------- drawing
    def _draw(self, _area, cr, width, height):
        cr.set_source_rgb(0.11, 0.11, 0.13)
        cr.paint()
        scale, ox, oy = self.transform()
        tw, th = self.state.target
        cr.save()
        cr.translate(ox, oy)
        cr.scale(scale, scale)
        if self.surface is not None and self.surface_size == tuple(self.state.target):
            cr.set_source_surface(self.surface, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_GOOD)
            cr.paint()
        else:
            cr.set_source_rgb(0.05, 0.05, 0.08)
            cr.rectangle(0, 0, tw, th)
            cr.fill()
        cr.restore()
        # Panel outline
        cr.set_line_width(1)
        cr.set_source_rgba(1, 1, 1, 0.25)
        cr.rectangle(ox - 0.5, oy - 0.5, tw * scale + 1, th * scale + 1)
        cr.stroke()
        if self.show_grid and self.grid:
            cr.set_source_rgba(1, 1, 1, 0.09)
            step = self.grid * scale
            x = ox
            while x <= ox + tw * scale:
                cr.move_to(round(x) + 0.5, oy)
                cr.line_to(round(x) + 0.5, oy + th * scale)
                x += step
            y = oy
            while y <= oy + th * scale:
                cr.move_to(ox, round(y) + 0.5)
                cr.line_to(ox + tw * scale, round(y) + 0.5)
                y += step
            cr.stroke()
        if self.show_margins and self.margin:
            cr.set_source_rgba(0.4, 0.8, 1, 0.35)
            cr.set_dash([4, 4])
            m = self.margin * scale
            cr.rectangle(ox + m, oy + m, tw * scale - 2 * m, th * scale - 2 * m)
            cr.stroke()
            cr.set_dash([])
        boxes = dict((w["id"], b) for w, b in self.boxes())
        if self.drag and self.drag.get("boxes"):
            boxes.update(self.drag["boxes"])
        selected = set(self.state.selection)
        if self.show_overlaps and selected:
            cr.set_source_rgba(1, 0.2, 0.3, 0.25)
            for sid in selected:
                if sid not in boxes:
                    continue
                sx, sy, sw, sh = boxes[sid]
                for oid, (bx, by, bw, bh) in boxes.items():
                    if oid in selected:
                        continue
                    ix0, iy0 = max(sx, bx), max(sy, by)
                    ix1, iy1 = min(sx + sw, bx + bw), min(sy + sh, by + bh)
                    if ix1 > ix0 and iy1 > iy0:
                        cr.rectangle(ox + ix0 * scale, oy + iy0 * scale, (ix1 - ix0) * scale, (iy1 - iy0) * scale)
            cr.fill()
        if self.hover and self.hover not in selected and self.hover in boxes:
            x, y, w, h = boxes[self.hover]
            cr.set_source_rgba(1, 1, 1, 0.6)
            cr.set_dash([3, 3])
            cr.rectangle(ox + x * scale + 0.5, oy + y * scale + 0.5, w * scale, h * scale)
            cr.stroke()
            cr.set_dash([])
        for sid in self.state.selection:
            if sid not in boxes:
                continue
            widget = self.state.widget(sid)
            x, y, w, h = boxes[sid]
            primary = sid == self.state.selection[-1]
            cr.set_source_rgba(0.21, 0.52, 0.89, 1)
            cr.set_line_width(2 if primary else 1)
            cr.rectangle(ox + x * scale, oy + y * scale, w * scale, h * scale)
            cr.stroke()
            if widget and widget.get("locked"):
                self._badge(cr, ox + x * scale + 3, oy + y * scale + 3, "🔒")
            elif primary and len(self.state.selection) == 1:
                for hx, hy in self._handles(x, y, w, h).values():
                    cx, cy = ox + hx * scale, oy + hy * scale
                    cr.set_source_rgb(1, 1, 1)
                    cr.rectangle(cx - HANDLE / 2, cy - HANDLE / 2, HANDLE, HANDLE)
                    cr.fill_preserve()
                    cr.set_source_rgb(0.21, 0.52, 0.89)
                    cr.set_line_width(1.5)
                    cr.stroke()
            if widget and widget.get("group"):
                cr.set_source_rgba(0.21, 0.52, 0.89, 0.8)
                cr.set_font_size(10)
                cr.move_to(ox + x * scale, oy + y * scale - 3)
                cr.show_text(_("group"))
        cr.set_source_rgba(0.94, 0.27, 0.86, 0.9)
        cr.set_line_width(1)
        for kind, position in self.guides:
            if kind == "v":
                cr.move_to(ox + position * scale + 0.5, oy)
                cr.line_to(ox + position * scale + 0.5, oy + th * scale)
            else:
                cr.move_to(ox, oy + position * scale + 0.5)
                cr.line_to(ox + tw * scale, oy + position * scale + 0.5)
        cr.stroke()
        if self.marquee:
            x0, y0, x1, y1 = self.marquee
            cr.set_source_rgba(0.21, 0.52, 0.89, 0.18)
            cr.rectangle(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            cr.fill_preserve()
            cr.set_source_rgba(0.21, 0.52, 0.89, 0.9)
            cr.stroke()

    @staticmethod
    def _badge(cr, x, y, text):
        cr.set_source_rgba(0, 0, 0, 0.6)
        cr.rectangle(x, y, 18, 16)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.set_font_size(11)
        cr.move_to(x + 2, y + 12)
        cr.show_text(text)

    # ---------------------------------------------------------- interaction
    def _set_hover(self, widget_id):
        if widget_id != self.hover:
            self.hover = widget_id
            self.queue_draw()

    def _motion(self, _controller, x, y):
        if self.drag:
            return
        handle = self.handle_at(x, y)
        cursors = {"nw": "nwse-resize", "se": "nwse-resize", "ne": "nesw-resize", "sw": "nesw-resize",
                   "n": "ns-resize", "s": "ns-resize", "e": "ew-resize", "w": "ew-resize"}
        if handle:
            self.set_cursor_from_name(cursors[handle])
            return
        widget = self.hit(*self.to_panel(x, y))
        self._set_hover(widget["id"] if widget else None)
        self.set_cursor_from_name("move" if widget and not widget.get("locked") else "default")

    def _modifiers(self, gesture):
        state = gesture.get_current_event_state()
        return bool(state & Gdk.ModifierType.SHIFT_MASK), bool(state & Gdk.ModifierType.CONTROL_MASK)

    def _drag_begin(self, gesture, x, y):
        self.grab_focus()
        shift, ctrl = self._modifiers(gesture)
        handle = self.handle_at(x, y)
        if handle:
            widget = self.state.primary()
            self.drag = {"mode": "resize", "handle": handle, "start": self.state.box(widget), "id": widget["id"],
                         "origin": (x, y), "boxes": {}}
            return
        widget = self.hit(*self.to_panel(x, y))
        if widget is None:
            if not (shift or ctrl):
                self.state.select(None)
            self.drag = {"mode": "marquee", "origin": (x, y), "boxes": {}}
            self.marquee = (x, y, x, y)
            return
        if shift or ctrl:
            self.state.select(widget["id"], toggle=True)
        elif widget["id"] not in self.state.selection:
            self.state.select(widget["id"])
        movable = [w for w in self.state.selected() if not w.get("locked")]
        self.drag = {"mode": "move", "origin": (x, y), "starts": {w["id"]: self.state.box(w) for w in movable},
                     "primary": widget["id"], "boxes": {}}

    def _drag_update(self, gesture, dx, dy):
        if not self.drag:
            return
        scale, _ox, _oy = self.transform()
        pdx, pdy = dx / scale, dy / scale
        mode = self.drag["mode"]
        shift, _ctrl = self._modifiers(gesture)
        threshold = SNAP_SCREEN / scale
        others = [b for w, b in self.boxes() if w["id"] not in self.state.selection]
        if mode == "marquee":
            x0, y0 = self.drag["origin"]
            self.marquee = (x0, y0, x0 + dx, y0 + dy)
        elif mode == "move" and self.drag["starts"]:
            primary = self.drag["primary"]
            start = self.drag["starts"].get(primary) or next(iter(self.drag["starts"].values()))
            moved = (start[0] + pdx, start[1] + pdy, start[2], start[3])
            if self.snap:
                snapped, self.guides = layout.snap_box(moved, others, self.state.target,
                                                       self.grid if self.show_grid else 0, threshold,
                                                       self.margin if self.show_margins else 0)
            else:
                snapped, self.guides = moved, []
            ddx, ddy = snapped[0] - start[0], snapped[1] - start[1]
            self.drag["boxes"] = {wid: (b[0] + ddx, b[1] + ddy, b[2], b[3]) for wid, b in self.drag["starts"].items()}
        elif mode == "resize":
            x, y, w, h = self.drag["start"]
            handle = self.drag["handle"]
            x1, y1 = x + w, y + h
            if "w" in handle:
                x = min(x1 - MIN_SIZE, x + pdx)
            if "e" in handle:
                x1 = max(x + MIN_SIZE, x1 + pdx)
            if "n" in handle:
                y = min(y1 - MIN_SIZE, y + pdy)
            if "s" in handle:
                y1 = max(y + MIN_SIZE, y1 + pdy)
            if shift and len(handle) == 2:      # keep proportions from the corner
                ratio = w / h
                if (x1 - x) / max(1, (y1 - y)) > ratio:
                    new_w = (y1 - y) * ratio
                    x = x1 - new_w if "w" in handle else x
                    x1 = x + new_w if "e" in handle else x1
                else:
                    new_h = (x1 - x) / ratio
                    y = y1 - new_h if "n" in handle else y
                    y1 = y + new_h if "s" in handle else y1
            self.guides = []
            if self.snap:
                xs = [0, self.state.target[0]] + [v for b in others for v in (b[0], b[0] + b[2])]
                ys = [0, self.state.target[1]] + [v for b in others for v in (b[1], b[1] + b[3])]
                if "w" in handle:
                    x, target = layout.snap_value(x, xs, threshold)
                    if target is not None:
                        self.guides.append(("v", target))
                if "e" in handle:
                    x1, target = layout.snap_value(x1, xs, threshold)
                    if target is not None:
                        self.guides.append(("v", target))
                if "n" in handle:
                    y, target = layout.snap_value(y, ys, threshold)
                    if target is not None:
                        self.guides.append(("h", target))
                if "s" in handle:
                    y1, target = layout.snap_value(y1, ys, threshold)
                    if target is not None:
                        self.guides.append(("h", target))
            self.drag["boxes"] = {self.drag["id"]: (x, y, max(MIN_SIZE, x1 - x), max(MIN_SIZE, y1 - y))}
        self.queue_draw()

    def _drag_end(self, _gesture, dx, dy):
        drag, self.drag = self.drag, None
        self.guides = []
        if drag and drag["mode"] == "marquee":
            x0, y0, x1, y1 = self.marquee or (0, 0, 0, 0)
            self.marquee = None
            if abs(x1 - x0) > 4 or abs(y1 - y0) > 4:
                a = self.to_panel(min(x0, x1), min(y0, y1))
                b = self.to_panel(max(x0, x1), max(y0, y1))
                ids = [w["id"] for w, (x, y, w_, h) in self.boxes()
                       if x >= a[0] and y >= a[1] and x + w_ <= b[0] and y + h <= b[1]]
                self.state.select_many(ids)
        elif drag and drag.get("boxes") and (abs(dx) > 1 or abs(dy) > 1):
            self.state.set_boxes(drag["boxes"])
            self.on_commit()
        self.queue_draw()

    def _key(self, _controller, keyval, _keycode, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        name = Gdk.keyval_name(keyval) or ""
        step = 10 if shift else 1
        moves = {"Left": (-step, 0), "Right": (step, 0), "Up": (0, -step), "Down": (0, step)}
        if name in moves and not ctrl:
            self.state.nudge(*moves[name])
            self.on_commit()
            return True
        if name in ("Delete", "BackSpace"):
            self.state.delete()
            self.on_commit()
            return True
        if name == "Escape":
            self.state.select(None)
            return True
        if ctrl and name.lower() == "z":
            (self.state.redo if shift else self.state.undo)()
            self.on_commit()
            return True
        if ctrl and name.lower() == "y":
            self.state.redo()
            self.on_commit()
            return True
        if ctrl and name.lower() == "d":
            self.state.duplicate()
            self.on_commit()
            return True
        if ctrl and name.lower() == "a":
            self.state.select_many([w["id"] for w in self.state.widgets() if w.get("visible", True)])
            return True
        if ctrl and name.lower() == "g":
            (self.state.ungroup if shift else self.state.group)()
            self.on_commit()
            return True
        if ctrl and shift and name.lower() == "c":
            self.state.copy_style()
            return True
        if ctrl and shift and name.lower() == "v":
            self.state.paste_style()
            self.on_commit()
            return True
        if name in ("Page_Up", "Page_Down"):
            self.state.restack(("top" if ctrl else "up") if name == "Page_Up" else ("bottom" if ctrl else "down"))
            self.on_commit()
            return True
        return False

    def _context_menu(self, gesture, _n, x, y):
        widget = self.hit(*self.to_panel(x, y))
        if widget is not None and widget["id"] not in self.state.selection:
            self.state.select(widget["id"])
        if not self.state.selection:
            return
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append(_("Duplicate"), "canvas.duplicate")
        section.append(_("Delete"), "canvas.delete")
        menu.append_section(None, section)
        order = Gio.Menu()
        order.append(_("Bring to front"), "canvas.front")
        order.append(_("Send to back"), "canvas.back")
        menu.append_section(None, order)
        other = Gio.Menu()
        primary = self.state.primary()
        other.append(_("Unlock") if primary and primary.get("locked") else _("Lock position"), "canvas.lock")
        other.append(_("Hide"), "canvas.hide")
        other.append(_("Copy style"), "canvas.copy_style")
        if self.state.style_clipboard:
            other.append(_("Paste style"), "canvas.paste_style")
        if len(self.state.selection) > 1:
            other.append(_("Group"), "canvas.group")
        if primary and primary.get("group"):
            other.append(_("Ungroup"), "canvas.ungroup")
        menu.append_section(None, other)
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(self)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.set_has_arrow(False)
        popover.popup()
