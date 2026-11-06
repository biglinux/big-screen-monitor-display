"""Brother Away section: the island preview, a gallery of the 14 stories
(thumbnails drawn by the theme itself) and the theme's options.

Choosing a story plays it in the window preview only; the display keeps
living its own day. The preview stops when the section is not on screen.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from bsmd import runtime, themes  # noqa: E402
from bsmd.i18n import N_, _  # noqa: E402

from . import components as ui  # noqa: E402

# id -> (title, seconds into the story for the thumbnail, hour of day, weather)
STORIES = (
    ("coconut_tree", N_("The rebellious palm tree"), 7, 14.0, None),
    ("philosopher", N_("The philosopher palm tree"), 15, 16.5, None),
    ("shark", N_("The mocking shark"), 16, 11.0, None),
    ("raft", N_("The impossible raft"), 8, 9.0, None),
    ("ufo", N_("The extraterrestrial encounter"), 13, 2.0, None),
    ("crab_glasses", N_("The crab and the glasses"), 13, 10.0, None),
    ("gull_lunch", N_("The seagull's lunch"), 8, 12.5, None),
    ("message_bottle", N_("Message in a bottle"), 8, 15.0, None),
    ("ship_asleep", N_("The ship that passed by"), 10, 13.0, None),
    ("mermaid", N_("The mermaid who ran away"), 10, 17.0, None),
    ("treasure", N_("The treasure"), 10, 10.5, None),
    ("stars_night", N_("A night of stars"), 8, 23.0, None),
    ("rain_complaint", N_("Complaining about the rain"), 3, 13.0, "rain"),
    ("fish_bait", N_("The fish that returned the bait"), 8, 8.5, None),
)


def render_story(story_id, seconds, hour, weather, values, size):
    ctx = runtime.RenderContext(preview=True)
    theme = themes.create("brother_away", ctx)
    try:
        theme.debug_seek(seconds, story_id, hour, weather)
        image = themes.render_for_panel(theme, size[0], size[1], dict(values, theme="brother_away"), ctx)
    finally:
        theme.close()
    image.thumbnail(ui.THUMB_RENDER)
    return image


class BrotherAwayPage:
    def __init__(self, window):
        self.window = window
        self.live = window.live_preview("brother_away", _("Preview of Brother Away"), height=340)
        self.renderer = window.renderer_of(self.live)
        intro = Adw.PreferencesGroup(title=_("Brother Away — The Perplexed Castaway!"),
                                     description=_("A castaway with opinions about everything, on the island "
                                                   "inside your display. Stories play by themselves, depending "
                                                   "on the hour, the weather and your computer."))
        self.banner = window.theme_banner("brother_away")

        stories_title = Adw.PreferencesGroup(title=_("Stories"),
                                             description=_("Choose one to watch it in the preview above. The display "
                                                           "is not interrupted."))
        self.grid = ui.CardGrid(self.play, _("Stories"), max_columns=4)
        for story_id, title, *_rest in STORIES:
            self.grid.add_card(story_id, ui.Card(_(title), icon="weather-clear-symbolic"))
        self.grid.connect("map", lambda _g: self._thumbnails())

        options = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        for group in window.theme_option_groups("brother_away"):
            options.append(group)
        content = ui.page_layout(self.banner, intro, self.live, stories_title, self.grid, options, maximum=1100)
        self.page = ui.navigation_page(_("Brother Away"), content, tag="brother_away")

    def play(self, story_id):
        self.renderer.play_story(story_id)
        title = dict((s[0], s[1]) for s in STORIES)[story_id]
        self.live.set_caption(_("Playing “{story}” in the preview").format(story=_(title)))
        self.window.toast(_("Playing “{story}” in the preview").format(story=_(title)))

    def _thumbnails(self):
        values = dict(self.window.values)
        size = self.window._device_size()
        for story_id, _title, seconds, hour, weather in STORIES:
            card = self.grid.cards[story_id]
            key = ("story", story_id, size, values.get("ba_humor"), values.get("overlay_enabled"),
                   values.get("language"))
            self.window.thumbnailer.request(
                key, lambda s=story_id, t=seconds, h=hour, w=weather: render_story(s, t, h, w, values, size),
                card.set_texture)
