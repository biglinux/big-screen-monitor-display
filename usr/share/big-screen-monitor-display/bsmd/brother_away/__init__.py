"""Brother Away — O Náufrago Perplecto!

An animated, narrative theme: a castaway on a tropical island, with a day
and night cycle, weather, persistent progress, stories and a MangoHud-style
telemetry overlay. Rendered as pixel art at a logical resolution and scaled
by an integer factor with nearest-neighbour sampling.
"""

import collections
import os
import random
import time
from datetime import datetime

from PIL import Image, ImageDraw

from . import overlay, stories
from .character import tint
from .dialogue import Dialogue
from .narrative import EVENT, REACTION, Engine, Hero, Memory
from .world import World


def pick_scale(width, height):
    return max(1, round(min(width, height) / 160))


class Reactions:
    """Telemetry -> world reactions with hysteresis and cooldowns."""

    RULES = {
        # name: (enter, exit, metric, activity)
        "heat": (85.0, 65.0, "cpu", "react_heat"),
        "hot": (82.0, 72.0, "temp", "react_hot"),
        "ram": (88.0, 78.0, "ram", "react_ram"),
        "disk": (92.0, 88.0, "disk", "react_disk"),
        "gpu": (80.0, 55.0, "gpu", "react_gpu"),
    }
    HOLD = 8.0           # seconds above the threshold before reacting
    COOLDOWN = 900.0

    def __init__(self):
        self.active = {name: False for name in self.RULES}
        self.above_since = {}
        self.last_fired = {}

    @staticmethod
    def metrics(stats):
        gpus = stats.get("gpus") or []
        gpu = max((g.get("percent", 0) for g in gpus if g.get("path")), default=0)
        return {"cpu": stats.get("cpu_percent", 0), "temp": stats.get("cpu_temp_value") or 0,
                "ram": stats.get("ram_percent", 0), "disk": stats.get("disk_percent", 0), "gpu": gpu}

    def update(self, now, stats):
        """Return the activity to trigger (or None); keeps ``active`` flags."""
        values = self.metrics(stats)
        fire = None
        for name, (enter, leave, metric, activity) in self.RULES.items():
            value = values[metric]
            if not self.active[name]:
                if value >= enter:
                    since = self.above_since.setdefault(name, now)
                    if now - since >= self.HOLD:
                        self.active[name] = True
                        if now - self.last_fired.get(name, -1e9) > self.COOLDOWN and fire is None:
                            self.last_fired[name] = now
                            fire = activity
                else:
                    self.above_since.pop(name, None)
            elif value <= leave:
                self.active[name] = False
                self.above_since.pop(name, None)
        return fire


class BrotherAwayTheme:
    def __init__(self, info, ctx=None):
        self.info = info
        self.ctx = ctx
        self.size = None
        self.rng = random.Random()
        state_dir = getattr(ctx, "state_dir", None)
        persist = state_dir and not getattr(ctx, "preview", False)
        self.memory = Memory(os.path.join(state_dir, "brother_away.json") if persist else None)
        self.dialogue = Dialogue(self.rng)
        self.reactions = Reactions()
        self.last = None
        self.world = None
        self.pending_seek = None
        self.sound_events = collections.deque(maxlen=20)   # (seq, event) read by the sound agent
        self._sound_seq = 0

    # ---------------------------------------------------------- setup
    def _setup(self, width, height):
        self.size = (width, height)
        self.scale = pick_scale(width, height)
        lw, lh = -(-width // self.scale), -(-height // self.scale)
        self.world = World(lw, lh, seed=self.rng.random())
        self.world.raft_stage = self.memory.data["raft"]
        self.world.items = list(self.memory.data["items"])
        lay = self.world.layout
        self.hero = Hero(lay.island_cx, lay.ground)
        story_list, activities = stories.build_registry()
        self.engine = Engine(self.world, self.hero, self.dialogue, self.memory, self.rng, story_list, activities)
        self.last = None

    def debug_seek(self, seconds, story=None, hour=None, weather=None, until_speech=None):
        """Preview/screenshot helper: start ``story`` and advance ``seconds``
        (or until the character says something containing ``until_speech``)."""
        self.pending_seek = (seconds, story, hour, weather, until_speech)

    def _apply_seek(self, settings):
        seconds, story, hour, weather, until_speech = self.pending_seek
        self.pending_seek = None
        self.world.hour_override = hour
        if weather:
            self.world.weather.force(weather, 3600)
            for _ in range(60):
                self.world.weather.update(1.0)
        if story:
            self.engine.forced = story
        step = 1 / 10
        limit = int((120 if until_speech else seconds) / step)
        for _ in range(limit):
            self._advance(step, settings, datetime.now())
            if until_speech and self.hero.speech and until_speech.lower() in self.hero.speech[0].lower():
                for _ in range(int(seconds / step)):
                    self._advance(step, settings, datetime.now())
                break

    # ---------------------------------------------------------- update
    def _advance(self, dt, settings, now):
        stats = self.ctx.telemetry() if self.ctx else {}
        world = self.world
        world.update(dt, now, settings, stats)
        world.floaters[:] = [[t, x, y, s - dt, c] for t, x, y, s, c in world.floaters if s - dt > 0]
        if settings.get("ba_telemetry_reactions", True):
            fire = self.reactions.update(world.time, stats)
            if fire and self.engine.state not in (EVENT, REACTION):
                self.engine.reaction = fire
            active = self.reactions.active
            world.heat = 1.0 if active["heat"] or active["hot"] else max(0.0, world.heat - dt * 0.1)
            world.volcano = min(1.0, world.volcano + dt * 0.2) if active["gpu"] else max(0.0, world.volcano - dt * 0.05)
            world.clutter = int(max(0, min(5, (stats.get("ram_percent", 0) - 70) / 5))) if active["ram"] else 0
            world.chest_full = active["disk"]
        else:
            world.heat = world.volcano = 0.0
            world.clutter = 0
            world.chest_full = False
        if settings.get("ba_animation", True):
            self.engine.update(dt, settings)
        for kind, name in self.engine.events:
            self._sound_seq += 1
            self.sound_events.append((self._sound_seq, f"{kind}:{name}"))
        self.engine.events.clear()
        self.hero.update(dt, world.weather.wind)

    # ---------------------------------------------------------- render
    def render(self, width, height, settings, ctx):
        if self.size != (width, height) or self.world is None:
            self._setup(width, height)
        if ctx is not None:
            self.ctx = ctx
        now_mono = time.monotonic()
        now = datetime.now()
        dt = 0.0 if self.last is None else min(0.25, now_mono - self.last)
        self.last = now_mono
        if self.pending_seek:
            self._apply_seek(settings)
        self._advance(dt if settings.get("ba_animation", True) else 0.0, settings, now)
        logical = self._compose()
        image = logical.resize((logical.width * self.scale, logical.height * self.scale), Image.Resampling.NEAREST)
        if image.size != (width, height):
            image = image.crop((0, 0, width, height))
        self._draw_native(image, settings, now)
        return image

    def _compose(self):
        world, hero = self.world, self.hero
        lay = world.layout
        img = Image.new("RGBA", (lay.w, lay.h))
        world.draw_sky(img)
        d = ImageDraw.Draw(img)
        world.draw_celestial(img, d)
        world.draw_clouds(d)
        world.draw_sea_details(d)
        for actor in world.actors:
            if actor.layer == "sea":
                actor.draw(d, img, world)
        world.draw_island(img, d)
        world.draw_palm(img, d, front=False)
        for actor in world.actors:
            if actor.layer == "back":
                actor.draw(d, img, world)
        pose = hero.pose
        sprite = hero.puppet.render(pose)
        warm = None
        if world.fire_lit and world.light < 0.75 and abs(hero.x - lay.fire_x) < 30:
            warm = ((255, 140, 60), 0.18)
        elif 17.5 < world.hour < 19.0:
            warm = ((255, 150, 90), 0.12)
        sprite = tint(sprite, max(0.42, world.light), warm)
        ax, ay = hero.puppet.anchor(pose)
        y_feet = hero.y + hero.offset_y + (3 if pose.get("submerge") else 0)
        img.paste(sprite, (int(round(hero.x)) - ax, int(round(y_feet)) - ay), sprite)
        self.head_logical = (hero.x + (hero.puppet.head_world_offset(pose)[0] if not pose.get("lying")
                                       else -14 * hero.facing),
                             y_feet + (hero.puppet.head_world_offset(pose)[1] - 8 if not pose.get("lying") else -6))
        for actor in world.actors:
            if actor.layer == "front":
                actor.draw(d, img, world)
        world.draw_palm(img, d, front=True)
        world.draw_weather(img, d)
        return img.convert("RGB")

    def _draw_native(self, image, settings, now):
        s = self.scale
        stats = self.ctx.telemetry() if self.ctx else {}
        dim = settings.get("overlay_auto_dim", True) and self.engine.state in (EVENT, REACTION)
        hud = overlay.draw_hud(image, settings, stats, now, dim=dim)
        for text, x, y, _left, color in self.world.floaters:
            overlay.draw_floater(image, text, (int(x * s), int(y * s)), s, color)
        hero = self.hero
        hx, hy = self.head_logical
        if hero.emote:
            overlay.draw_floater(image, hero.emote[0], (int(hx * s), int((hy - 4) * s)), s, (255, 230, 120))
        if hero.speech and settings.get("ba_subtitles", True):
            overlay.draw_bubble(image, hero.speech[0], (int(hx * s), int(hy * s)), avoid=hud, scale=s)

    def frame_interval(self, settings, ctx):
        if not settings.get("ba_animation", True):
            return 1.0 - (time.time() % 1.0) + 0.01
        fps = getattr(ctx, "target_fps", 8.0) or 8.0
        return 1.0 / max(1.0, min(15.0, fps))

    def close(self):
        self.memory.maybe_save(force=True)
