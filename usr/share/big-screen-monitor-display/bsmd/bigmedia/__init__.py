"""Big Media Player theme: retro media skins driven by real MPRIS sessions.

The theme never talks to D-Bus, the network or the audio server: it reads
the shared media snapshot (``ctx.media()``), which the service receives
from the user's session agent (see :mod:`bsmd.media`). Frames are composed
from a cached static chrome plus small dynamic layers, so an idle player
costs one clock update per second and a playing one only the pixels of the
progress bar, the time and (if enabled) the scrolling title and visualizer.

Without any data the theme shows its idle screen; in a preview without
players it shows clearly labelled demonstration data.
"""

import collections
import datetime
import math
import time

from PIL import Image, ImageDraw, ImageFilter

from .. import telemetry, themes
from ..i18n import _
from ..media import model, selection
from . import layout as layout_mod, paint as P, skins

THEME_ID = "big_media_player"
CHROME_CACHE = 6
MARQUEE_SPEED = {"slow": 18, "normal": 32, "fast": 56}     # px per second at 320 px
MARQUEE_PAUSE = 1.6
ANIMATION_FPS = 10.0
TRANSITION = 0.6
# bmp_animations: frame-rate cap while something moves (always bounded by the panel's own target fps).
# Idle themes that show a process list / the full sensor list (mirrors the
# runtime's own check on the session theme, which only sees "big_media_player").
IDLE_PROCESS_THEMES = ("standard", "gkrellm", "old_computer")
IDLE_SENSOR_THEMES = ("gkrellm",)
MOTION_FPS = {"economy": 4.0, "balanced": ANIMATION_FPS, "fluid": 20.0}
OSD_TIME = 2.2
BANNER_TIME = 3.0
PLAY_EASE = 0.45                 # s for the vinyl disc to slide out/in (modern skins)


class Frame:
    """Everything a skin needs to paint one frame (plain attributes)."""

    def __init__(self, theme, settings, now):
        self._theme = theme
        self.now = now
        self.accent = None
        self.logo = None
        self.logo_style = settings.get("bmp_logo_style", "logo_name")
        self.distro = ""
        self.art_shape = settings.get("bmp_art_shape", "skin")
        self.art_frame = settings.get("bmp_art_frame", "skin")
        self.art_glow = bool(settings.get("bmp_art_glow"))
        self.lcd_effect = bool(settings.get("bmp_lcd_effect", True))
        self.marquee = bool(settings.get("bmp_marquee", True))
        self.show = {key: bool(settings.get(f"bmp_show_{key}", True))
                     for key in ("title", "artist", "album", "description", "source")}
        self.show_vol_percent = bool(settings.get("bmp_volume_percent", True))
        self.tele_icons = bool(settings.get("bmp_tele_icons", True))
        self.tele_sep = settings.get("bmp_tele_separator", "bar")
        self.vis_style = settings.get("bmp_vis_style", "bars")
        self.compact_buttons = False
        self.status = "Stopped"
        self.title = self.artist = self.album = self.description = self.source = ""
        self.live = False
        self.fraction = None
        self.elapsed_text = self.total_text = "--:--"
        self.readout_text = "--:--"
        self.caps = {key: False for key in model.CAPS}
        self.shuffle = None
        self.loop = None
        self.vol_percent = None
        self.vol_muted = None
        self.vol_label = "VOL"
        self.vol_text = "--"
        self.vol_scale = 100
        self.bands = None
        self.vis_label = ""
        # Modern Collection (unused by the classic skins).
        self.pal = None
        self.pal_key = None
        self.style_key = None
        self.face = False
        self.base = 14.0
        self.app = ""
        self.output = ""
        self.remaining_text = ""
        self.art_image = None
        self.art_key = None
        self.play_t = 1.0
        self.disc_angle = 0
        self.radius_scale = 1.0
        self.shadow = 0.6
        self.texture = 0.5
        self.glow = True
        self.motion = "balanced"
        self.osd = None
        self.banner = None
        self.shape = None
        self.ambient = False

    def shape_at(self, t):
        """Envelope of the decorative waveform for this track (1.0 when unknown)."""
        if not self.shape:
            return 1.0
        pos = max(0.0, min(1.0, t)) * (len(self.shape) - 1)
        i = int(pos)
        j = min(len(self.shape) - 1, i + 1)
        return self.shape[i] + (self.shape[j] - self.shape[i]) * (pos - i)

    def logo_at(self, size):
        return self._theme.logo_image(size, self)

    def halo(self, img, box, radius, shape, color, blur, filled=True):
        self._theme.paste_halo(img, box, radius, shape, color, blur, filled)

    def scroll(self, text, size, width, bold, mono, pixel, loop):
        return self._theme.scroll_offset(text, size, width, bold, mono, pixel, loop, self.now)


class BigMediaPlayerTheme:
    def __init__(self, info, ctx=None):
        self.info = info
        self.ctx = ctx
        self.manager = selection.ActivePlayerManager()
        self._idle_target = None         # theme shown after inactivity (bmp_idle_mode "theme")
        self.chromes = collections.OrderedDict()
        self.art_tiles = collections.OrderedDict()
        self.halos = collections.OrderedDict()
        self.accents = {}
        self.blurred = collections.OrderedDict()
        self.marquees = {}
        self.animating = False
        self.last_player = None          # (bus, title, artist, art id) for the "last art" idle mode
        self.last_art = None
        self.inactive_since = None
        self.track_key = None
        self.track_changed = -1e9
        self.previous_tile = None
        self.tele_visible = "init"
        self.tele_changed = -1e9
        self.idle_theme = None
        self.idle_theme_id = None
        self.idle_entered = None
        self._demo_art = {}
        self._logo_cache = {}
        self.palettes = collections.OrderedDict()
        self.cover_palettes = collections.OrderedDict()
        self.shapes = collections.OrderedDict()
        self._play_t = None
        self._play_mono = None
        self._vol_seen = None
        self._vol_changed = -1e9

    def close(self):
        if self.idle_theme is not None:
            self.idle_theme.close()
            self.idle_theme = None

    @property
    def needs(self):
        """Optional telemetry for the collector. The player itself needs none, but
        the idle theme it hands the panel to may (the Standard theme's process list,
        GKrellM's sensors, Kojiro widgets). They are requested as soon as that idle
        mode is configured, so the data is ready when the panel switches over."""
        needs = {"processes": False, "sensors": False, "fans": False, "disks": set(), "addrs": False}
        target = self._idle_target
        if target in IDLE_PROCESS_THEMES:
            needs["processes"] = True
        if target in IDLE_SENSOR_THEMES:
            needs["sensors"] = True
        inner = getattr(self.idle_theme, "needs", None) if self.idle_theme is not None else None
        if isinstance(inner, dict):
            for key in ("processes", "sensors", "fans", "addrs"):
                needs[key] = needs[key] or bool(inner.get(key))
            needs["disks"] = set(inner.get("disks") or ())
        return needs

    # ------------------------------------------------------------ data
    def _media(self, ctx, settings):
        state = None
        getter = getattr(ctx, "media", None) if ctx is not None else None
        if getter is not None:
            try:
                state = getter()
            except Exception:  # noqa: BLE001 - media is optional, the panel is not
                state = None
        snapshot = state.snapshot if state is not None and state.connected else None
        demo = False
        if (snapshot is None or not snapshot["players"]) and getattr(ctx, "preview", False) and \
                settings.get("bmp_preview_demo", True):
            snapshot = model.demo_snapshot()
            demo = True
        return state, snapshot, demo

    def _choose(self, snapshot, settings, now):
        if not snapshot or not snapshot["players"]:
            return None
        self.manager.apply_settings(settings)
        if settings.get("bmp_player_mode") != "fixed" and snapshot.get("active"):
            player = next((p for p in snapshot["players"] if p["bus"] == snapshot["active"]), None)
            if player is not None and not any(model.matches(player, pattern) for pattern in self.manager.ignore):
                self.manager.current = player["bus"]
                return player
        return selection.pick(snapshot, self.manager, now)

    # ------------------------------------------------------------ main entry
    def render(self, width, height, settings, ctx):
        now = time.monotonic()
        wall = time.time()
        self._marquee_speed = settings.get("bmp_marquee_speed", "normal")
        state, snapshot, demo = self._media(ctx, settings)
        player = self._choose(snapshot, settings, now)
        has_media = player is not None and bool(player["title"] or player["status"] != "Stopped")
        if has_media and player["status"] == "Playing":
            self.inactive_since = None
        elif self.inactive_since is None:
            self.inactive_since = now
        inactive = 0.0 if self.inactive_since is None else now - self.inactive_since
        idle_after = settings.get("bmp_idle_after", 120)
        idle = not has_media or inactive >= idle_after
        mode = settings.get("bmp_idle_mode", "screen")
        target = settings.get("bmp_idle_theme", "standard") if mode == "theme" else None
        self._idle_target = target if target != THEME_ID else None
        if has_media:
            self.last_player = player
        self.animating = False

        if idle and mode == "theme":
            image = self._render_idle_theme(width, height, settings, ctx, has_media, now)
            if image is not None:
                return image
        else:
            self._drop_idle_theme()

        skin = skins.get(self._skin_id(settings, player, wall))
        night = self._night(settings, wall)
        if idle and mode in ("clock", "rest", "telemetry"):
            image = self._render_idle_full(width, height, skin, settings, mode, state, now, wall)
        else:
            show_last = idle and mode == "last_art" and self.last_player is not None
            shown = player if has_media and not (idle and mode == "screen") else (self.last_player if show_last
                                                                                   else None)
            image = self._render_player(width, height, skin, settings, state, snapshot, shown, demo, now, wall,
                                        idle=idle or shown is None)
        dim = 1.0
        if night:
            dim *= 0.55
        if idle and settings.get("bmp_idle_dim"):
            dim *= 0.45
        return P.darken(image, dim) if dim < 1 else image

    def frame_interval(self, settings, ctx):
        if self.idle_theme is not None:
            return self.idle_theme.frame_interval(settings, ctx)
        low_power = settings.get("bmp_layout") == "low_power" or settings.get("performance_profile") == "economy"
        motion = self.motion(settings)
        if self.animating and motion != "off":
            fps = min(MOTION_FPS[motion], getattr(ctx, "target_fps", 8.0) or 8.0)
            return 1.0 / max(1.0, fps)
        return themes.static_interval(settings, ctx, base=0.5 if not low_power else 1.0)

    @staticmethod
    def motion(settings):
        """Animation level: off | economy | balanced | fluid ("auto" keeps the 4.3 behaviour)."""
        value = settings.get("bmp_animations", "auto")
        if settings.get("bmp_layout") == "low_power":
            return "off"
        if value == "auto":
            return "off" if settings.get("performance_profile") == "economy" else "balanced"
        return value if value in MOTION_FPS or value == "off" else "balanced"

    # ------------------------------------------------------------ skin selection
    def _skin_id(self, settings, player, wall):
        skin_id = settings.get("bmp_skin", "bigamp")
        if player is not None:
            for pair in (settings.get("bmp_app_skins") or "").replace(";", ",").split(","):
                pattern, _sep, mapped = pair.partition("=")
                if mapped.strip() in skins.SKINS and model.matches(player, pattern):
                    skin_id = mapped.strip()
                    break
        if self._night(settings, wall) and settings.get("bmp_night_skin", "same") in skins.SKINS:
            skin_id = settings["bmp_night_skin"]
        return skin_id

    @staticmethod
    def _night(settings, wall):
        if not settings.get("bmp_night"):
            return False
        hour = datetime.datetime.fromtimestamp(wall).hour
        start, end = settings.get("bmp_night_start", 22), settings.get("bmp_night_end", 7)
        if start == end:
            return False
        return start <= hour < end if start < end else (hour >= start or hour < end)

    # ------------------------------------------------------------ the player
    def _variant(self, settings, width, height):
        value = settings.get("bmp_layout", "auto")
        if value in ("full", "compact", "party", "info"):
            return value
        if value == "low_power":
            return "full"
        return "compact" if min(width, height) < 200 else "full"

    def _tele_mode(self, settings, width, height):
        mode = settings.get("bmp_tele_mode", "auto")
        if mode == "auto":
            return "always" if height >= 240 and width >= 300 else "alternate"
        return mode

    def _render_player(self, width, height, skin, settings, state, snapshot, player, demo, now, wall, idle):
        variant = self._variant(settings, width, height)
        modern = getattr(skin, "modern", False)
        if variant == "cinema" and not modern:
            variant = "party"
        tele_mode = self._tele_mode(settings, width, height)
        if variant == "party" and tele_mode not in ("alerts", "hidden"):
            tele_mode = "alerts"
        tele_pos = settings.get("bmp_tele_position", "bottom") if tele_mode != "hidden" else None
        vis_on = settings.get("bmp_visualizer", "decorative") != "off" and not idle
        opts = {"title_bar": True, "tele": tele_pos, "vis": vis_on or variant == "party",
                "controls": settings.get("bmp_show_controls", True), "volume": settings.get("bmp_show_volume", True),
                "variant": variant, "text_size": settings.get("bmp_text_size"),
                "art_size": settings.get("bmp_art_size"), "disc": settings.get("bmp_modern_disc", "skin")}
        d = Frame(self, settings, now)
        self._fill_logo(d, settings)
        if modern:
            from .modern import base as modern_base
            text_scale = layout_mod.TEXT_SCALE.get(settings.get("bmp_text_size"), 1.0)
            opts["badge_w"] = modern_base.badge_width(d.logo_style, d.distro, 13 * text_scale * min(width, height)
                                                      / 300, width) if d.logo is not None else 0
        L = skin.compute_layout(width, height, opts) if modern else layout_mod.compute(width, height, skin, opts)
        self._fill_media(d, settings, state, snapshot, player, demo, now, idle)
        art_image, art_key = self._art_source(state, player, demo, skin, idle)
        if modern:
            self._prepare_modern(d, skin, settings, L, art_image, art_key, player, now)
        elif settings.get("bmp_adaptive_colors") and art_image is not None and art_key:
            d.accent = self._accent(art_key, art_image, skin)
        if self.motion(settings) == "off" and settings.get("bmp_animations") == "off":
            d.marquee = False
        d.compact_buttons = bool(L.buttons) and P.width(L.buttons) < P.height(L.buttons) * 5.2

        img = self._chrome(skin, L, d, settings).copy()
        if L.mode == "micro":
            return self._render_micro(img, L, skin, d, settings, art_image, art_key, now, wall, tele_mode, idle)
        skin.title_info(img, L, d)
        if modern:
            skin.before_art(img, L, d)
        if L.art and idle and not d.title:
            skin.art(img, P.ibox(L.art), self._logo_art(L.art, d, skin), d)
        elif L.art:
            self._draw_art(img, L.art, skin, d, art_image, art_key, settings, now, player)
        if settings.get("bmp_art_background") and art_image is not None and L.info and not idle and not modern:
            self._blur_background(img, L.extras.get("text") or L.info, art_key, art_image)
        if idle:
            self._idle_info(img, L, skin, d, state, wall)
        else:
            skin.info(img, L, d)
        if L.readout:
            d.readout_text = time.strftime("%H:%M", time.localtime(wall)) if idle else d.readout_text
            skin.readout(img, L.readout, d)
        if L.vis and not idle:
            self._fill_bands(d, settings, state, player, now)
            if d.bands:
                skin.vis(img, L.vis, d)
        if not idle:
            if L.times:
                (skin.times if skin.time_inline else skins.Skin.times.__get__(skin))(img, L.times, d)
            if L.progress:
                skin.progress(img, L.progress, d)
        if L.buttons:
            skin.buttons(img, L.buttons, d)
        if L.volume:
            skin.volume(img, L.volume, d)
        if modern:
            skin.extras(img, L, d)
        if L.tele:
            self._draw_tele(img, L, skin, d, settings, tele_mode, player, idle, now, wall)
        self._overlays(img, L, skin, d, settings, idle, now)
        self._mark_track(player, now)
        return img

    # ------------------------------------------------------------ modern collection
    def _prepare_modern(self, d, skin, settings, L, art_image, art_key, player, now):
        from .modern import base as modern_base
        mode = settings.get("bmp_palette", "skin")
        if mode == "skin" and settings.get("bmp_adaptive_colors"):
            mode = "cover"
        custom = modern_base.parse_hex(settings.get("bmp_accent_color")) if mode == "custom" else None
        cover = cover_key = None
        if mode == "cover" and art_image is not None and art_key:
            cover = self.cover_palettes.get(art_key)
            if cover is None:
                cover = self.cover_palettes[art_key] = modern_base.cover_colors(art_image)
                while len(self.cover_palettes) > 16:
                    self.cover_palettes.popitem(last=False)
            cover_key = art_key
        tone = settings.get("bmp_pure_tone", "white")
        key = (skin.id, mode, custom, cover_key, tone)
        pal = self.palettes.get(key)
        if pal is None:
            pal = self.palettes[key] = skin.palette(mode, custom, cover, tone)
            while len(self.palettes) > 16:
                self.palettes.popitem(last=False)
        d.pal, d.pal_key = pal, key
        d.radius_scale = modern_base.RADIUS_SCALE.get(settings.get("bmp_modern_radius", "skin"), 1.0)
        d.shadow = settings.get("bmp_modern_shadow", 60) / 100
        d.texture = settings.get("bmp_modern_texture", 50) / 100
        d.glow = bool(settings.get("bmp_glow", True))
        d.style_key = (d.radius_scale, d.shadow, d.texture, d.glow)
        face = settings.get("bmp_modern_font", "skin")
        d.face = skin.faces[0] if face == "skin" else modern_base.FACES.get(face, False)
        d.base = L.font
        d.art_image, d.art_key = art_image, art_key
        d.ambient = bool(art_image is not None and not pal.get("contrast")
                         and (skin.ambient or settings.get("bmp_art_background")))
        d.motion = motion = self.motion(settings)
        playing = player is not None and player["status"] == "Playing"
        # Disc slide (eased) and rotation: only while playing, only when motion allows it.
        target = 1.0 if playing else 0.0
        if self._play_t is None or motion == "off" or not settings.get("bmp_transitions", True):
            self._play_t = target
        else:
            step = (now - (self._play_mono or now)) / PLAY_EASE
            self._play_t = min(target, self._play_t + step) if target > self._play_t else \
                max(target, self._play_t - step)
            if self._play_t != target and L.extras.get("disc"):
                self.animating = True
        self._play_mono = now
        d.play_t = self._play_t
        if L.extras.get("disc") and playing and settings.get("bmp_modern_spin", True) and \
                motion in ("balanced", "fluid"):
            step = 6 if motion == "fluid" else 12
            d.disc_angle = int((now * 200) % 360) // step * step          # 33 1/3 rpm
            self.animating = True
        if L.vis and player is not None:
            seed = f"{player['bus']}|{player['title']}|{player['artist']}"
            shape = self.shapes.get(seed)
            if shape is None:
                shape = self.shapes[seed] = modern_base.track_shape(seed)
                while len(self.shapes) > 8:
                    self.shapes.popitem(last=False)
            d.shape = shape

    def _overlays(self, img, L, skin, d, settings, idle, now):
        """Temporary volume display and new-track banner."""
        modern = getattr(skin, "modern", False)
        state = (d.vol_percent, d.vol_muted)
        if self._vol_seen is None:
            self._vol_seen = state
        elif state != self._vol_seen:
            self._vol_seen = state
            self._vol_changed = now
        osd = settings.get("bmp_volume_osd", "modern")
        if (osd == "all" or (osd == "modern" and modern)) and now - self._vol_changed < OSD_TIME and \
                d.vol_percent is not None:
            d.osd = now - self._vol_changed
        if modern and settings.get("bmp_track_banner") and not idle and self.track_key is not None and \
                now - self.track_changed < BANNER_TIME:
            d.banner = (now - self.track_changed) if d.motion != "off" else 1.0
            if d.motion != "off":
                self.animating = True
        if modern:
            skin.overlay(img, L, d)
        elif d.osd is not None:
            from .modern import base as modern_base
            modern_base.draw_volume_osd(img, L, d, skin.pal)

    def _render_micro(self, img, L, skin, d, settings, art_image, art_key, now, wall, tele_mode, idle):
        """Tiny panels: art + one scrolling line + progress; telemetry alternates as a page."""
        page_tele = tele_mode != "hidden" and (idle or (tele_mode in ("alternate", "always", "intermittent")
                                                        and int(wall // 6) % 3 == 2))
        pal = d.pal or skin.pal
        face = d.face if getattr(skin, "modern", False) else skin.mono
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, L.W, L.H), fill=pal["lcd_bg"])
        if L.art:
            if idle:
                self._logo_tile(img, L.art, d, skin)
            else:
                self._draw_art(img, L.art, skin, d, art_image, art_key, settings, now, None, frame=False)
        x0, y0, x1, y1 = L.info
        size = L.font
        if page_tele:
            items = self._tele_items(settings, telemetry.snapshot(), wall)
            y = y0
            for _icon, label, value, alert in items[:max(1, int((L.H - y0) // (size * 1.25)))]:
                text = f"{label} {value}" if label else value
                P.put_text(img, (x0, y + size * 0.6), P.ellipsize(text, size, x1 - x0, mono=True), size,
                           (240, 90, 70) if alert else pal["lcd_fg"], mono=True)
                y += size * 1.25
            self.animating = False
            return img
        if idle:
            P.put_text(img, (x0, y0 + size * 0.7), time.strftime("%H:%M", time.localtime(wall)), size * 1.4,
                       pal["lcd_hi"], bold=True, mono=True)
            P.put_text(img, (x0, y0 + size * 2.1), P.ellipsize(_("No media"), size * 0.85, x1 - x0), size * 0.85,
                       pal["lcd_dim2"])
            return img
        line_h = size * 1.25
        title_box = (x0, y0, x1, y0 + line_h)
        bold = face is not True
        offset = self.scroll_offset(d.title, size, x1 - x0, bold, face, False, False, now) if d.marquee else 0
        if d.marquee:
            P.marquee(img, title_box, d.title or _("Unknown title"), size, d.accent or pal["lcd_hi"], offset,
                      bold=bold, mono=face)
        else:
            P.put_text(img, (x0, y0 + line_h / 2), P.ellipsize(d.title, size, x1 - x0, bold), size,
                       pal["lcd_hi"], bold=bold)
        second = d.artist or d.source
        if second and L.lines >= 2:
            P.put_text(img, (x0, y0 + line_h * 1.5), P.ellipsize(second, size * 0.9, x1 - x0), size * 0.9,
                       pal["lcd_fg"])
        if L.progress:
            px0, py0, px1, py1 = L.progress
            draw.rectangle(L.progress, fill=P.shade(pal["lcd_fg"], 0.25))
            if d.fraction is not None:
                draw.rectangle((px0, py0, px0 + (px1 - px0) * d.fraction, py1), fill=d.accent or pal["fill"])
        if L.times:
            tx0, ty0, tx1, ty1 = L.times
            ts = max(7, (ty1 - ty0) * 0.8)
            P.glyph(draw, {"Playing": "play", "Paused": "pause"}.get(d.status, "stop"),
                    (tx0, ty0 + (ty1 - ty0) * 0.2, tx0 + (ty1 - ty0) * 0.6, ty1 - (ty1 - ty0) * 0.2),
                    pal["lcd_fg"])
            P.put_text(img, (tx0 + (ty1 - ty0) * 0.8, (ty0 + ty1) / 2), d.elapsed_text, ts, pal["lcd_fg"],
                       mono=True)
            vol = ("M" if d.vol_muted else d.vol_text) if d.vol_percent is not None else ""
            P.put_text(img, (tx1, (ty0 + ty1) / 2), vol, ts, pal["lcd_dim2"], mono=True, anchor="rm")
        return img

    # ------------------------------------------------------------ data -> frame
    def _fill_media(self, d, settings, state, snapshot, player, demo, now, idle):
        volume = snapshot["volume"] if snapshot else (state.volume if state is not None else model.clean_volume({}))
        source = settings.get("bmp_volume_source", "system")
        if source == "player" and player is not None and player.get("volume") is not None:
            d.vol_percent = int(round(player["volume"] * 100))
            d.vol_muted = False
            d.vol_label = "APP"
            d.vol_scale = 100
        elif volume.get("available"):
            d.vol_percent = volume["percent"]
            d.vol_muted = volume["muted"]
            d.vol_label = "SYS" if source == "system" else "VOL"
            d.vol_scale = max(100, settings.get("bmp_volume_max", 100), volume["percent"] or 0)
        d.vol_text = f"{d.vol_percent}%" if d.vol_percent is not None else "--"
        if settings.get("bmp_show_output") and source == "system" and volume.get("output"):
            d.output = volume["output"]
        if player is None:
            return
        d.status = player["status"]
        d.title = player["title"] or ""
        d.artist = player["artist"]
        d.album = player["album"]
        d.description = player["description"]
        d.source = player["identity"] + (" · DEMO" if demo and player["identity"] != "DEMO" else "")
        d.app = d.source
        if settings.get("bmp_show_output") and volume.get("output") and source == "system":
            d.source = f"{d.source} → {volume['output']}" if d.source else volume["output"]
        d.caps = dict(player["can"]) if not demo else {key: True for key in model.CAPS}
        d.shuffle, d.loop = player["shuffle"], player["loop"]
        position = model.position_now(player, now)
        length = player["length_us"]
        d.live = model.is_live(player)
        if length and position is not None:
            d.fraction = max(0.0, min(1.0, position / length))
        hours = bool(length and length >= 3600 * 10 ** 6)
        d.elapsed_text = model.fmt_time(position, hours)
        if length is None:
            d.total_text = _("LIVE") if d.live else "--:--"
        elif settings.get("bmp_time_mode") == "remaining" and position is not None:
            d.total_text = "-" + model.fmt_time(length - position, hours)
        else:
            d.total_text = model.fmt_time(length, hours)
        if length is not None and position is not None:
            d.remaining_text = "-" + model.fmt_time(max(0, length - position), hours)
        if settings.get("bmp_show_percent") and d.fraction is not None:
            d.total_text = f"{d.total_text} {int(d.fraction * 100)}%"
        if settings.get("bmp_time_mode") == "remaining" and length and position is not None:
            d.readout_text = "-" + model.fmt_time(length - position)
        else:
            d.readout_text = model.fmt_time(position) if position is not None else "--:--"
        if d.readout_text.count(":") > 1:       # h:mm:ss does not fit the 5-digit readout
            d.readout_text = d.readout_text.rsplit(":", 1)[0]

    def _fill_logo(self, d, settings):
        mode = settings.get("bmp_logo", "auto")
        if mode == "none":
            d.logo_style = "none"
            return
        from ..kojiro import assets
        info = assets.distro_info()
        # "BigCommunity, based in BigLinux" -> "BigCommunity": the title bar is narrow. In a
        # desktop with its own identity (Big WindowMaker), its name instead.
        d.distro = info["name"].split(",")[0].split(" based ")[0].strip()[:24]
        d.logo = True       # resolved lazily by logo_image(size)
        self._logo_mode = (mode, settings.get("bmp_logo_custom", ""), distro_logo_path())

    def logo_image(self, size, d=None):
        mode, custom, path = getattr(self, "_logo_mode", ("auto", "", None))
        key = (mode, custom, path, size)
        if key in self._logo_cache:
            return self._logo_cache[key]
        from ..kojiro import assets
        image = None
        if mode == "custom" and custom:
            from ..kojiro import store
            custom_path = store.wallpaper_path(custom)
            if custom_path:
                try:
                    with Image.open(custom_path) as source:
                        image = source.convert("RGBA")
                    image.thumbnail((size, size), Image.Resampling.LANCZOS)
                except (OSError, ValueError):
                    image = None
        if image is None:
            image = assets.load_logo(path, size) if path else None
        if image is None:
            image = assets.fallback_logo(size, (200, 210, 230))
        if len(self._logo_cache) > 24:
            self._logo_cache.clear()
        self._logo_cache[key] = image
        return image

    # ------------------------------------------------------------ chrome cache
    def _chrome(self, skin, L, d, settings):
        key = (skin.id, L.key(), d.logo_style, d.distro, d.lcd_effect, getattr(self, "_logo_mode", None),
               skin.chrome_key(d) if getattr(skin, "modern", False) else None)
        image = self.chromes.get(key)
        if image is None:
            image = Image.new("RGB", (L.W, L.H), skin.pal["body"])
            skin.chrome(image, L, d)
            self.chromes[key] = image
            while len(self.chromes) > CHROME_CACHE:
                self.chromes.popitem(last=False)
        else:
            self.chromes.move_to_end(key)
        return image

    # ------------------------------------------------------------ art
    def _art_source(self, state, player, demo, skin, idle):
        if player is None:
            return None, None
        if demo:
            return self._demo_image(), "demo"
        art_id = player.get("art")
        image = state.art(art_id) if (state is not None and art_id) else None
        if image is None:
            return None, None
        return image, art_id

    def _demo_image(self):
        image = self._demo_art.get("demo")
        if image is None:
            image = demo_art(480)
            self._demo_art["demo"] = image
        return image

    def _draw_art(self, img, box, skin, d, image, key, settings, now, player, frame=True):
        box = P.ibox(box)
        radius, shape = skin.art_radius(box, d)
        vinyl = settings.get("bmp_vinyl") and image is not None and d.status == "Playing"
        if vinyl:
            shape, radius = "circle", min(P.width(box), P.height(box)) // 2
        angle = 0
        if vinyl:
            angle = int((now * 40) % 360) // 3 * 3          # 33⅓ rpm feel, 3° steps
            self.animating = True
        tile = self._art_tile(box, image, key, shape, radius, skin, angle, vinyl, getattr(skin, "art_fit", "auto"))
        # Short crossfade from the previous cover after a track change.
        if settings.get("bmp_transitions", True) and self.motion(settings) != "off" and \
                self.previous_tile is not None and \
                now - self.track_changed < TRANSITION and self.previous_tile[0].size == tile[0].size:
            t = (now - self.track_changed) / TRANSITION
            tile = (Image.blend(self.previous_tile[0], tile[0], t), tile[1])
            self.animating = True
        self._current_tile = tile
        if frame:
            skin.art(img, box, tile, d)
        else:
            img.paste(tile[0], box[:2], tile[1])

    def _art_tile(self, box, image, key, shape, radius, skin, angle, vinyl, fit="auto"):
        w, h = P.width(box), P.height(box)
        cache_key = (key, w, h, shape, radius, skin.id if image is None else "", angle, fit)
        hit = self.art_tiles.get(cache_key)
        if hit is not None:
            self.art_tiles.move_to_end(cache_key)
            return hit
        if image is None:
            source = placeholder_art(min(w, h), skin.pal)
        elif fit != "cover" and abs(image.width / image.height - 1) > 0.15:
            source = P.contain_fit(image, (w, h), (0, 0, 0))      # video thumbnail: keep it whole
        else:
            source = P.cover_fit(image, (w, h))
        if source.size != (w, h):
            source = P.cover_fit(source, (w, h))
        mask = None
        if vinyl:
            source = _vinyl(source, angle)
            if source.size != (w, h):
                # Non-square art box: centre the round record instead of stretching its mask.
                side = min(w, h)
                canvas = Image.new("RGB", (w, h), (0, 0, 0))
                canvas.paste(source, ((w - side) // 2, (h - side) // 2))
                mask = Image.new("L", (w, h), 0)
                mask.paste(P.circle_mask(side), ((w - side) // 2, (h - side) // 2))
                source = canvas
        if mask is None and shape == "circle":
            mask = P.circle_mask(min(w, h)).resize((w, h))
        elif mask is None and radius:
            mask = P.rounded_mask((w, h), radius)
        tile = (source, mask)
        self.art_tiles[cache_key] = tile
        while len(self.art_tiles) > (40 if vinyl else 12):
            self.art_tiles.popitem(last=False)
        return tile

    def _logo_tile(self, img, box, d, skin):
        w, h = P.width(box), P.height(box)
        ImageDraw.Draw(img).rectangle(box, fill=skin.pal["lcd_bg"])
        if d.logo_style == "none":
            return
        logo = self.logo_image(int(min(w, h) * 0.7), d)
        if logo is not None:
            img.paste(logo, (int(box[0] + (w - logo.width) / 2), int(box[1] + (h - logo.height) / 2)), logo)

    def _logo_art(self, box, d, skin):
        """Art tile for the idle screen: the distribution logo on the skin's display colour."""
        box = P.ibox(box)
        w, h = P.width(box), P.height(box)
        key = ("logo", w, h, skin.id, d.logo_style, getattr(self, "_logo_mode", None))
        hit = self.art_tiles.get(key)
        if hit is None:
            tile = Image.new("RGB", (w, h), skin.pal["lcd_bg"])
            self._logo_tile(tile, (0, 0, w, h), d, skin)
            radius, shape = skin.art_radius(box, d)
            mask = P.circle_mask(min(w, h)).resize((w, h)) if shape == "circle" else (
                P.rounded_mask((w, h), radius) if radius else None)
            hit = self.art_tiles[key] = (tile, mask)
        return hit

    def _mark_track(self, player, now):
        key = (player["bus"], player["track_id"], player["title"]) if player else None
        if key != self.track_key:
            if self.track_key is not None:
                self.previous_tile = getattr(self, "_current_tile", None)
                self.track_changed = now
            self.track_key = key

    def _accent(self, key, image, skin):
        if key not in self.accents:
            color = P.dominant_color(image)
            self.accents[key] = None if color is None else P.ensure_contrast(color, skin.pal["lcd_bg"], 3.0)
            if len(self.accents) > 32:
                self.accents.clear()
        return self.accents[key]

    def _blur_background(self, img, box, key, image):
        box = P.ibox(box)
        cache_key = (key, box)
        tile = self.blurred.get(cache_key)
        if tile is None:
            tile = P.cover_fit(image, (P.width(box), P.height(box))).filter(ImageFilter.GaussianBlur(
                max(4, P.height(box) // 10)))
            tile = P.darken(tile, 0.38)
            self.blurred[cache_key] = tile
            while len(self.blurred) > 4:
                self.blurred.popitem(last=False)
        img.paste(tile, box[:2])

    def paste_halo(self, img, box, radius, shape, color, blur, filled=True):
        box = P.ibox(box)
        margin = blur * 3
        key = (box[2] - box[0], box[3] - box[1], radius, shape, tuple(color), blur, filled)
        tile = self.halos.get(key)
        if tile is None:
            w, h = box[2] - box[0] + margin * 2, box[3] - box[1] + margin * 2
            mask = Image.new("L", (w, h), 0)
            draw = ImageDraw.Draw(mask)
            inner = (margin, margin, w - margin - 1, h - margin - 1)
            if shape == "circle":
                draw.ellipse(inner, fill=210 if filled else None, outline=255, width=3)
            else:
                draw.rounded_rectangle(inner, radius=max(0, radius), fill=210 if filled else None, outline=255,
                                       width=3)
            mask = mask.filter(ImageFilter.GaussianBlur(blur))
            tile = (Image.new("RGB", (w, h), color[:3]), mask)
            self.halos[key] = tile
            while len(self.halos) > 8:
                self.halos.popitem(last=False)
        img.paste(tile[0], (box[0] - margin, box[1] - margin), tile[1])

    # ------------------------------------------------------------ text scrolling
    def scroll_offset(self, text, size, width, bold, mono, pixel, loop, now):
        key = (text, int(size), int(width), loop)
        start = self.marquees.get(key)
        if start is None:
            if len(self.marquees) > 32:
                self.marquees.clear()
            self.marquees[key] = start = now
        text_w = P.text_width(text + ("   ***   " if loop else ""), size, bold, mono, pixel) if loop else \
            P.text_width(text, size, bold, mono, pixel)
        if (not loop and text_w <= width) or (loop and P.text_width(text, size, bold, mono, pixel) <= width):
            return 0
        self.animating = True
        speed = MARQUEE_SPEED.get(self._marquee_speed, 32) * max(0.6, size / 14)
        elapsed = now - start
        if loop:
            return max(0.0, elapsed - MARQUEE_PAUSE) * speed
        travel = text_w - width
        cycle = MARQUEE_PAUSE * 2 + travel / speed
        phase = elapsed % cycle
        if phase < MARQUEE_PAUSE:
            return 0
        if phase > MARQUEE_PAUSE + travel / speed:
            return travel
        return (phase - MARQUEE_PAUSE) * speed

    _marquee_speed = "normal"

    # ------------------------------------------------------------ visualizer
    def _fill_bands(self, d, settings, state, player, now):
        mode = settings.get("bmp_visualizer", "decorative")
        playing = player is not None and player["status"] == "Playing"
        bands = state.spectrum_bands(now) if (state is not None and mode == "spectrum") else None
        if bands:
            d.bands, d.vis_label = bands, "FFT"
            self.animating = True
            return
        # Decorative animation: driven only by the playback state, labelled as such.
        d.vis_label = "DECO" if mode == "decorative" else _("NO SIGNAL")
        count = 20
        if not playing or mode != "decorative":
            d.bands = [0.04] * count
            return
        self.animating = True
        d.bands = decorative_bands(count, now)

    # ------------------------------------------------------------ telemetry
    def _tele_visible(self, mode, settings, player, idle, now, wall):
        """('tele' | 'media' | None) for the strip, per display mode."""
        playing = player is not None and player["status"] == "Playing"
        if mode == "hidden":
            return None
        if mode == "always":
            return "tele"
        if mode == "intermittent":
            every, duration = settings.get("bmp_tele_every", 30), settings.get("bmp_tele_duration", 8)
            return "tele" if (wall % every) < duration else "media"
        if mode == "alternate":
            every = max(4, settings.get("bmp_tele_duration", 8))
            return "tele" if int(wall // every) % 2 else "media"
        if mode == "paused":
            return "media" if playing else "tele"
        if mode == "idle":
            changed = now - self.track_changed if self.track_key else 1e9
            return "tele" if idle or changed >= settings.get("bmp_tele_idle_after", 60) else "media"
        if mode == "alerts":
            return "tele" if self._alerts(settings, telemetry.snapshot()) else "media"
        return "tele"

    @staticmethod
    def _alerts(settings, stats):
        cpu = stats.get("cpu_percent")
        temp = stats.get("cpu_temp_value")
        gpus = stats.get("gpus") or []
        gpu_temp = next((g.get("temp_value") for g in gpus if g.get("temp_value") is not None), None)
        limit_t = settings.get("bmp_tele_alert_temp", 85)
        return bool((cpu is not None and cpu >= settings.get("bmp_tele_alert_cpu", 90))
                    or (temp is not None and temp >= limit_t) or (gpu_temp is not None and gpu_temp >= limit_t))

    def _tele_items(self, settings, stats, wall):
        items = []
        limit_t = settings.get("bmp_tele_alert_temp", 85)
        icon = _icon
        if settings.get("bmp_tele_clock", True):
            items.append((None, "", time.strftime("%H:%M", time.localtime(wall)), False))
        if not stats.get("valid"):
            return items
        if settings.get("bmp_tele_cpu", True) and stats.get("cpu_percent") is not None:
            cpu = stats["cpu_percent"]
            value = f"{cpu:.0f}%"
            temp = stats.get("cpu_temp_value")
            if settings.get("bmp_tele_cpu_temp", True) and temp is not None:
                value += f" {temp:.0f}°C"
            items.append((icon("cpu"), "CPU", value, cpu >= settings.get("bmp_tele_alert_cpu", 90)
                          or (temp is not None and temp >= limit_t)))
        if settings.get("bmp_tele_ram", True) and stats.get("ram_used_mb") is not None:
            items.append((icon("ram"), "RAM", f"{stats['ram_used_mb'] / 1024:.1f} GB", False))
        if settings.get("bmp_tele_swap", True) and stats.get("swap_total_mb"):
            items.append((icon("swap"), "SWAP", f"{stats.get('swap_percent', 0):.0f}%", False))
        if settings.get("bmp_tele_disk", True) and stats.get("disk_percent") is not None:
            items.append((icon("disk"), "DISK", f"{stats['disk_percent']:.0f}%", False))
        gpus = [g for g in stats.get("gpus") or [] if g.get("path")]
        if settings.get("bmp_tele_gpu", True) and gpus:
            gpu = gpus[stats.get("active_gpu_idx", 0) % len(gpus)]
            value = f"{gpu.get('percent', 0):.0f}%"
            temp = gpu.get("temp_value")
            if settings.get("bmp_tele_gpu_temp", True) and temp is not None:
                value += f" {temp:.0f}°C"
            items.append((icon("gpu"), "GPU", value, temp is not None and temp >= limit_t))
        return items

    def _media_items(self, d, player):
        items = []
        if player is not None:
            state = {"Playing": _("Playing"), "Paused": _("Paused")}.get(player["status"], _("Stopped"))
            items.append((None, "", state, False))
            if d.album:
                items.append((None, "", d.album, False))
        if d.vol_percent is not None:
            items.append((None, _("Vol"), _("muted") if d.vol_muted else d.vol_text, bool(d.vol_muted)))
        return items

    def _draw_tele(self, img, L, skin, d, settings, mode, player, idle, now, wall):
        content = self._tele_visible(mode, settings, player, idle, now, wall)
        if content != self.tele_visible:
            if self.tele_visible != "init":
                self.tele_changed = now
            self.tele_visible = content
        if content is None:
            return
        items = self._tele_items(settings, telemetry.snapshot(), wall) if content == "tele" else \
            self._media_items(d, player)
        slide = 0.0
        if settings.get("bmp_tele_animate", True) and now - self.tele_changed < 0.35:
            slide = (1 - (now - self.tele_changed) / 0.35) * P.width(L.tele) * 0.15
            self.animating = True
        if L.tele_overlay and content != "tele":
            return            # the overlay only appears for telemetry, never over the art without reason
        skin.tele(img, L.tele, d, items, overlay=L.tele_overlay, opacity=settings.get("bmp_tele_opacity", 85) / 100,
                  slide=slide)

    # ------------------------------------------------------------ idle
    def _idle_info(self, img, L, skin, d, state, wall):
        box = L.extras.get("text") or L.info
        if not box:
            return
        pal = d.pal or skin.pal
        face = d.face if getattr(skin, "modern", False) else skin.mono
        x0, y0, x1, y1 = P.inset(box, max(3, L.font * 0.4), 2)
        if d.title:          # "last art" mode: last track, dimmed
            lines = [(d.title, pal["lcd_dim2"], 1.05, True), (d.artist or d.source, pal["lcd_dim2"], 0.9,
                                                                   False), (_("Paused") if d.status == "Paused" else
                                                                            _("Stopped"), pal["lcd_fg"], 0.9,
                                                                            False)]
        else:
            if state is None or not state.connected:
                hint = _("Media agent not running")
            elif not state.players:
                hint = _("No MPRIS player found")
            else:
                hint = _("Waiting for playback")
            lines = [(_("No media playing"), pal["lcd_hi"], 1.15, True), (hint, pal["lcd_dim2"], 0.85, False)]
            if not L.readout:
                lines.insert(0, (time.strftime("%H:%M", time.localtime(wall)), pal["lcd_fg"], 1.6, True))
        total = sum(L.font * f * 1.3 for _t, _c, f, _b in lines)
        y = y0 + max(0, ((y1 - y0) - total) / 2)
        for text, color, factor, bold in lines:
            size = L.font * factor
            if L.mode == "portrait":
                P.put_text(img, ((x0 + x1) / 2, y + size * 0.65), P.ellipsize(text, size, x1 - x0, bold, face),
                           size, color, bold=bold, mono=face, anchor="mm")
            else:
                P.put_text(img, (x0, y + size * 0.65), P.ellipsize(text, size, x1 - x0, bold, face), size, color,
                           bold=bold, mono=face)
            y += size * 1.3

    def _render_idle_full(self, width, height, skin, settings, mode, state, now, wall):
        img = Image.new("RGB", (width, height), (0, 0, 0))
        if mode == "rest":
            # Burn-in friendly: tiny dim clock that moves every minute.
            size = max(10, min(width, height) // 9)
            minute = int(wall // 60)
            x = (minute * 37) % max(1, width - size * 3) + size * 1.5
            y = (minute * 23) % max(1, height - size * 2) + size
            P.put_text(img, (x, y), time.strftime("%H:%M", time.localtime(wall)), size, (70, 70, 80), mono=True,
                       anchor="mm")
            return img
        d = Frame(self, settings, now)
        self._fill_logo(d, settings)
        if getattr(skin, "modern", False):
            d.pal, d.pal_key, d.style_key, d.face = skin.pal, ("static", skin.id), (), skin.faces[0]
        L = layout_mod.Layout(width, height, "full", min(width, height) / 320, 14)
        L.title = (0, 0, width, max(12, round(skin.title_h * L.unit)))
        L.info = None
        L.art = None
        img = self._chrome(skin, L, d, settings).copy()
        pad = max(6, int(L.unit * 10))
        well = (pad, L.title[3] + pad, width - pad, height - pad)
        P.lcd_well(img, well, skin.pal["lcd_bg"])
        x0, y0, x1, y1 = well
        if mode == "clock":
            text = time.strftime("%H:%M", time.localtime(wall))
            size = min((y1 - y0) * 0.5, (x1 - x0) / 3.6)
            P.seven_seg(img, ((x0 + x1) / 2, (y0 + y1) / 2 - size * 0.15), text, size, skin.pal["lcd_hi"],
                        anchor="mm", bg=skin.pal["lcd_bg"])
            date = time.strftime("%A, %d %B %Y", time.localtime(wall))
            P.put_text(img, ((x0 + x1) / 2, y1 - size * 0.32), date, max(9, size * 0.16), skin.pal["lcd_dim2"],
                       anchor="mm", mono=skin.mono)
            return img
        # Expanded telemetry: one row per metric with a bar.
        stats = telemetry.snapshot()
        items = self._tele_items(settings, stats, wall)
        rows = max(1, len(items))
        row_h = min((y1 - y0 - pad) / rows, max(16, height / 7))
        size = row_h * 0.5
        y = y0 + pad / 2
        values = {"CPU": stats.get("cpu_percent"), "RAM": stats.get("ram_percent"), "SWAP": stats.get("swap_percent"),
                  "DISK": stats.get("disk_percent")}
        gpus = [g for g in stats.get("gpus") or [] if g.get("path")]
        if gpus:
            values["GPU"] = gpus[0].get("percent")
        draw = ImageDraw.Draw(img)
        for _unused, label, value, alert in items:
            color = (240, 90, 70) if alert else skin.pal["lcd_fg"]
            P.put_text(img, (x0 + pad, y + row_h / 2), label or _("Time"), size, skin.pal["lcd_dim2"], bold=True,
                       mono=skin.mono)
            P.put_text(img, (x1 - pad, y + row_h / 2), value, size, color, mono=True, anchor="rm")
            fraction = values.get(label)
            if fraction is not None:
                bx0, bx1 = x0 + pad + size * 3.6, x1 - pad - size * 6.2
                if bx1 > bx0 + 10:
                    draw.rectangle((bx0, y + row_h * 0.35, bx1, y + row_h * 0.65),
                                   fill=P.shade(skin.pal["lcd_fg"], 0.2))
                    draw.rectangle((bx0, y + row_h * 0.35, bx0 + (bx1 - bx0) * min(1, fraction / 100),
                                    y + row_h * 0.65), fill=color)
            y += row_h
        return img

    def _render_idle_theme(self, width, height, settings, ctx, has_media, now):
        """Hand the panel to another theme after inactivity; come back when playback starts."""
        target = settings.get("bmp_idle_theme", "standard")
        if target == THEME_ID:
            return None
        if self.idle_theme is None or self.idle_theme_id != target:
            self._drop_idle_theme()
            self.idle_theme = themes.create(target, ctx)
            self.idle_theme_id = target
        return themes.render_for_panel(self.idle_theme, width, height, dict(settings, theme=target), ctx)

    def _drop_idle_theme(self):
        if self.idle_theme is not None:
            self.idle_theme.close()
            self.idle_theme = None
            self.idle_theme_id = None


# ---------------------------------------------------------------- helpers

_LOGO_PATH = []


def logo_candidates(info):
    """Icon names to try, most specific first: LOGO, ID, distributor-logo-ID, names
    mentioned in NAME ("BigCommunity, based in BigLinux" -> biglinux), ID_LIKE."""
    import re
    names = [info.get("LOGO", ""), info.get("ID", ""), f"distributor-logo-{info.get('ID', '')}"]
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]+", info.get("NAME", "")):
        if word.lower() not in ("based", "in", "on", "linux", "gnu", "edition"):
            names += [word.lower(), f"distributor-logo-{word.lower()}"]
    for like in info.get("ID_LIKE", "").split():
        names += [f"distributor-logo-{like}", f"{like}linux-logo", like]
    names.append("distributor-logo")
    seen = []
    for name in names:
        if name and name not in seen and "/" not in name:
            seen.append(name)
    return seen


def find_icon(name, roots=("/usr/share/icons",)):
    import glob
    from ..kojiro import assets
    path = assets.logo_path(name)
    if path:
        return path
    for root in roots:
        found = sorted(glob.glob(f"{root}/*/scalable/*/{name}.svg") + glob.glob(f"{root}/*/*/apps/{name}.svg")
                       + glob.glob(f"{root}/*/*/apps/{name}.png"))
        if found:
            return found[0]
    return None


def distro_logo_path():
    """Logo of the system (the desktop's own identity, else the distribution), or None.

    Searched once per identity: a login into another desktop changes it."""
    import os
    from ..kojiro import assets
    info = assets.identity()
    key = (info.get("LOGO", ""), info.get("LOGO_FILE", ""), info.get("ID", ""), info.get("NAME", ""))
    if not _LOGO_PATH or _LOGO_PATH[0][0] != key:
        logo_file = info.get("LOGO_FILE", "")
        path = None
        if logo_file:
            # A desktop identity: its icon from the theme, else its own file.
            path = find_icon(info.get("LOGO", "")) or (logo_file if os.path.isfile(logo_file) else None)
        if path is None:
            path = next((p for p in (find_icon(n) for n in logo_candidates(info)) if p), None)
        _LOGO_PATH[:] = [(key, path)]
    return _LOGO_PATH[0][1]


def _icon(name):
    def make(size, color):
        from ..kojiro import draw as kdraw
        try:
            return kdraw.icon(name, size, color)
        except Exception:  # noqa: BLE001 - icons are decoration
            return None
    return make


def decorative_bands(count, now):
    """Smooth, clearly synthetic motion (sum of slow sines), only while playing."""
    bands = []
    for i in range(count):
        base = 0.55 - 0.35 * (i / count)
        wobble = 0.22 * math.sin(now * (2.1 + i * 0.37) + i * 1.7) + 0.14 * math.sin(now * (5.3 + i * 0.11) + i)
        bands.append(max(0.04, min(1.0, base + wobble)))
    return bands


def placeholder_art(side, pal):
    """Original stand-in cover: a stylised record with a note, in the skin's colours."""
    side = max(8, int(side))
    img = Image.new("RGB", (side, side), pal["lcd_bg"])
    P.vgrad(img, (0, 0, side, side), P.shade(pal["lcd_bg"], 1.25), pal["lcd_bg"])
    draw = ImageDraw.Draw(img)
    c = side / 2
    r = side * 0.38
    draw.ellipse((c - r, c - r, c + r, c + r), fill=P.shade(pal["lcd_bg"], 0.6), outline=pal["lcd_dim2"])
    for k in (0.75, 0.55):
        draw.ellipse((c - r * k, c - r * k, c + r * k, c + r * k), outline=P.mix(pal["lcd_bg"], pal["lcd_dim2"], 0.45))
    draw.ellipse((c - r * 0.28, c - r * 0.28, c + r * 0.28, c + r * 0.28), fill=pal["accent"])
    draw.ellipse((c - r * 0.05, c - r * 0.05, c + r * 0.05, c + r * 0.05), fill=pal["lcd_bg"])
    return img


def demo_art(side):
    """Original demonstration cover (synthwave sun over a grid), generated, no external asset."""
    img = Image.new("RGB", (side, side))
    P.vgrad(img, (0, 0, side, side), None, None, [(0, (20, 8, 48)), (0.55, (120, 30, 110)), (0.56, (12, 4, 30)),
                                                   (1, (30, 10, 60))])
    draw = ImageDraw.Draw(img)
    c = side / 2
    r = side * 0.27
    for k in range(int(r * 2)):
        y = c * 0.9 - r + k
        if y > side * 0.55:
            break
        half = math.sqrt(max(0, r * r - (k - r) ** 2))
        if k > r and int(k / max(1, side / 40)) % 2:
            continue
        draw.line((c - half, y, c + half, y), fill=P.mix((255, 220, 80), (255, 60, 140), k / (r * 2)))
    horizon = side * 0.56
    for i in range(1, 9):
        y = horizon + (side - horizon) * (i / 8) ** 1.8
        draw.line((0, y, side, y), fill=(220, 60, 200))
    for i in range(-8, 9):
        draw.line((c + i * side * 0.05, horizon, c + i * side * 0.35, side), fill=(220, 60, 200))
    P.put_text(img, (side * 0.5, side * 0.12), "DEMO", side * 0.1, (255, 255, 255), bold=True, anchor="mm")
    return img


def _vinyl(image, angle):
    """Album art as the label of a spinning record."""
    side = min(image.size)
    record = Image.new("RGB", (side, side), (10, 10, 12))
    draw = ImageDraw.Draw(record)
    c = side / 2
    for k in range(10, int(c), max(2, side // 60)):
        draw.ellipse((c - k, c - k, c + k, c + k), outline=(26, 26, 30))
    label = P.cover_fit(image, (int(side * 0.62), int(side * 0.62))).rotate(-angle, Image.Resampling.BILINEAR)
    record.paste(label, (int(c - label.width / 2), int(c - label.height / 2)), P.circle_mask(label.width))
    draw.ellipse((c - side * 0.025, c - side * 0.025, c + side * 0.025, c + side * 0.025), fill=(0, 0, 0))
    draw.arc((side * 0.08, side * 0.08, side * 0.92, side * 0.92), 200, 250, fill=(70, 70, 80), width=2)
    return record
