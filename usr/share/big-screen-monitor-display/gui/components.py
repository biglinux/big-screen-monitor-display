"""Reusable widgets of the configuration window (AshyWall design family).

Everything here is presentation only: no settings are read or written, no
D-Bus or subprocess is touched. Rendering of thumbnails happens in one
worker thread (:class:`Thumbnailer`); widgets receive finished textures on
the GTK main loop.
"""

import collections
import os
import queue
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk, Pango  # noqa: E402

from bsmd.i18n import _  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SPACING = 12
THUMB_SIZE = (240, 150)
# Rendered thumbnails: 1.5x the card, sharp on scaled screens without holding 2x pixels.
THUMB_RENDER = (360, 225)
_CSS_LOADED = []


def load_css():
    """Install gui/style.css once for the whole display."""
    if _CSS_LOADED:
        return
    display = Gdk.Display.get_default()
    if display is None:
        return
    provider = Gtk.CssProvider()
    provider.load_from_path(os.path.join(HERE, "style.css"))
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _CSS_LOADED.append(provider)


def texture_from_image(image):
    """PIL image -> immutable Gdk texture (safe to create in a worker thread).

    Built directly in cairo's native layout (BGRA, premultiplied; opaque here), so
    GTK does not convert every preview frame again on its own threads."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    data = GLib.Bytes.new(image.tobytes("raw", "BGRA"))
    return Gdk.MemoryTexture.new(image.width, image.height, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, data,
                                 image.width * 4)


def set_label(widget, text):
    widget.update_property([Gtk.AccessibleProperty.LABEL], [text])


def caption(text, wrap=True, dim=True, xalign=0.0):
    label = Gtk.Label(label=text, wrap=wrap, xalign=xalign)
    label.add_css_class("caption")
    if dim:
        label.add_css_class("dim-label")
    return label


def pill(text, kind=None):
    label = Gtk.Label(label=text, valign=Gtk.Align.CENTER)
    label.add_css_class("status-pill")
    if kind:
        label.add_css_class(kind)
    return label


def set_pill(label, text, kind=None):
    for name in ("success", "warning", "error", "accent"):
        label.remove_css_class(name)
    if kind:
        label.add_css_class(kind)
    label.set_label(text)


def page_layout(*children, maximum=1000, spacing=24):
    """Vertically stacked content in a clamp, inside a scroller (AshyWall detail layout)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing, margin_top=18, margin_bottom=24,
                  margin_start=12, margin_end=12)
    for child in children:
        if child is not None:
            box.append(child)
    scroller = Gtk.ScrolledWindow(child=Adw.Clamp(child=box, maximum_size=maximum, tightening_threshold=600),
                                  hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    scroller.content_box = box
    return scroller


def navigation_page(title, content, tag=None, header_start=(), header_end=(), bottom=None):
    """Adw.NavigationPage with a header bar, like every AshyWall page."""
    header = Adw.HeaderBar()
    for widget in header_start:
        header.pack_start(widget)
    for widget in reversed(list(header_end)):
        header.pack_end(widget)
    toolbar = Adw.ToolbarView(content=content)
    toolbar.add_top_bar(header)
    if bottom is not None:
        toolbar.add_bottom_bar(bottom)
    page = Adw.NavigationPage(child=toolbar, title=title, tag=tag) if tag else \
        Adw.NavigationPage(child=toolbar, title=title)
    page.header = header
    page.toolbar = toolbar
    return page


class Adaptive:
    """Boxes that are side by side on wide windows and stacked on narrow ones.

    Driven by one window breakpoint (``attach``): a BreakpointBin would clip
    content inside scrolled pages, because it does not report its child's
    natural height.
    """

    def __init__(self):
        self.narrow = False
        self.boxes = []

    def attach(self, window, collapse_targets=(), wide="max-width: 1100sp", narrow="max-width: 640sp"):
        """Two window breakpoints (libadwaita applies only the last matching one):
        ``wide`` stacks the adaptive boxes; ``narrow`` also sets ``collapse_targets``
        ((object, property, value) setters, e.g. the split view's "collapsed")."""
        medium = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(wide))
        small = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(narrow))
        for target, prop, value in collapse_targets:
            small.add_setter(target, prop, value)
        window.add_breakpoint(medium)
        window.add_breakpoint(small)
        window.connect("notify::current-breakpoint",
                       lambda w, _p: self.set_narrow(w.get_current_breakpoint() is not None))

    def set_narrow(self, narrow):
        self.narrow = narrow
        self.boxes = [box for box in self.boxes if True]
        for box in self.boxes:
            self._apply(box)

    def _apply(self, box):
        box.set_orientation(Gtk.Orientation.VERTICAL if self.narrow else Gtk.Orientation.HORIZONTAL)
        if isinstance(box, Gtk.Paned):
            return
        box.set_homogeneous(not self.narrow)       # stacked: each part takes its own height
        box.set_spacing(18 if self.narrow else 24)
        for child in (box.get_first_child(), box.get_last_child()):
            if child is not None:
                child.set_valign(Gtk.Align.FILL if self.narrow else Gtk.Align.START)

    def add(self, box):
        self.boxes.append(box)
        self._apply(box)
        return box


ADAPTIVE = Adaptive()


def adaptive_split(first, second, threshold=None, ratio=None):
    """Side by side when the window is wide, stacked when narrow (see :class:`Adaptive`)."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24, homogeneous=True)
    first.set_hexpand(True)
    second.set_hexpand(True)
    box.append(first)
    box.append(second)
    return ADAPTIVE.add(box)


# ---------------------------------------------------------------- display preview

class DisplayPreview(Gtk.Box):
    """A USB panel drawn as a bezel with the real rendered frame inside.

    Keeps the panel's aspect ratio, never upscales blurrily beyond the frame
    (``Gtk.ContentFit.CONTAIN``), shows an optional badge (DEMO, state) and
    opens a large viewer that shares the same live paintable.
    """

    __gtype_name__ = "BsmdDisplayPreview"
    __gsignals__ = {"visible-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,))}

    def __init__(self, description, height=300, ratio=1.5, expandable=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        # SCALE_DOWN: the panel's pixels are shown 1:1 when they fit (sharp, and no
        # per-frame scaling on the GTK thread); larger panels are reduced.
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.SCALE_DOWN, can_shrink=True)
        self.picture.set_alternative_text(description)
        set_label(self.picture, description)
        self.description = description
        overlay = Gtk.Overlay(child=self.picture)
        self.badge = Gtk.Label(halign=Gtk.Align.START, valign=Gtk.Align.START, visible=False)
        self.badge.add_css_class("preview-badge")
        overlay.add_overlay(self.badge)
        self.spinner = Adw.Spinner(width_request=28, height_request=28, halign=Gtk.Align.CENTER,
                                   valign=Gtk.Align.CENTER)
        overlay.add_overlay(self.spinner)
        bezel = Gtk.Box()
        bezel.add_css_class("display-bezel")
        overlay.set_hexpand(True)
        overlay.set_vexpand(True)
        bezel.append(overlay)
        self.aspect = Gtk.AspectFrame(child=bezel, obey_child=False, ratio=ratio)
        self.aspect.set_size_request(-1, min(height, 180))
        self.append(self.aspect)
        # Caption and the enlarge button sit under the panel, never over its content.
        footer = Gtk.Box(spacing=6)
        self.caption = caption("", xalign=0.0)
        self.caption.set_hexpand(True)
        footer.append(self.caption)
        if expandable:
            button = Gtk.Button(child=Adw.ButtonContent(icon_name="view-fullscreen-symbolic", label=_("Enlarge")),
                                tooltip_text=_("Enlarge preview"), halign=Gtk.Align.END)
            button.add_css_class("flat")
            set_label(button, _("Enlarge preview"))
            button.connect("clicked", lambda _b: self.open_viewer())
            footer.append(button)
        self.append(footer)
        self.picture.connect("map", lambda _w: self.emit("visible-changed", True))
        self.picture.connect("unmap", lambda _w: self.emit("visible-changed", False))
        self.picture.connect("notify::paintable", lambda p, _x: self.spinner.set_visible(p.get_paintable() is None))

    def set_ratio(self, width, height):
        if width and height:
            # The bezel adds 20 px around the frame; close enough for the ratio.
            self.aspect.set_ratio(width / height)

    def set_badge(self, text=None, demo=False):
        self.badge.set_visible(bool(text))
        self.badge.set_label(text or "")
        if demo:
            self.badge.add_css_class("demo")
        else:
            self.badge.remove_css_class("demo")

    def set_caption(self, text):
        self.caption.set_label(text or "")

    def open_viewer(self):
        """Large view of the same live paintable (nothing is sent to the display)."""
        root = self.get_root()
        dialog = Adw.Dialog(title=self.description, content_width=1100, content_height=720)
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, hexpand=True, vexpand=True)
        set_label(picture, self.description)
        binding = self.picture.bind_property("paintable", picture, "paintable", GObject.BindingFlags.SYNC_CREATE)
        bezel = Gtk.Box(margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        bezel.add_css_class("display-bezel")
        bezel.append(picture)
        frame = Gtk.AspectFrame(child=bezel, obey_child=False, ratio=self.aspect.get_ratio())
        toolbar = Adw.ToolbarView(content=frame)
        toolbar.add_css_class("preview-viewer")
        toolbar.add_top_bar(Adw.HeaderBar())
        dialog.set_child(toolbar)
        dialog.connect("closed", lambda _d: binding.unbind())
        dialog.present(root)


# ---------------------------------------------------------------- cards

class ThumbPicture(Gtk.Picture):
    """Picture whose natural size is the card's, not its texture's (rendered at 1.5x),
    so galleries fit as many columns as AshyWall's."""

    __gtype_name__ = "BsmdThumbPicture"

    def do_measure(self, orientation, for_size):
        minimum, natural, min_base, nat_base = Gtk.Picture.do_measure(self, orientation, for_size)
        if orientation == Gtk.Orientation.HORIZONTAL:
            return minimum, max(minimum, min(natural, THUMB_SIZE[0])), -1, -1
        return minimum, max(minimum, min(natural, THUMB_SIZE[1])), min_base, nat_base


class Card(Gtk.Box):
    """Gallery card: thumbnail with badges, title and a caption (AshyWall WallpaperCard)."""

    __gtype_name__ = "BsmdCard"

    def __init__(self, title, subtitle="", size=THUMB_SIZE, fit=Gtk.ContentFit.CONTAIN, icon=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.key = None
        self.picture = ThumbPicture(content_fit=fit, can_shrink=True)
        self.picture.set_size_request(*size)
        self.placeholder = Gtk.Image(icon_name=icon or "image-x-generic-symbolic", pixel_size=32)
        self.placeholder.add_css_class("dim-label")
        self.check = Gtk.Image(icon_name="object-select-symbolic", halign=Gtk.Align.END, valign=Gtk.Align.START,
                               visible=False)
        self.check.add_css_class("card-badge")
        self.check.add_css_class("accent")
        self.badge = Gtk.Label(halign=Gtk.Align.START, valign=Gtk.Align.START, visible=False)
        self.badge.add_css_class("preview-badge")
        self.frame = Gtk.Overlay(child=self.picture, overflow=Gtk.Overflow.HIDDEN)
        self.frame.add_css_class("thumbnail-frame")
        for overlay in (self.placeholder, self.check, self.badge):
            self.frame.add_overlay(overlay)
        self.title = Gtk.Label(label=title, xalign=0, ellipsize=Pango.EllipsizeMode.END, width_chars=1,
                               max_width_chars=1, hexpand=True)
        self.title.add_css_class("heading")
        self.subtitle = Gtk.Label(label=subtitle, xalign=0, ellipsize=Pango.EllipsizeMode.END, width_chars=1,
                                  max_width_chars=1, hexpand=True)
        self.subtitle.add_css_class("caption")
        self.subtitle.add_css_class("dim-label")
        self.append(self.frame)
        self.append(self.title)
        self.append(self.subtitle)
        self.subtitle.set_visible(bool(subtitle))
        self._update_accessible()

    def set_texture(self, texture):
        self.picture.set_paintable(texture)
        self.placeholder.set_visible(texture is None)

    def set_selected(self, selected, tooltip=None):
        self.check.set_visible(selected)
        self.check.set_tooltip_text(tooltip)
        if selected:
            self.frame.add_css_class("selected")
        else:
            self.frame.remove_css_class("selected")
        self._update_accessible()

    def set_badge(self, text=None):
        self.badge.set_visible(bool(text))
        self.badge.set_label(text or "")
        self._update_accessible()

    def set_text(self, title=None, subtitle=None):
        if title is not None:
            self.title.set_label(title)
        if subtitle is not None:
            self.subtitle.set_label(subtitle)
            self.subtitle.set_visible(bool(subtitle))
        self._update_accessible()

    def _update_accessible(self):
        parts = [self.title.get_label(), self.subtitle.get_label()]
        if self.badge.get_visible():
            parts.append(self.badge.get_label())
        if self.check.get_visible():
            parts.append(self.check.get_tooltip_text() or _("Selected"))
        set_label(self, ", ".join(p for p in parts if p))


class CardGrid(Gtk.FlowBox):
    """Keyboard-navigable grid of :class:`Card` (FlowBox: these galleries hold tens of
    items, so a virtualised GridView would only add a model layer)."""

    __gtype_name__ = "BsmdCardGrid"

    def __init__(self, on_activate, label, max_columns=5):
        super().__init__(homogeneous=True, min_children_per_line=1, max_children_per_line=max_columns,
                         selection_mode=Gtk.SelectionMode.NONE, activate_on_single_click=True,
                         column_spacing=0, row_spacing=0, valign=Gtk.Align.START)
        self.add_css_class("card-grid")
        set_label(self, label)
        self.cards = {}
        self.connect("child-activated", lambda _g, child: on_activate(child.get_child().key))

    def add_card(self, key, card):
        card.key = key
        self.cards[key] = card
        self.append(card)
        return card

    def clear(self):
        self.remove_all()
        self.cards = {}

    def filter(self, predicate):
        self.set_filter_func(lambda child: predicate(child.get_child().key))


def action_tile(icon, title, callback, tooltip=None):
    """Large flat button with an icon over a label (dashboard quick actions)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.append(Gtk.Image(icon_name=icon))
    label = Gtk.Label(label=title, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=16)
    box.append(label)
    button = Gtk.Button(child=box, tooltip_text=tooltip or title)
    button.add_css_class("action-tile")
    button.add_css_class("card")
    set_label(button, title)
    button.connect("clicked", lambda _b: callback())
    return button


class StateCard(Gtk.Box):
    """Problem or onboarding card: icon, title, explanation and up to two actions."""

    __gtype_name__ = "BsmdStateCard"

    def __init__(self):
        super().__init__(spacing=18, visible=False)
        self.add_css_class("state-card")
        self.add_css_class("card")
        self.icon = Gtk.Image(valign=Gtk.Align.START)
        self.icon.add_css_class("state-icon")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self.title = Gtk.Label(xalign=0, wrap=True)
        self.title.add_css_class("title-4")
        self.body = Gtk.Label(xalign=0, wrap=True)
        self.body.add_css_class("dim-label")
        text.append(self.title)
        text.append(self.body)
        self.buttons = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        self.append(self.icon)
        self.append(text)
        self.append(self.buttons)
        self._kind = None

    def show(self, kind, icon, title, body, actions=()):
        if self._kind:
            self.remove_css_class(self._kind)
        self._kind = kind
        if kind:
            self.add_css_class(kind)
        self.icon.set_from_icon_name(icon)
        self.title.set_label(title)
        self.body.set_label(body)
        while (child := self.buttons.get_first_child()) is not None:
            self.buttons.remove(child)
        for index, (label, callback) in enumerate(actions):
            button = Gtk.Button(label=label)
            button.add_css_class("pill")
            if index == 0:
                button.add_css_class("suggested-action")
            button.connect("clicked", lambda _b, cb=callback: cb())
            self.buttons.append(button)
        self.set_visible(True)

    def hide(self):
        self.set_visible(False)


# ---------------------------------------------------------------- background rendering

class Thumbnailer:
    """One worker thread renders gallery thumbnails; newest requests first.

    ``request(key, work, callback)`` runs ``work()`` (returns a PIL image or a
    texture) in the worker and calls ``callback(texture)`` on the main loop.
    Results are kept in a small LRU, so returning to a gallery is free;
    ``invalidate()`` drops them after the settings change.
    """

    def __init__(self, capacity=64):
        self.capacity = capacity
        self.cache = collections.OrderedDict()
        self.pending = collections.OrderedDict()
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.generation = 0
        self.thread = threading.Thread(target=self._loop, name="thumbnails", daemon=True)
        self.thread.start()

    def cached(self, key):
        with self.lock:
            texture = self.cache.get(key)
            if texture is not None:
                self.cache.move_to_end(key)
            return texture

    def request(self, key, work, callback):
        texture = self.cached(key)
        if texture is not None:
            callback(texture)
            return
        with self.lock:
            callbacks = self.pending.pop(key, (work, []))[1]
            callbacks.append(callback)
            self.pending[key] = (work, callbacks)
            self.pending.move_to_end(key, last=False)          # newest first
        self.wake.set()

    def invalidate(self, prefix=None):
        with self.lock:
            self.generation += 1
            if prefix is None:
                self.cache.clear()
            else:
                for key in [k for k in self.cache if k[0] == prefix]:
                    del self.cache[key]

    def stop(self):
        self.stop_event.set()
        self.wake.set()

    def _loop(self):
        while not self.stop_event.is_set():
            self.wake.wait()
            self.wake.clear()
            while not self.stop_event.is_set():
                with self.lock:
                    if not self.pending:
                        break
                    key, (work, callbacks) = self.pending.popitem(last=False)
                    generation = self.generation
                try:
                    result = work()
                    texture = result if isinstance(result, Gdk.Texture) else (
                        texture_from_image(result) if result is not None else None)
                except Exception as error:  # noqa: BLE001 - a broken thumbnail must not stop the others
                    print(f"thumbnail {key!r} failed: {error!r}")
                    texture = None
                if texture is not None:
                    with self.lock:
                        if generation == self.generation:
                            self.cache[key] = texture
                            while len(self.cache) > self.capacity:
                                self.cache.popitem(last=False)
                for callback in callbacks:
                    GLib.idle_add(lambda cb=callback, t=texture: cb(t) and False)


class SerialWorker:
    """Runs blocking calls (sysfs scans, systemctl, file reads) off the main loop,
    one at a time, dropping a job of the same name that is still queued."""

    def __init__(self):
        self.jobs = queue.Queue()
        self.queued = set()
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, name="gui-worker", daemon=True).start()

    def submit(self, name, work, done=None):
        with self.lock:
            if name in self.queued:
                return
            self.queued.add(name)
        self.jobs.put((name, work, done))

    def _loop(self):
        while True:
            name, work, done = self.jobs.get()
            with self.lock:
                self.queued.discard(name)
            try:
                result, error = work(), None
            except Exception as problem:  # noqa: BLE001 - reported to the caller
                result, error = None, problem
            if done is not None:
                GLib.idle_add(lambda r=result, e=error, d=done: d(r, e) and False)
