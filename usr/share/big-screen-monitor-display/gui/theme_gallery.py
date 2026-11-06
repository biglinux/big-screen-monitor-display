"""Theme Gallery section: cards rendered by the real theme engine, and one
detail page per theme (large live preview + its options).

Thumbnails are drawn by the same ``themes.render_for_panel`` the service
uses, at the size of the selected display, in the window's thumbnail worker.
"""

import fnmatch

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk  # noqa: E402

from bsmd import runtime, themes  # noqa: E402
from bsmd.i18n import N_, _  # noqa: E402

from . import components as ui  # noqa: E402

# Sections of the window that hold the full editor of a theme.
DEDICATED = {"kojiro": "kojiro", "big_media_player": "big_media_player", "brother_away": "brother_away"}
SHORT = {"standard": N_("Clean dashboard with eight colour schemes."),
         "gkrellm": N_("Stacked monitors in the classic GKrellM style."),
         "planet": N_("The Earth lit right now, with the real Sun and Moon."),
         "old_computer": N_("A system monitor window from the classic desktop era."),
         "brother_away": N_("Animated island with 14 stories, weather and day/night."),
         "kojiro": N_("Your wallpaper with freely placed hardware widgets."),
         "big_media_player": N_("15 retro and modern players that follow your music.")}


def theme_signature(values, info):
    """Settings that change how ``info`` looks (its own keys plus common ones)."""
    patterns = list(info.preferences) + ["language", "orientation"]
    items = []
    for key, value in values.items():
        if key == "displays":
            continue
        if any(fnmatch.fnmatch(key, pattern) for pattern in patterns):
            items.append((key, repr(value)))
    return hash(tuple(sorted(items)))


def render_theme(theme_id, values, size):
    ctx = runtime.RenderContext(preview=True)
    theme = themes.create(theme_id, ctx)
    try:
        width, height = size
        image = themes.render_for_panel(theme, width, height, dict(values, theme=theme_id), ctx)
    finally:
        theme.close()
    image.thumbnail(ui.THUMB_RENDER)
    return image


class ThemeGallery:
    def __init__(self, window, nav):
        self.window = window
        self.nav = nav
        self.details = {}
        self.search = Gtk.SearchEntry(placeholder_text=_("Search themes"), hexpand=True)
        self.search.connect("search-changed", lambda _e: self._search_changed())
        search_bar = Gtk.SearchBar(child=Adw.Clamp(child=self.search, maximum_size=480), show_close_button=False)
        search_bar.connect_entry(self.search)
        search_button = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text=_("Search (Ctrl+F)"))
        search_button.bind_property("active", search_bar, "search-mode-enabled",
                                    GObject.BindingFlags.BIDIRECTIONAL)
        self.search_button = search_button

        self.grid = ui.CardGrid(self.open_theme, _("Themes"), max_columns=4)
        for info in themes.available():
            card = ui.Card(_(info.name.split(" — ")[0]), _(SHORT.get(info.id, info.description)),
                           icon="applications-graphics-symbolic")
            self.grid.add_card(info.id, card)
        self.grid.set_filter_func(self._matches)
        intro = ui.caption(_("Every preview is drawn by the same engine that feeds the display, at the size of "
                             "your display. Pick a theme to see it larger and adjust it."))
        self.empty = Adw.StatusPage(icon_name="system-search-symbolic", title=_("No theme found"),
                                    description=_("Try another word."), visible=False)
        content = ui.page_layout(intro, self.grid, self.empty, maximum=1200, spacing=12)
        self.page = ui.navigation_page(_("Theme Gallery"), content, tag="themes", header_end=[search_button])
        self.page.toolbar.add_top_bar(search_bar)
        self.grid.connect("map", lambda _g: self.refresh())

    # ------------------------------------------------------------ cards
    def _search_changed(self):
        self.grid.invalidate_filter()
        self.empty.set_visible(not any(self._matches_id(key) for key in self.grid.cards))

    def _matches(self, child):
        text = self.search.get_text().strip().lower()
        if not text:
            return True
        info = themes.REGISTRY[child.get_child().key]
        haystack = " ".join((_(info.name), _(info.description), _(SHORT.get(info.id, "")), info.id)).lower()
        return text in haystack

    def refresh(self):
        """Selection marks and thumbnails (re-rendered only when the theme's options changed)."""
        values = self.window.values
        saved = self.window.saved
        size = self.window._device_size()
        visible = 0
        for theme_id, card in self.grid.cards.items():
            info = themes.REGISTRY[theme_id]
            card.set_selected(values.get("theme") == theme_id, _("Selected"))
            in_use = saved.get("theme") == theme_id or any(
                isinstance(entry, dict) and entry.get("theme") == theme_id
                for entry in (saved.get("displays") or {}).values())
            card.set_badge(_("In use") if in_use else None)
            key = ("theme", theme_id, size, theme_signature(values, info))
            snapshot = dict(values)
            self.window.thumbnailer.request(key, lambda t=theme_id, v=snapshot: render_theme(t, v, size),
                                            card.set_texture)
            visible += 1 if self._matches_id(theme_id) else 0
        self.empty.set_visible(visible == 0)

    def _matches_id(self, theme_id):
        text = self.search.get_text().strip().lower()
        info = themes.REGISTRY[theme_id]
        return not text or text in " ".join((_(info.name), _(info.description), info.id)).lower()

    # ------------------------------------------------------------ detail pages
    def open_theme(self, theme_id):
        page = self.details.get(theme_id)
        if page is None:
            page = self._build_detail(theme_id)
            self.details[theme_id] = page
        self._sync_detail(theme_id)
        self.nav.push(page)

    def _build_detail(self, theme_id):
        info = themes.REGISTRY[theme_id]
        title = _(info.name.split(" — ")[0])
        preview = self.window.live_preview(theme_id, _("Preview of {theme}").format(theme=title), height=340)
        use = Gtk.Button(label=_("Use This Theme"), tooltip_text=_("Select it for every display; Apply sends it"))
        use.add_css_class("suggested-action")
        use.connect("clicked", lambda _b: self._use(theme_id))
        header_end = [use]
        about = Adw.PreferencesGroup(title=_("About"))
        description = Adw.ActionRow(title=_(info.description), title_lines=4)
        description.add_css_class("property")
        about.add(description)
        resolutions = Adw.ActionRow(title=_("Displays"), subtitle=_(info.resolutions), subtitle_selectable=True)
        resolutions.add_css_class("property")
        about.add(resolutions)
        if info.animated:
            animated = Adw.ActionRow(title=_("Animation"), subtitle=_("Animated; the rate follows the "
                                                                       "performance profile and the panel speed."))
            animated.add_css_class("property")
            about.add(animated)
        side = [about]
        if theme_id in DEDICATED:
            open_row = Adw.ActionRow(title=_("Open the full editor"),
                                     subtitle=_("Every option of this theme has its own section."), activatable=True)
            open_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            open_row.connect("activated", lambda _r: self.window.show_section(DEDICATED[theme_id]))
            about.add(open_row)
        else:
            side += self.window.theme_option_groups(theme_id)
        options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        for group in side:
            options.append(group)
        content = ui.page_layout(ui.adaptive_split(preview, options), maximum=1400)
        page = ui.navigation_page(title, content, tag=f"theme-{theme_id}", header_end=header_end)
        page.use_button = use
        return page

    def _sync_detail(self, theme_id):
        page = self.details.get(theme_id)
        if page is None:
            return
        selected = self.window.values.get("theme") == theme_id
        page.use_button.set_sensitive(not selected)
        page.use_button.set_label(_("Selected") if selected else _("Use This Theme"))

    def _use(self, theme_id):
        self.window._set("theme", theme_id)
        self._sync_detail(theme_id)
        self.refresh()
        self.window.toast(_("Theme selected. Press Apply to send it to the display."))

    def values_changed(self):
        for theme_id in self.details:
            self._sync_detail(theme_id)
        if self.grid.get_mapped():
            self.refresh()
