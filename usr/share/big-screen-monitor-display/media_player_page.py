"""Big Media Player tab of the configuration window.

The USB panels are output-only (no touch, no buttons), so the real playback
controls live here: they act on the MPRIS player the display follows. The
window embeds the same media core as the session agent (on GTK's own GLib
loop) for the live preview, and sends commands through the agent's D-Bus
interface when the agent runs, so window and display always agree on the
player. Options are edited like every other tab and saved with "Apply".
"""

import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from bsmd import runtime, settings, themes  # noqa: E402
from bsmd.bigmedia import skins  # noqa: E402
from bsmd.i18n import N_, _  # noqa: E402
from bsmd.media import agent as media_agent, artwork, hub, model  # noqa: E402

THEME_ID = "big_media_player"
SKIN_INSPIRATION = {
    "bigamp": N_("Inspired by the classic Winamp 2.x look"),
    "bigmatch": N_("Inspired by the Musicmatch Jukebox era"),
    "bigative": N_("Inspired by Creative's hi-fi style players"),
    "bigalplayer": N_("Inspired by the classic RealPlayer window"),
    "bigmediaplayer": N_("Inspired by the Windows 9x media player"),
    "bigxmms2": N_("Inspired by XMMS2 terminal clients"),
    "bigx": N_("Inspired by the X Multimedia System (XMMS)"),
}
MODERN_INSPIRATION = {
    "big_vinyl": N_("Record sleeve and turntable feel"),
    "big_pure": N_("Minimal light product design"),
    "big_ember": N_("Premium hi-fi with amber light"),
    "big_groove": N_("Textured case and vivid gradient"),
    "big_lounge": N_("Calm living-room media centre"),
    "big_wave": N_("Minimal player with waveform"),
    "big_flow": N_("Modern streaming now-playing card"),
    "big_stage": N_("Cinematic live-show experience"),
}
COLLECTION_LABELS = {"classic": N_("Classic"), "modern": N_("Modern")}
THUMB = (192, 128)
STATUS_LABELS = {"Playing": N_("Playing"), "Paused": N_("Paused"), "Stopped": N_("Stopped")}


def _short(text, limit=60):
    return text if len(text) <= limit else text[:limit - 1] + "…"


class MediaPlayerPage:
    def __init__(self, window, run_helper):
        self.window = window
        self.run_helper = run_helper
        self.core = None
        self.local_hub = None
        self.conn = None
        self.agent_ok = False
        self.agent_info = {}
        self.players = []
        self.player = None
        self._seeking = False
        self._volume_lock = False
        self._dropdown_lock = False
        self._thumbs = {}
        self.active = False
        self.widget = self._build()
        GLib.timeout_add(1000, self._tick)

    # ------------------------------------------------------------ media core
    def ensure_core(self):
        """Start the in-process media core (preview data + fallback controls)."""
        if self.core is not None:
            return True
        try:
            self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as error:
            self.status_row.set_subtitle(_("No session D-Bus: {error}").format(error=error.message))
            return False
        self.local_hub = hub.MediaHub()
        hub.set_local(self.local_hub)
        uid = hub.local_uid()
        self.core = media_agent.MediaCore(
            self.conn, self.window.values, sink=lambda message, coalesce=None: self.local_hub.on_message(uid, message),
            on_state=lambda: GLib.idle_add(self._refresh_now))
        self.core.start()
        return True

    def close(self):
        if self.core is not None:
            self.core.stop()
            self.core = None
        hub.set_local(None)

    def set_active(self, active):
        self.active = active
        if active:
            self.ensure_core()
            self._render_thumbs()

    def reload(self):
        """Settings were reverted/restored in the window."""
        if self.core is not None:
            self.core.apply_settings(self.window.values)

    def values_changed(self):
        if self.core is not None:
            self.core.apply_settings(self.window.values)

    # ------------------------------------------------------------ commands
    def command(self, action, value=0.0, bus=""):
        def reply(ok, message):
            if not ok and message:
                GLib.idle_add(self.window.toast, self._explain(message))
            GLib.idle_add(self._refresh_now)

        if self.agent_ok and self.conn is not None:
            def done(conn, result):
                try:
                    ok, message = conn.call_finish(result).unpack()
                except GLib.Error as error:
                    ok, message = False, error.message
                reply(ok, message)
            self.conn.call(media_agent.BUS_NAME, media_agent.OBJECT_PATH, media_agent.INTERFACE, "Command",
                           GLib.Variant("(ssd)", (action, bus, float(value))), GLib.VariantType("(bs)"),
                           Gio.DBusCallFlags.NONE, 4000, None, done)
            if action == "select" and self.core is not None:
                self.core.command(action, bus, value)          # keep the preview on the same player
            return
        if self.ensure_core():
            self.core.command(action, bus, value, reply)

    @staticmethod
    def _explain(message):
        known = {
            "no media player": _("No MPRIS media player found."),
            "not supported by this player": _("This control is not available for the current media."),
            "seeking is not supported": _("Seeking is not available for this media."),
            "no volume backend": _("The system volume could not be accessed."),
            "volume unknown": _("The system volume could not be accessed."),
            "this player has no own volume": _("This player does not expose its own volume."),
        }
        return known.get(message, message)

    # ------------------------------------------------------------ building
    def _build(self):
        w = self.window
        page = Adw.PreferencesPage()
        preview = w._group(_("Big Media Player"),
                           _("Classic and modern players that follow the music and videos playing on this "
                             "computer (MPRIS)."))
        preview.add(w.pictures[THEME_ID])
        page.add(preview)
        page.add(self._now_playing_group())
        page.add(self._gallery_group())

        look = w._group(_("Appearance"))
        look.add(w._combo("bmp_layout", _("Layout"), [
            ("auto", _("Automatic for the display size")), ("full", _("Complete")), ("compact", _("Compact")),
            ("party", _("Audio / party (big art and visualizer)")), ("info", _("Information (more metadata)")),
            ("cinema", _("Cinema (picture edge to edge; modern skins)")),
            ("low_power", _("Low power (no animation)"))]))
        look.add(w._combo("bmp_animations", _("Animations"), [
            ("auto", _("Automatic")), ("off", _("Off (reduced motion)")), ("economy", _("Economical")),
            ("balanced", _("Balanced")), ("fluid", _("Fluid"))],
            _("Never faster than the display can receive; Off also stops scrolling text.")))
        look.add(w._combo("bmp_text_size", _("Text size"), [("small", _("Small")), ("normal", _("Normal")),
                                                          ("large", _("Large"))]))
        look.add(w._combo("bmp_art_size", _("Album art size"), [("small", _("Small")), ("normal", _("Normal")),
                                                              ("large", _("Large"))]))
        look.add(w._combo("bmp_art_shape", _("Album art shape"), [
            ("skin", _("As the skin")), ("square", _("Square")), ("rounded", _("Rounded")), ("circle", _("Round"))]))
        look.add(w._combo("bmp_art_frame", _("Album art frame"), [
            ("skin", _("As the skin")), ("metal", _("Metal")), ("neon", _("Neon")), ("none", _("None"))]))
        look.add(w._switch("bmp_art_glow", _("Glow around the album art")))
        look.add(w._switch("bmp_art_background", _("Blurred album art behind the text")))
        look.add(w._switch("bmp_vinyl", _("Vinyl mode"), _("The cover turns like a record while playing.")))
        look.add(w._switch("bmp_adaptive_colors", _("Colours from the album art"),
                           _("Highlights take a colour of the cover, keeping the contrast readable.")))
        look.add(w._switch("bmp_lcd_effect", _("LCD texture")))
        look.add(w._switch("bmp_transitions", _("Cover transition when the track changes")))
        page.add(look)
        page.add(self._modern_group())

        meta = w._group(_("Metadata"), _("Only what the player reports is shown; nothing is invented."))
        for key, title in (("bmp_show_title", _("Title")), ("bmp_show_artist", _("Artist")),
                           ("bmp_show_album", _("Album")), ("bmp_show_description", _("Description")),
                           ("bmp_show_source", _("Source application"))):
            meta.add(w._switch(key, title))
        meta.add(w._switch("bmp_marquee", _("Scroll long titles")))
        meta.add(w._combo("bmp_marquee_speed", _("Scrolling speed"), [("slow", _("Slow")), ("normal", _("Normal")),
                                                                    ("fast", _("Fast"))]))
        meta.add(w._combo("bmp_logo", _("Distribution logo"), [
            ("auto", _("Detected automatically")), ("custom", _("Custom image")), ("none", _("Hidden"))]))
        meta.add(w._combo("bmp_logo_style", _("Logo display"), [
            ("logo_name", _("Logo and name")), ("logo", _("Logo only")), ("name", _("Name only"))]))
        logo_row = Adw.ActionRow(title=_("Custom logo"), subtitle=_("PNG, JPEG, WebP or SVG"))
        button = Gtk.Button(label=_("Choose…"), valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda *_a: self._choose_logo())
        logo_row.add_suffix(button)
        meta.add(logo_row)
        page.add(meta)

        play = w._group(_("Playback"))
        play.add(w._combo("bmp_player_mode", _("Player shown"), [
            ("auto", _("Automatic (recommended)")), ("last", _("Last used")), ("fixed", _("Always the same player"))],
            _("Automatic keeps the playing player and ignores short clips from other tabs.")))
        play.add(self._entry("bmp_player_fixed", _("Fixed player"), _("Part of the name, e.g. spotify, vlc, firefox")))
        play.add(self._entry("bmp_player_ignore", _("Ignored applications"),
                             _("Comma separated, e.g. chromium, kdeconnect")))
        play.add(w._switch("bmp_auto_switch", _("Switch automatically"),
                           _("Follow another player when it starts playing while the current one is paused.")))
        play.add(w._switch("bmp_show_controls", _("Show the transport keys")))
        play.add(w._combo("bmp_time_mode", _("Time on the right"), [("total", _("Total duration")),
                                                                   ("remaining", _("Remaining time"))]))
        play.add(w._switch("bmp_show_percent", _("Show percentage")))
        play.add(w._switch("bmp_preview_demo", _("Demonstration data in the preview"),
                           _("Used only in this window when no player is found; marked DEMO.")))
        page.add(play)

        vol = w._group(_("Volume"))
        vol.add(w._switch("bmp_show_volume", _("Show volume")))
        vol.add(w._combo("bmp_volume_source", _("Volume shown"), [
            ("system", _("System output (recommended)")), ("player", _("Player's own volume, when available"))]))
        vol.add(w._switch("bmp_volume_percent", _("Show percentage")))
        vol.add(w._switch("bmp_show_output", _("Show output device name")))
        vol.add(w._scale("bmp_volume_step", _("Step of the volume keys"), 1, 20, 1))
        vol.add(w._scale("bmp_volume_max", _("Safe maximum"), 100, 150, 5,
                         _("Above 100 % the audio is amplified and may distort.")))
        vol.add(w._combo("bmp_volume_osd", _("Enlarged volume after a change"), [
            ("modern", _("Modern skins")), ("all", _("All skins")), ("off", _("Off"))]))
        self.output_row = Adw.ComboRow(title=_("Output followed"))
        self.output_row.set_model(Gtk.StringList.new([_("Default output")]))
        self.output_row.connect("notify::selected", self._on_output_selected)
        vol.add(self.output_row)
        page.add(vol)

        tele = w._group(_("Telemetry"), _("Hardware data from the same collector the other themes use."))
        tele.add(w._combo("bmp_tele_mode", _("Mode"), [
            ("auto", _("Automatic for the display size")), ("always", _("Always visible")), ("hidden", _("Hidden")),
            ("intermittent", _("Intermittent")), ("alternate", _("Alternating with media details")),
            ("paused", _("Only when paused")), ("idle", _("After a while without track changes")),
            ("alerts", _("Only on alerts"))]))
        tele.add(w._combo("bmp_tele_position", _("Position"), [
            ("bottom", _("Bottom")), ("top", _("Top")), ("overlay", _("Over the album art"))]))
        tele.add(w._scale("bmp_tele_every", _("Interval (s)"), 10, 600, 5))
        tele.add(w._scale("bmp_tele_duration", _("Duration (s)"), 3, 60, 1))
        tele.add(w._scale("bmp_tele_idle_after", _("Without track changes for (s)"), 10, 1800, 10))
        tele.add(w._scale("bmp_tele_alert_cpu", _("CPU alert (%)"), 50, 100, 1))
        tele.add(w._scale("bmp_tele_alert_temp", _("Temperature alert (°C)"), 50, 110, 1))
        for key, title in (("bmp_tele_clock", _("Clock")), ("bmp_tele_cpu", _("CPU")),
                           ("bmp_tele_cpu_temp", _("CPU temperature")), ("bmp_tele_ram", _("RAM")),
                           ("bmp_tele_swap", _("Swap")), ("bmp_tele_disk", _("Disk")), ("bmp_tele_gpu", _("GPU")),
                           ("bmp_tele_gpu_temp", _("GPU temperature")), ("bmp_tele_icons", _("Icons")),
                           ("bmp_tele_animate", _("Slide-in animation"))):
            tele.add(w._switch(key, title))
        tele.add(w._combo("bmp_tele_separator", _("Separator"), [("bar", "|"), ("dot", "•"), ("space", _("Space"))]))
        tele.add(w._scale("bmp_tele_opacity", _("Opacity over the art (%)"), 30, 100, 5))
        page.add(tele)

        vis = w._group(_("Visualizer"),
                       _("MPRIS carries no audio. The decorative animation only follows play/pause and is "
                         "labelled DECO. The real spectrum analyses what the speakers play (labelled FFT)."))
        vis.add(w._combo("bmp_visualizer", _("Visualizer"), [
            ("off", _("Off")), ("decorative", _("Decorative animation")),
            ("spectrum", _("Real spectrum (records the output monitor)"))]))
        vis.add(w._combo("bmp_vis_style", _("Style"), [("bars", _("Bars")), ("led", _("LED segments")),
                                                       ("vu", _("VU meter")), ("scope", _("Line"))]))
        vis.add(w._scale("bmp_vis_sensitivity", _("Sensitivity (%)"), 50, 200, 10))
        page.add(vis)

        idle = w._group(_("Without playback"))
        idle.add(w._combo("bmp_idle_mode", _("Show"), [
            ("screen", _("Waiting screen with logo and clock")), ("last_art", _("Last track, dimmed")),
            ("clock", _("Big clock")), ("telemetry", _("Expanded telemetry")), ("rest", _("Rest (dark, small clock)")),
            ("theme", _("Another theme"))]))
        idle.add(w._scale("bmp_idle_after", _("After a pause of (s)"), 5, 3600, 5))
        idle.add(w._combo("bmp_idle_theme", _("Other theme"), [
            (tid, _(themes.REGISTRY[tid].name)) for tid in settings.SCHEMA["bmp_idle_theme"][1]],
            _("Returns to the player as soon as playback starts.")))
        idle.add(w._switch("bmp_idle_dim", _("Dim the display")))
        idle.add(w._switch("bmp_night", _("Night mode"), _("Darker display and optional night skin.")))
        idle.add(w._scale("bmp_night_start", _("Night starts at"), 0, 23, 1))
        idle.add(w._scale("bmp_night_end", _("Night ends at"), 0, 23, 1))
        idle.add(w._combo("bmp_night_skin", _("Night skin"), [("same", _("Same skin"))] +
                          [(sid, skins.SKINS[sid].name) for sid in skins.SKIN_IDS],
                          _("For example Big Pure by day and Big Lounge at night.")))
        idle.add(self._entry("bmp_app_skins", _("Skin per application"),
                             "spotify=big_flow, firefox=big_stage, vlc=big_ember, rhythmbox=big_vinyl"))
        page.add(idle)

        page.add(self._advanced_group())
        shortcuts = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        for accel, action, value in (("<Control>space", "play_pause", 0), ("<Control>Right", "next", 0),
                                     ("<Control>Left", "previous", 0), ("<Control>Up", "volume_up", 0),
                                     ("<Control>Down", "volume_down", 0), ("<Control>m", "mute", 0)):
            shortcuts.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string(accel),
                                                    Gtk.CallbackAction.new(lambda *_a, a=action, v=value:
                                                                           self.command(a, v) or True)))
        page.add_controller(shortcuts)
        return page

    def _entry(self, key, title, placeholder=""):
        row = Adw.EntryRow(title=title)
        row.set_text(self.window.values.get(key, "") or "")
        row.set_show_apply_button(True)
        if placeholder:
            row.set_tooltip_text(placeholder)
        row.connect("apply", lambda r: self.window._set(key, r.get_text().strip()))
        row.connect("changed", lambda r: self.window._set(key, r.get_text().strip())
                    if len(r.get_text()) <= settings.SCHEMA[key][1] else None)
        self.window._widgets[key] = (row, "entry")
        return row

    def _now_playing_group(self):
        group = self.window._group(_("Now playing"), _("Real controls for the player shown on the display "
                                                       "(the USB panels have no touch input). "
                                                       "Shortcuts: Ctrl+Space, Ctrl+←/→, Ctrl+↑/↓, Ctrl+M."))
        self.status_row = Adw.ActionRow(title=_("Looking for media players…"), subtitle="")
        self.status_row.set_title_lines(2)
        self.status_icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        self.status_row.add_prefix(self.status_icon)
        group.add(self.status_row)

        self.player_row = Adw.ComboRow(title=_("Player"), subtitle=_("Automatic follows the player in use"))
        self.player_row.set_model(Gtk.StringList.new([_("Automatic")]))
        self.player_row.connect("notify::selected", self._on_player_selected)
        group.add(self.player_row)

        transport = Adw.ActionRow(title=_("Playback"))
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.buttons = {}
        for action, icon, tip in (("previous", "media-skip-backward-symbolic", _("Previous")),
                                  ("play_pause", "media-playback-start-symbolic", _("Play/Pause")),
                                  ("stop", "media-playback-stop-symbolic", _("Stop")),
                                  ("next", "media-skip-forward-symbolic", _("Next")),
                                  ("shuffle", "media-playlist-shuffle-symbolic", _("Shuffle")),
                                  ("loop", "media-playlist-repeat-symbolic", _("Repeat"))):
            button = Gtk.Button(icon_name=icon, tooltip_text=tip, css_classes=["circular"])
            button.update_property([Gtk.AccessibleProperty.LABEL], [tip])
            button.connect("clicked", lambda _b, a=action: self.command(a))
            self.buttons[action] = button
            box.append(button)
        self.buttons["play_pause"].add_css_class("suggested-action")
        transport.add_suffix(box)
        group.add(transport)

        seek = Adw.ActionRow(title=_("Position"))
        self.time_label = Gtk.Label(label="--:-- / --:--", css_classes=["numeric", "dim-label"])
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.seek.set_hexpand(True)
        self.seek.set_size_request(240, -1)
        self.seek.set_draw_value(False)
        self.seek.update_property([Gtk.AccessibleProperty.LABEL], [_("Position")])
        self.seek.connect("change-value", self._on_seek)
        seek.add_suffix(self.seek)
        seek.add_suffix(self.time_label)
        group.add(seek)

        volume = Adw.ActionRow(title=_("System volume"), subtitle=_("Default output"))
        self.volume_row = volume
        vbox = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.mute_button = Gtk.ToggleButton(icon_name="audio-volume-muted-symbolic", tooltip_text=_("Mute"))
        self.mute_button.connect("toggled", self._on_mute)
        down = Gtk.Button(icon_name="list-remove-symbolic", tooltip_text=_("Volume down"))
        down.connect("clicked", lambda *_a: self.command("volume_down"))
        up = Gtk.Button(icon_name="list-add-symbolic", tooltip_text=_("Volume up"))
        up.connect("clicked", lambda *_a: self.command("volume_up"))
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume.set_size_request(200, -1)
        self.volume.set_value_pos(Gtk.PositionType.RIGHT)
        self.volume.update_property([Gtk.AccessibleProperty.LABEL], [_("System volume")])
        self.volume.connect("value-changed", self._on_volume)
        for widget in (self.mute_button, down, self.volume, up):
            vbox.append(widget)
        volume.add_suffix(vbox)
        group.add(volume)
        return group

    def _modern_group(self):
        w = self.window
        group = w._group(_("Modern Collection"), _("Options of the eight modern skins; the classic skins are not "
                                                   "affected."))
        group.add(w._combo("bmp_palette", _("Colours"), [
            ("skin", _("Original colours of the skin")), ("cover", _("Taken from the album art")),
            ("custom", _("Custom accent colour")), ("mono", _("Monochrome")), ("contrast", _("High contrast"))],
            _("Text contrast is always kept readable.")))
        accent = self._entry("bmp_accent_color", _("Accent colour (#RRGGBB)"), "#3584e4")
        try:
            button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
            rgba = Gdk.RGBA()
            if rgba.parse(self.window.values.get("bmp_accent_color") or "#3584e4"):
                button.set_rgba(rgba)

            def picked(btn, _pspec):
                c = btn.get_rgba()
                accent.set_text("#{:02x}{:02x}{:02x}".format(*(int(round(v * 255)) for v in (c.red, c.green, c.blue))))
            button.connect("notify::rgba", picked)
            accent.add_suffix(button)
        except (AttributeError, TypeError):
            pass                      # GTK < 4.10: the hexadecimal entry is enough
        group.add(accent)
        group.add(w._combo("bmp_pure_tone", _("Big Pure tone"), [
            ("white", _("White")), ("beige", _("Beige")), ("grey", _("Light grey")),
            ("graphite", _("Graphite (dark)"))]))
        group.add(w._combo("bmp_modern_radius", _("Rounded corners"), [
            ("skin", _("As the skin")), ("square", _("Square")), ("soft", _("Soft")), ("round", _("Round"))]))
        group.add(w._scale("bmp_modern_shadow", _("Shadows (%)"), 0, 100, 5))
        group.add(w._scale("bmp_modern_texture", _("Texture (%)"), 0, 100, 5,
                           _("Leather of Big Groove, grain of Big Ember and Big Vinyl.")))
        group.add(w._switch("bmp_glow", _("Light effects"), _("Amber glow, lit rims and play key halo.")))
        group.add(w._combo("bmp_modern_disc", _("Record behind the cover"), [
            ("skin", _("As the skin")), ("show", _("Always")), ("hide", _("Never"))]))
        group.add(w._switch("bmp_modern_spin", _("Turn the record while playing"),
                            _("Stops on pause; needs Balanced or Fluid animations.")))
        group.add(w._combo("bmp_modern_font", _("Typeface"), [
            ("skin", _("As the skin (falls back to an installed font)")), ("system", _("System sans-serif")),
            ("dejavu", _("DejaVu Sans (bundled)"))]))
        self.modern_anchor = group
        group.add(w._switch("bmp_track_banner", _("New track banner"),
                            _("Title and artist slide in over the cover for three seconds.")))
        return group

    def _gallery_group(self):
        group = self.window._group(_("Skins"), _("Seven classic homages and eight modern designs. Select one to see "
                                                 "it in the preview; Apply sends it to the display."))
        filters = Gtk.Box(css_classes=["linked"], halign=Gtk.Align.START, margin_bottom=6)
        self.filter_buttons = {}
        first_filter = None
        for key, label in (("all", _("All")), ("classic", _("Classic")), ("modern", _("Modern"))):
            button = Gtk.ToggleButton(label=label)
            if first_filter is None:
                first_filter = button
                button.set_active(True)
            else:
                button.set_group(first_filter)
            button.connect("toggled", self._on_filter, key)
            self.filter_buttons[key] = button
            filters.append(button)
        group.set_header_suffix(filters)
        first = None
        self.skin_checks = {}
        self.skin_rows = {}
        self.thumb_pictures = {}
        for skin_id in skins.SKIN_IDS:
            skin = skins.SKINS[skin_id]
            hint = SKIN_INSPIRATION.get(skin_id) or MODERN_INSPIRATION.get(skin_id, "")
            collection = _(COLLECTION_LABELS[skin.collection])
            row = Adw.ActionRow(title=GLib.markup_escape_text(skin.name),
                                subtitle=GLib.markup_escape_text(f"{_(skin.description)}\n{collection} · {_(hint)}"))
            row.set_subtitle_lines(3)
            self.skin_rows[skin_id] = row
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if first is None:
                first = check
            else:
                check.set_group(first)
            check.set_active(self.window.values.get("bmp_skin") == skin_id)
            check.connect("toggled", self._on_skin, skin_id)
            check.update_property([Gtk.AccessibleProperty.LABEL], [skin.name])
            row.add_prefix(check)
            row.set_activatable_widget(check)
            picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
            picture.set_size_request(*THUMB)
            picture.set_alternative_text(_("Preview of {theme}").format(theme=skin.name))
            row.add_suffix(picture)
            self.thumb_pictures[skin_id] = picture
            self.skin_checks[skin_id] = check
            group.add(row)
        self.fit_row = Adw.ActionRow(title=_("Display size"))
        group.add(self.fit_row)
        return group

    def _advanced_group(self):
        group = self.window._group(_("Diagnostics"), _("State of the media integration."))
        self.diag = {}
        for key, title in (("agent", _("Media agent (desktop session)")), ("service", _("Display service")),
                           ("dbus", _("MPRIS players")), ("audio", _("Audio system")),
                           ("art", _("Album art cache")), ("errors", _("Recent problems"))):
            row = Adw.ActionRow(title=title, subtitle="—")
            row.set_subtitle_lines(4)
            row.set_subtitle_selectable(True)
            self.diag[key] = row
            group.add(row)
        start = Gtk.Button(label=_("Start"), valign=Gtk.Align.CENTER)
        start.connect("clicked", lambda *_a: self.start_agent(force=True))
        self.diag["agent"].add_suffix(start)
        self.start_button = start
        clear = Gtk.Button(label=_("Clear"), valign=Gtk.Align.CENTER)
        clear.connect("clicked", lambda *_a: self._clear_cache())
        self.diag["art"].add_suffix(clear)
        reload_row = Adw.ActionRow(title=_("Reload media session"),
                                   subtitle=_("Looks for players again and retries album art."), activatable=True)
        reload_row.add_suffix(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        reload_row.connect("activated", lambda *_a: self._reload_session())
        group.add(reload_row)
        return group

    # ------------------------------------------------------------ callbacks
    def _on_filter(self, button, key):
        if not button.get_active():
            return
        for skin_id, row in self.skin_rows.items():
            row.set_visible(key == "all" or skins.SKINS[skin_id].collection == key)

    def _on_skin(self, check, skin_id):
        if check.get_active():
            self.window._set("bmp_skin", skin_id)

    def _on_player_selected(self, row, _pspec):
        if self._dropdown_lock:
            return
        index = row.get_selected()
        bus = self.players[index - 1]["bus"] if 0 < index <= len(self.players) else ""
        self.command("select", 0, bus)

    def _on_output_selected(self, row, _pspec):
        if self._dropdown_lock:
            return
        outputs = self.core.volume.outputs if self.core else []
        index = row.get_selected()
        self.window._set("bmp_volume_sink", outputs[index - 1][0] if 0 < index <= len(outputs) else "")

    def _on_seek(self, _scale, _scroll, value):
        player = self.player
        if not player or not player["can"]["seek"] or not player["length_us"]:
            return True
        self._seeking = time.monotonic()
        self.command("seek_to", max(0, value) * 1_000_000, player["bus"])
        return False

    def _on_volume(self, scale):
        if self._volume_lock:
            return
        self.command("volume_set", int(scale.get_value()))

    def _on_mute(self, button):
        if self._volume_lock:
            return
        self.command("mute")

    def _choose_logo(self):
        dialog = Gtk.FileDialog(title=_("Choose a logo"))
        dialog.open(self.window, None, self._logo_chosen)

    def _logo_chosen(self, dialog, result):
        try:
            path = dialog.open_finish(result).get_path()
        except GLib.Error:
            return
        from bsmd.kojiro import store
        from kojiro_page import _store_writable

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
            GLib.idle_add(self._logo_imported, image_id, error)
        threading.Thread(target=worker, daemon=True).start()

    def _logo_imported(self, image_id, error):
        if error or not image_id:
            self.window._error(_("The image could not be imported"), error or _("Unknown error"))
            return False
        self.window.values["bmp_logo_custom"] = image_id
        self.window.values["bmp_logo"] = "custom"
        self.window._reload_widgets()
        self.window.toast(_("Logo imported. Press Apply to use it on the display."))
        return False

    def _clear_cache(self):
        artwork.ArtCache().clear()
        self.command("retry_art")
        self.window.toast(_("Album art cache cleared."))

    def _reload_session(self):
        if self.core is not None:
            self.core.stop()
            self.core = None
        self.ensure_core()
        self.command("retry_art")
        self.window.toast(_("Media session reloaded."))

    def start_agent(self, force=False):
        """Launch the session agent (it exits by itself when the theme is unused)."""
        import os
        import subprocess
        import sys
        main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
        args = [sys.executable, main_py, "--media-agent"] + (["--keep"] if force else [])
        try:
            subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            self.window.toast(_("Could not start the media agent: {error}").format(error=error))

    # ------------------------------------------------------------ refresh
    def _tick(self):
        if self.active:
            self._probe_agent()
            self._refresh_now()
            self._refresh_diagnostics()
        return True

    def _probe_agent(self):
        if self.conn is None:
            return
        def done(conn, result):
            try:
                self.agent_info = __import__("json").loads(conn.call_finish(result).unpack()[0])
                self.agent_ok = True
            except (GLib.Error, ValueError):
                self.agent_ok, self.agent_info = False, {}
        self.conn.call(media_agent.BUS_NAME, media_agent.OBJECT_PATH, media_agent.INTERFACE, "GetState", None,
                       GLib.VariantType("(s)"), Gio.DBusCallFlags.NO_AUTO_START, 1500, None, done)

    def _refresh_now(self):
        if self.core is None:
            return False
        snapshot = model.clean_snapshot(self.core.snapshot())
        self.players = snapshot["players"]
        # The display follows the agent's choice; show the same one here.
        active = (self.agent_info.get("active") if self.agent_ok else None) or snapshot["active"]
        player = next((p for p in self.players if p["bus"] == active), None)
        self.player = player
        self._dropdown_lock = True
        labels = [_("Automatic")] + [f"{p['identity']} — {_(STATUS_LABELS.get(p['status'], p['status']))}"
                                     for p in self.players]
        model_ = self.player_row.get_model()
        if [model_.get_string(i) for i in range(model_.get_n_items())] != labels:
            self.player_row.set_model(Gtk.StringList.new(labels))
            manual = self.core.manual
            index = next((i + 1 for i, p in enumerate(self.players) if p["bus"] == manual), 0)
            self.player_row.set_selected(index)
        outputs = self.core.volume.outputs
        out_labels = [_("Default output")] + [description for _name, description in outputs]
        out_model = self.output_row.get_model()
        if [out_model.get_string(i) for i in range(out_model.get_n_items())] != out_labels:
            self.output_row.set_model(Gtk.StringList.new(out_labels))
            wanted = self.window.values.get("bmp_volume_sink", "")
            self.output_row.set_selected(next((i + 1 for i, (n, _d) in enumerate(outputs) if n == wanted), 0))
        self._dropdown_lock = False
        if player is None:
            self.status_row.set_title(_("No MPRIS media player found."))
            self.status_row.set_subtitle(_("Start playing in Spotify, VLC, Rhythmbox, a browser with media "
                                           "integration or any MPRIS compatible application."))
            self.status_icon.set_from_icon_name("dialog-information-symbolic")
        else:
            title = player["title"] or _("Unknown title")
            self.status_row.set_title(GLib.markup_escape_text(_short(title, 80)))
            details = [model.secondary_line(player)] if model.secondary_line(player) != player["identity"] else []
            if player["album"] and player["album"] not in details:
                details.append(player["album"])
            details.append(f"{player['identity']} · {_(STATUS_LABELS.get(player['status'], player['status']))}")
            self.status_row.set_subtitle(GLib.markup_escape_text(" — ".join(filter(None, details))))
            self.status_icon.set_from_icon_name({"Playing": "media-playback-start-symbolic",
                                                 "Paused": "media-playback-pause-symbolic"}.get(
                player["status"], "media-playback-stop-symbolic"))
        caps = player["can"] if player else {key: False for key in model.CAPS}
        playing = bool(player and player["status"] == "Playing")
        self.buttons["play_pause"].set_icon_name("media-playback-pause-symbolic" if playing else
                                                 "media-playback-start-symbolic")
        self.buttons["play_pause"].set_sensitive(caps["pause"] if playing else caps["play"])
        for action, cap in (("previous", "previous"), ("next", "next"), ("stop", "stop")):
            self.buttons[action].set_sensitive(caps[cap])
            if not caps[cap] and player:
                self.buttons[action].set_tooltip_text(_("Not available for this media"))
        self.buttons["shuffle"].set_sensitive(bool(player and player["shuffle"] is not None and caps["control"]))
        self.buttons["loop"].set_sensitive(bool(player and player["loop"] is not None and caps["control"]))
        if player and player["shuffle"]:
            self.buttons["shuffle"].add_css_class("accent")
        else:
            self.buttons["shuffle"].remove_css_class("accent")
        position = model.position_now(player) if player else None
        length = player["length_us"] if player else None
        hours = bool(length and length >= 3600 * 10 ** 6)
        if length:
            total = model.fmt_time(length, hours)
        else:
            total = _("LIVE") if player and model.is_live(player) else "--:--"
        self.time_label.set_label(f"{model.fmt_time(position, hours)} / {total}")
        self.seek.set_sensitive(bool(player and caps["seek"] and length))
        if length and (not self._seeking or time.monotonic() - self._seeking > 1.5):
            self.seek.set_range(0, length / 1_000_000)
            self.seek.set_value((position or 0) / 1_000_000)
        volume = snapshot["volume"]
        self._volume_lock = True
        self.volume.set_range(0, max(100, self.window.values.get("bmp_volume_max", 100), volume["percent"] or 0))
        if volume["available"]:
            self.volume.set_value(volume["percent"])
            self.mute_button.set_active(bool(volume["muted"]))
            self.volume_row.set_subtitle(volume["output"] or _("Default output"))
        else:
            self.volume_row.set_subtitle(_("The system volume could not be accessed.") +
                                         (f" ({volume['error']})" if volume["error"] else ""))
        self.volume.set_sensitive(volume["available"])
        self.mute_button.set_sensitive(volume["available"])
        self._volume_lock = False
        return False

    def _refresh_diagnostics(self):
        if self.agent_ok:
            sockets = self.agent_info.get("sockets") or []
            self.diag["agent"].set_subtitle(_("Running (pid {pid}); connected to: {sockets}").format(
                pid=self.agent_info.get("pid", "?"), sockets=", ".join(sockets) or _("no display service")))
            self.start_button.set_visible(False)
        else:
            self.diag["agent"].set_subtitle(_("Not running. It starts with the session when a display uses the "
                                              "Big Media Player theme."))
            self.start_button.set_visible(True)
        status = self.window.status or {}
        media = status.get("media")
        if media:
            text = _("Socket {path}: {state}; {count} message(s), {invalid} rejected")
            self.diag["service"].set_subtitle(text.format(
                path=media.get("socket"), state=_("receiving") if media.get("connected") else _("no agent data"),
                count=media.get("messages", 0), invalid=media.get("invalid", 0) + media.get("rejected", 0)))
        else:
            self.diag["service"].set_subtitle(_("The service has not started its media socket (theme not in use "
                                                "or service not running)."))
        players = self.players
        lines = []
        for p in players:
            status = _(STATUS_LABELS.get(p["status"], p["status"]))
            caps = ", ".join(k for k, v in p["can"].items() if v)
            lines.append(f"{p['identity']} ({p['bus'][len('org.mpris.MediaPlayer2.'):]}) — {status}; {caps}")
        self.diag["dbus"].set_subtitle("\n".join(lines) or _("No MPRIS player on the bus."))
        if self.core is not None:
            vol = self.core.volume.snapshot()
            backend = {"pulse": "PipeWire/PulseAudio (pactl)", "wpctl": "WirePlumber (wpctl)",
                       "alsa": "ALSA (amixer)"}.get(vol["backend"], _("none"))
            self.diag["audio"].set_subtitle(f"{backend}; {vol['output'] or '—'}" +
                                            (f"; {vol['error']}" if vol["error"] else ""))
            files, size = self.core.loader.cache.usage()
            self.diag["art"].set_subtitle(_("{files} image(s), {size:.1f} MB").format(files=files,
                                                                                     size=size / 1048576))
            errors = list(self.core.errors)[-5:] + list((self.agent_info.get("agent") or {}).get("errors") or [])[-3:]
            self.diag["errors"].set_subtitle("\n".join(errors[-6:]) or _("None"))
        size = self.window._device_size()
        from bsmd.bigmedia import layout
        compact = layout.is_micro(*size)
        self.fit_row.set_subtitle(_("{w}×{h}: every skin fits{note}").format(
            w=size[0], h=size[1], note=_(" (compact layout with alternating pages)") if compact else ""))

    # ------------------------------------------------------------ gallery thumbnails
    def _render_thumbs(self):
        size = self.window._device_size()
        values = dict(self.window.values, theme=THEME_ID)
        key = (size, tuple(sorted((k, str(v)) for k, v in values.items() if k.startswith("bmp_") and k != "bmp_skin")))
        if self._thumbs.get("key") == key:
            return
        self._thumbs["key"] = key

        def worker():
            for skin_id in skins.SKIN_IDS:
                ctx = runtime.RenderContext(preview=True)
                theme = themes.create(THEME_ID, ctx)
                try:
                    image = themes.render_for_panel(theme, size[0], size[1], dict(values, bmp_skin=skin_id), ctx)
                except Exception:  # noqa: BLE001 - a thumbnail must not break the window
                    continue
                image.thumbnail((THUMB[0] * 2, THUMB[1] * 2))
                data = GLib.Bytes.new(image.tobytes())
                texture = Gdk.MemoryTexture.new(image.width, image.height, Gdk.MemoryFormat.R8G8B8, data,
                                                image.width * 3)
                GLib.idle_add(self.thumb_pictures[skin_id].set_paintable, texture)
        threading.Thread(target=worker, name="bmp-thumbs", daemon=True).start()

    def sync_skin(self):
        for skin_id, check in self.skin_checks.items():
            check.set_active(self.window.values.get("bmp_skin") == skin_id)
