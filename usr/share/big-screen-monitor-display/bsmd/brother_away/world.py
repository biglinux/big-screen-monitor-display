"""The island: layout, sky, weather, scenery and event actors.

Everything is drawn at the logical pixel-art resolution. Layers use their
own cadence (waves at 2 Hz, clouds move by whole pixels, the sky gradient is
cached per minute) so that consecutive frames differ only where something
really moves - the frame optimizer then sends small dirty rectangles.
"""

import math
import random
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw

from . import palette as P

SYNODIC_MONTH = 29.530588853
NEW_MOON_REF = datetime(2000, 1, 6, 18, 14)


def moon_phase(when):
    """0 = new moon, 0.5 = full moon."""
    days = (when - NEW_MOON_REF).total_seconds() / 86400.0
    return (days / SYNODIC_MONTH) % 1.0


_MOON_CACHE = {}


def moon_sprite(radius, phase):
    """Moon disc with the terminator for ``phase`` (shadow clipped to the disc)."""
    key = (radius, round(phase, 2))
    if key not in _MOON_CACHE:
        size = radius * 2 + 1
        disc = Image.new("L", (size, size), 0)
        ImageDraw.Draw(disc).ellipse((0, 0, size - 1, size - 1), fill=255)
        if phase < 0.5:
            shift = -round(phase * 4 * radius)
        else:
            shift = round((1 - phase) * 4 * radius)
        shadow = Image.new("L", (size, size), 0)
        ImageDraw.Draw(shadow).ellipse((shift, 0, shift + size - 1, size - 1), fill=255)
        sprite = Image.new("RGBA", (size, size), (*P.MOON, 0))
        sprite.putalpha(disc)
        dark = Image.new("RGBA", (size, size), (*P.MOON_SHADOW, 255))
        mask = Image.fromarray((np.array(disc) & np.array(shadow)), "L")
        sprite.paste(dark, (0, 0), mask)
        if 0.45 < phase < 0.55:
            sprite.putpixel((radius - 2, radius - 1), (*P.shade(P.MOON, 0.85), 255))
            sprite.putpixel((radius + 1, radius + 2), (*P.shade(P.MOON, 0.85), 255))
        _MOON_CACHE[key] = sprite
    return _MOON_CACHE[key]


class Layout:
    def __init__(self, width, height):
        self.w, self.h = width, height
        portrait = height > width
        self.portrait = portrait
        self.horizon = int(height * (0.46 if portrait else 0.5))
        island_w = int(min(width * (0.94 if portrait else 0.78), height * 1.7))
        self.island_cx = int(width * 0.52)
        self.island_left = self.island_cx - island_w // 2
        self.island_right = self.island_cx + island_w // 2
        sea_h = height - self.horizon
        self.island_top = self.horizon + int(sea_h * (0.42 if portrait else 0.36))
        self.island_bottom = min(height - 2, self.island_top + int(sea_h * 0.4))
        self.ground = self.island_top + max(7, int((self.island_bottom - self.island_top) * 0.48))
        self.walk_min = self.island_left + 14
        self.walk_max = self.island_right - 12
        island_w = self.island_right - self.island_left
        # The palm stands on the right (the HUD lives top-left); sea activities
        # (raft, fishing, swimming, visitors) happen on the left shore.
        self.palm_x = self.island_left + int(island_w * 0.8)
        self.fire_x = self.island_cx + int(island_w * 0.1)
        self.raft_x = self.island_left + int(island_w * 0.17)
        self.rocks_x = self.island_left + int(island_w * 0.42)
        self.shore_dir = -1
        self.shore_x = self.island_left + 10
        self.swim_y = self.ground + max(3, (self.island_bottom - self.ground) // 2)
        self.sea_x = max(12, self.island_left - 6)
        self.offscreen_sea = -30


class Weather:
    STATES = ("clear", "windy", "rain", "storm", "fog", "rainbow")
    NEXT = {
        "clear": (("clear", 5), ("windy", 3), ("rain", 1.5), ("fog", 0.7)),
        "windy": (("clear", 3), ("windy", 2), ("rain", 2), ("storm", 0.6)),
        "rain": (("rainbow", 3), ("rain", 1.5), ("storm", 0.8), ("windy", 1)),
        "storm": (("rain", 3), ("rainbow", 1)),
        "fog": (("clear", 3), ("fog", 1)),
        "rainbow": (("clear", 4), ("windy", 1)),
    }

    def __init__(self, rng):
        self.rng = rng
        self.state = "clear"
        self.remaining = rng.uniform(600, 1200)
        self.wind = 0.0
        self.rain = 0.0
        self.darkness = 0.0
        self.fog = 0.0
        self.rainbow = 0.0
        self.flash = 0.0
        self.forced = None

    def force(self, state, duration):
        self.state = state
        self.remaining = duration
        self.forced = state

    def update(self, dt, enabled=True):
        if not enabled:
            self.state = "clear"
        else:
            self.remaining -= dt
            if self.remaining <= 0:
                options = self.NEXT[self.state]
                total = sum(w for _, w in options)
                pick = self.rng.uniform(0, total)
                for name, weight in options:
                    pick -= weight
                    if pick <= 0:
                        self.state = name
                        break
                self.forced = None
                self.remaining = self.rng.uniform(240, 420) if self.state in ("storm", "rainbow") \
                    else self.rng.uniform(600, 1500)
        target = {"clear": (0.1, 0, 0, 0, 0), "windy": (0.8, 0, 0.05, 0, 0), "rain": (0.35, 0.6, 0.25, 0, 0),
                  "storm": (1.0, 1.0, 0.45, 0, 0), "fog": (0.05, 0, 0.1, 0.8, 0),
                  "rainbow": (0.2, 0.05, 0, 0, 1)}[self.state]
        k = min(1.0, dt * 0.25)
        self.wind += (target[0] - self.wind) * k
        self.rain += (target[1] - self.rain) * k
        self.darkness += (target[2] - self.darkness) * k
        self.fog += (target[3] - self.fog) * k
        self.rainbow += (target[4] - self.rainbow) * k
        if self.state == "storm" and self.rng.random() < dt * 0.08:
            self.flash = 1.0
        self.flash = max(0.0, self.flash - dt * 3)


# --------------------------------------------------------------- actors -----

class Actor:
    layer = "front"      # "sea" (behind island), "back", "front"
    done = False

    def update(self, dt, world):
        pass

    def draw(self, d, img, world):
        pass


class FallingCoconut(Actor):
    def __init__(self, x, y0, target_y, bounce=True, hit=None):
        self.x, self.y, self.vy = float(x), float(y0), 0.0
        self.target = target_y
        self.bounce = bounce
        self.landed = False
        self.hit = hit           # y at which it "hits" a head, or None
        self.hit_done = False
        self.rest = 0.0
        self.vx = 0.0

    def update(self, dt, world):
        if self.landed:
            self.rest += dt
            self.x += self.vx * dt
            self.vx *= 0.9
            if self.rest > 25:
                self.done = True
            return
        self.vy += 240 * dt
        self.y += self.vy * dt
        if self.hit is not None and not self.hit_done and self.y >= self.hit:
            self.hit_done = True
            self.vy = -self.vy * 0.45
            self.vx = 28
        if self.y >= self.target:
            self.y = self.target
            if self.bounce and abs(self.vy) > 40:
                self.vy = -self.vy * 0.35
            else:
                self.landed = True

    def draw(self, d, img, world):
        x, y = round(self.x), round(self.y)
        d.ellipse((x - 2, y - 3, x + 2, y + 1), fill=P.COCONUT, outline=P.OUTLINE)
        d.point((x - 1, y - 2), fill=P.WOOD)


class Shark(Actor):
    layer = "sea"

    def __init__(self, x, y, speed=8.0):
        self.x, self.y = float(x), y
        self.target = float(x)
        self.speed = speed
        self.laugh = 0.0
        self.visible = True
        self.t = 0.0

    def update(self, dt, world):
        self.t += dt
        self.laugh = max(0.0, self.laugh - dt)
        delta = self.target - self.x
        step = self.speed * dt
        self.x += max(-step, min(step, delta))

    def draw(self, d, img, world):
        if not self.visible:
            return
        x, y = round(self.x), self.y
        bob = 1 if int(self.t * 3) % 2 else 0
        if self.laugh > 0:
            # Head out of the water, "laughing".
            d.ellipse((x - 8, y - 6 - bob, x + 8, y + 3), fill=P.SHARK, outline=P.OUTLINE)
            d.chord((x - 6, y - 4 - bob, x + 6, y + 3), 0, 180, fill=P.SHARK_LIGHT)
            d.rectangle((x - 4, y - 1 - bob, x + 4, y + 1 - bob), fill=P.MOUTH)
            for tx in range(x - 4, x + 5, 2):
                d.point((tx, y - 1 - bob), fill=P.TEETH)
            d.point((x - 4, y - 4 - bob), fill=P.EYE_WHITE)
            d.point((x + 3, y - 4 - bob), fill=P.EYE_WHITE)
        else:
            d.polygon([(x - 3, y), (x + 3, y), (x + 1, y - 7 - bob)], fill=P.SHARK, outline=P.OUTLINE)
            d.line([(x - 6, y + 1), (x + 6, y + 1)], fill=P.FOAM)


class Crab(Actor):
    def __init__(self, x, y, target, speed=14):
        self.x, self.y, self.target, self.speed = float(x), y, float(target), speed
        self.t = 0.0
        self.carry = None

    def update(self, dt, world):
        self.t += dt
        delta = self.target - self.x
        step = self.speed * dt
        self.x += max(-step, min(step, delta))

    @property
    def arrived(self):
        return abs(self.target - self.x) < 0.5

    def draw(self, d, img, world):
        x, y = round(self.x), self.y
        legs = int(self.t * 10) % 2
        d.ellipse((x - 3, y - 3, x + 3, y), fill=P.CRAB, outline=P.OUTLINE)
        for dx in (-3, 3):
            d.line([(x + dx, y - 1), (x + dx + (2 if dx > 0 else -2), y + legs)], fill=P.CRAB_DARK)
        d.point((x - 4, y - 4), fill=P.CRAB)
        d.point((x + 4, y - 4), fill=P.CRAB)
        d.point((x - 1, y - 4), fill=P.EYE_WHITE)
        d.point((x + 1, y - 4), fill=P.EYE_WHITE)
        if self.carry == "glasses":
            d.rectangle((x - 3, y - 6, x + 3, y - 5), fill=P.GLASSES)
            d.point((x - 2, y - 6), fill=P.LENS_GOLD)


class Gull(Actor):
    layer = "front"

    def __init__(self, x, y, tx, ty, speed=40):
        self.x, self.y = float(x), float(y)
        self.tx, self.ty = float(tx), float(ty)
        self.speed = speed
        self.t = 0.0
        self.carry = None

    def update(self, dt, world):
        self.t += dt
        dx, dy = self.tx - self.x, self.ty - self.y
        dist = math.hypot(dx, dy)
        if dist > 0.5:
            step = min(dist, self.speed * dt)
            self.x += dx / dist * step
            self.y += dy / dist * step

    @property
    def arrived(self):
        return math.hypot(self.tx - self.x, self.ty - self.y) < 1

    def draw(self, d, img, world):
        x, y = round(self.x), round(self.y)
        up = int(self.t * 6) % 2
        d.ellipse((x - 2, y - 1, x + 2, y + 1), fill=P.GULL)
        wing = -3 if up else 1
        d.line([(x - 5, y + wing), (x - 1, y)], fill=P.GULL_DARK)
        d.line([(x + 1, y), (x + 5, y + wing)], fill=P.GULL_DARK)
        d.point((x + 3, y), fill=P.SHOE_ACCENT)
        if self.carry == "fish":
            d.line([(x, y + 2), (x + 2, y + 2)], fill=P.FISH)


class UFO(Actor):
    layer = "back"

    def __init__(self, x, y, tx, ty):
        self.x, self.y, self.tx, self.ty = float(x), float(y), float(tx), float(ty)
        self.beam = 0.0
        self.t = 0.0

    def update(self, dt, world):
        self.t += dt
        self.x += (self.tx - self.x) * min(1.0, dt * 1.2)
        self.y += (self.ty - self.y) * min(1.0, dt * 1.2)

    def draw(self, d, img, world):
        x, y = round(self.x), round(self.y + math.sin(self.t * 3))
        if self.beam > 0:
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            od.polygon([(x - 4, y + 2), (x + 4, y + 2), (x + 12, world.layout.ground + 1),
                        (x - 12, world.layout.ground + 1)], fill=(*P.BEAM, int(90 * self.beam)))
            img.alpha_composite(overlay)
        d.ellipse((x - 10, y - 2, x + 10, y + 3), fill=P.UFO, outline=P.OUTLINE)
        d.ellipse((x - 5, y - 6, x + 5, y + 1), fill=P.UFO_DARK, outline=P.OUTLINE)
        for i, lx in enumerate(range(x - 7, x + 8, 4)):
            on = (int(self.t * 6) + i) % 2
            d.point((lx, y + 1), fill=P.UFO_LIGHT if on else P.UFO_DARK)


class Ship(Actor):
    layer = "sea"

    def __init__(self, x, y, speed):
        self.x, self.y, self.speed = float(x), y, speed

    def update(self, dt, world):
        self.x += self.speed * dt
        if self.x > world.layout.w + 30 or self.x < -30:
            self.done = True

    def draw(self, d, img, world):
        x, y = round(self.x), self.y
        d.polygon([(x - 7, y), (x + 7, y), (x + 5, y + 2), (x - 5, y + 2)], fill=P.SHIP)
        d.line([(x, y), (x, y - 8)], fill=P.SHIP)
        d.polygon([(x + 1, y - 8), (x + 6, y - 2), (x + 1, y - 2)], fill=P.SAIL)
        d.polygon([(x - 1, y - 7), (x - 5, y - 2), (x - 1, y - 2)], fill=P.SAIL)


class Mermaid(Actor):
    layer = "sea"

    def __init__(self, x, y):
        self.x, self.y = x, y
        self.rise = 0.0
        self.leaving = False
        self.t = 0.0

    def update(self, dt, world):
        self.t += dt
        self.rise = max(0.0, min(1.0, self.rise + (-dt if self.leaving else dt) * 1.2))
        if self.leaving and self.rise <= 0:
            self.done = True

    def draw(self, d, img, world):
        h = round(9 * self.rise)
        if h <= 0:
            return
        x, y = self.x, self.y
        d.ellipse((x - 2, y - h, x + 2, y - h + 4), fill=P.SKIN_LIGHT, outline=P.OUTLINE)
        d.line([(x - 2, y - h), (x - 4, y - h + 6)], fill=P.MERMAID_HAIR, width=2)
        if h > 4:   # the body only shows once the head is above the water line
            d.rectangle((x - 2, y - h + 4, x + 2, y), fill=P.SKIN_LIGHT)
        if int(self.t * 2) % 2:
            d.line([(x + 6, y - 1), (x + 9, y - 3)], fill=P.MERMAID_TAIL, width=2)
        d.line([(x - 5, y + 1), (x + 5, y + 1)], fill=P.FOAM)


class FloatingItem(Actor):
    layer = "sea"

    def __init__(self, kind, x, y, tx, speed=6):
        self.kind, self.x, self.y, self.tx, self.speed = kind, float(x), y, float(tx), speed
        self.t = 0.0

    @property
    def arrived(self):
        return abs(self.x - self.tx) < 0.5

    def update(self, dt, world):
        self.t += dt
        delta = self.tx - self.x
        step = self.speed * dt
        self.x += max(-step, min(step, delta))

    def draw(self, d, img, world):
        x, y = round(self.x), self.y + (1 if int(self.t * 2) % 2 else 0)
        draw_item(d, self.kind, x, y)


class JumpingFish(Actor):
    layer = "sea"

    def __init__(self, x, y, direction=1):
        self.x0, self.y0, self.dir = x, y, direction
        self.t = 0.0

    def update(self, dt, world):
        self.t += dt
        if self.t > 1.2:
            self.done = True

    def draw(self, d, img, world):
        t = self.t / 1.2
        x = round(self.x0 + self.dir * 16 * t)
        y = round(self.y0 - math.sin(t * math.pi) * 12)
        d.ellipse((x - 3, y - 1, x + 3, y + 1), fill=P.FISH, outline=P.OUTLINE)
        d.point((x - 4 * self.dir, y), fill=P.FISH)


class BigWave(Actor):
    layer = "front"

    def __init__(self, x_start, x_end, y, speed=-30):
        self.x, self.x_end, self.y, self.speed = float(x_start), x_end, y, speed
        self.t = 0.0

    @property
    def arrived(self):
        return self.x <= self.x_end

    def update(self, dt, world):
        self.t += dt
        self.x += self.speed * dt
        if self.x < self.x_end - 30:
            self.done = True

    def draw(self, d, img, world):
        x, y = round(self.x), self.y
        d.chord((x - 8, y - 10, x + 14, y + 6), 180, 360, fill=world.sea_color, outline=P.OUTLINE)
        d.arc((x - 6, y - 9, x + 10, y + 2), 200, 330, fill=P.FOAM, width=2)
        for i in range(4):
            d.point((x - 4 + i * 3, y - 7 + (i % 2)), fill=P.FOAM)


class Particle(Actor):
    def __init__(self, x, y, vx, vy, color, life, gravity=0.0, size=1):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.color, self.life, self.gravity, self.size = color, life, gravity, size

    def update(self, dt, world):
        self.vy += self.gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        if self.life <= 0:
            self.done = True

    def draw(self, d, img, world):
        x, y = round(self.x), round(self.y)
        if self.size > 1:
            d.rectangle((x, y, x + self.size - 1, y + self.size - 1), fill=self.color)
        else:
            d.point((x, y), fill=self.color)


def draw_item(d, kind, x, y):
    if kind == "bottle":
        d.rectangle((x - 1, y - 5, x + 1, y), fill=P.BOTTLE, outline=P.OUTLINE)
        d.point((x, y - 6), fill=P.WOOD)
        d.point((x, y - 3), fill=P.PAPER)
    elif kind == "shell":
        d.pieslice((x - 3, y - 3, x + 3, y + 3), 180, 360, fill=P.SAND_LIGHT, outline=P.OUTLINE)
        d.line([(x, y - 3), (x, y)], fill=P.SAND_SHADE)
    elif kind == "radio":
        d.rectangle((x - 4, y - 4, x + 4, y), fill=P.ROCK_DARK, outline=P.OUTLINE)
        d.ellipse((x - 3, y - 3, x - 1, y - 1), fill=P.ROCK_LIGHT)
        d.line([(x + 3, y - 4), (x + 5, y - 8)], fill=P.ROCK_LIGHT)
    elif kind == "chest":
        d.rectangle((x - 5, y - 5, x + 5, y), fill=P.CHEST, outline=P.OUTLINE)
        d.line([(x - 5, y - 3), (x + 5, y - 3)], fill=P.GOLD)
        d.point((x, y - 2), fill=P.GOLD)
    elif kind == "chest_full":
        draw_item(d, "chest", x, y)
        for i, color in enumerate((P.GOLD, P.BOTTLE, P.PAPER, P.CRAB, P.GOLD)):
            d.point((x - 4 + i * 2, y - 6 - (i % 2)), fill=color)
    elif kind == "crate":
        d.rectangle((x - 3, y - 5, x + 3, y), fill=P.WOOD, outline=P.OUTLINE)
        d.line([(x - 3, y - 5), (x + 3, y)], fill=P.WOOD_DARK)
    elif kind == "barrel":
        d.rectangle((x - 3, y - 6, x + 3, y), fill=P.WOOD_DARK, outline=P.OUTLINE)
        d.line([(x - 3, y - 4), (x + 3, y - 4)], fill=P.ROCK)
        d.line([(x - 3, y - 2), (x + 3, y - 2)], fill=P.ROCK)
    elif kind == "sandcastle":
        d.rectangle((x - 4, y - 4, x + 4, y), fill=P.SAND_LIGHT, outline=P.SAND_SHADE)
        d.rectangle((x - 2, y - 7, x + 2, y - 4), fill=P.SAND_LIGHT, outline=P.SAND_SHADE)
        d.point((x, y - 8), fill=P.CRAB)
    elif kind == "mirror":
        d.ellipse((x - 3, y - 6, x + 3, y), fill=P.RAIN, outline=P.OUTLINE)
        d.point((x - 1, y - 4), fill=P.FOAM)
    elif kind == "star":
        d.point((x, y - 2), fill=P.GOLD)
        d.line([(x - 2, y), (x + 2, y)], fill=P.GOLD)
        d.point((x, y - 1), fill=P.GOLD)
        d.point((x, y + 1), fill=P.GOLD)


class World:
    def __init__(self, width, height, seed=None):
        self.layout = Layout(width, height)
        self.rng = random.Random(seed)
        self.weather = Weather(self.rng)
        self.actors = []
        self.time = 0.0
        self.hour = 15.0
        self.hour_override = None
        self.when = datetime.now()
        self.palm_lean = 0.0          # extra lean (stories make the palm "answer")
        self.palm_shake = 0.0
        self.coconuts = 3
        self.fire_lit = False
        self.raft_stage = 0
        self.raft_broken = 0.0
        self.raft_dx = 0
        self.floaters = []          # [text, x, y, seconds left, colour] drawn at native resolution
        self.items = []
        self.clutter = 0
        self.volcano = 0.0
        self.heat = 0.0
        self.chest_full = False
        self.sea_color = P.SKY_KEYS[4][3]
        self._sky_cache = (None, None)
        self._island_cache = (None, None)
        self.clouds = [self._new_cloud(initial=True) for _ in range(4)]
        self.stars = [(self.rng.randrange(width), self.rng.randrange(max(1, self.layout.horizon - 4)),
                       self.rng.random() * 6.28, self.rng.random()) for _ in range(max(12, width * height // 700))]
        self.rain_drops = [(self.rng.random() * width, self.rng.random() * height) for _ in range(width // 2)]
        self.light = 1.0

    # ---------------------------------------------------------- update
    def _new_cloud(self, initial=False):
        lay = self.layout
        width = self.rng.randint(14, 30)
        x = self.rng.uniform(-width, lay.w) if initial else (-width - 2 if self.weather.wind >= 0 else lay.w + 2)
        y = self.rng.randint(4, max(6, lay.horizon - 22))
        puffs = [(self.rng.randint(0, width - 6), self.rng.randint(-3, 2), self.rng.randint(4, 8))
                 for _ in range(self.rng.randint(3, 6))]
        return {"x": x, "y": y, "w": width, "puffs": puffs, "speed": self.rng.uniform(0.6, 1.4)}

    def update(self, dt, when, settings, telemetry):
        self.time += dt
        self.when = when
        if self.hour_override is not None:
            self.hour = self.hour_override
        elif settings.get("ba_day_night", True):
            self.hour = when.hour + when.minute / 60 + when.second / 3600
        else:
            self.hour = 15.0
        self.weather.update(dt, settings.get("ba_weather", True))
        for cloud in self.clouds:
            cloud["x"] += (0.5 + abs(self.weather.wind) * 4) * cloud["speed"] * dt * (1 if self.weather.wind >= 0 else -1)
        self.clouds = [c for c in self.clouds if -c["w"] - 4 < c["x"] < self.layout.w + 4]
        want = 4 + int(self.weather.darkness * 6)
        while len(self.clouds) < want:
            self.clouds.append(self._new_cloud())
        for actor in self.actors:
            actor.update(dt, self)
        self.actors = [a for a in self.actors if not a.done]
        self.palm_shake = max(0.0, self.palm_shake - dt * 1.5)
        self.raft_broken = max(0.0, self.raft_broken - dt * 0.02)
        if self.coconuts < 3 and self.rng.random() < dt / 600:
            self.coconuts += 1      # coconuts grow back slowly
        night = self.hour >= 18.5 or self.hour < 5.5
        if night and not self.fire_lit and self.rng.random() < dt / 120:
            self.fire_lit = True
        if not night and self.fire_lit and 8 < self.hour < 17 and self.rng.random() < dt / 300:
            self.fire_lit = False

    # ---------------------------------------------------------- drawing
    def palm_crown(self):
        lay = self.layout
        height = int((lay.ground - lay.horizon) + lay.h * 0.18)
        lean = 10 + self.weather.wind * 3 + self.palm_lean + math.sin(math.floor(self.time * 4) / 4 * 1.3) * self.weather.wind
        lean += math.sin(self.time * 18) * 2 * self.palm_shake
        top_x = lay.palm_x + lean
        top_y = lay.ground - height
        return top_x, top_y, height, lean

    def draw_sky(self, img):
        zenith, horizon, sea_top, sea_bottom, light = P.sky_at(self.hour)
        w = self.weather
        if w.darkness > 0.01:
            gray = (90, 96, 108)
            zenith = P.mix(zenith, P.shade(gray, light), w.darkness)
            horizon = P.mix(horizon, P.shade(gray, light * 1.1), w.darkness)
            sea_top = P.mix(sea_top, P.shade((60, 70, 86), light), w.darkness * 0.8)
            light *= 1 - w.darkness * 0.35
        self.light = light
        self.sea_color = sea_top
        key = (int(self.hour * 60), round(w.darkness, 2), self.layout.w, self.layout.h)
        if self._sky_cache[0] != key:
            lay = self.layout
            sky = np.zeros((lay.h, lay.w, 3), dtype=np.uint8)
            t = np.linspace(0, 1, lay.horizon)[:, None] ** 1.4
            sky[:lay.horizon] = (np.array(zenith) * (1 - t) + np.array(horizon) * t)[:, None, :].astype(np.uint8)
            sea_rows = lay.h - lay.horizon
            t2 = np.linspace(0, 1, sea_rows)[:, None]
            sky[lay.horizon:] = (np.array(sea_top) * (1 - t2) + np.array(sea_bottom) * t2)[:, None, :].astype(np.uint8)
            # Dithered bands keep the VGA look on gradients.
            sky[1:lay.horizon:2, ::2] = (sky[1:lay.horizon:2, ::2] * 0.97).astype(np.uint8)
            self._sky_cache = (key, Image.fromarray(sky, "RGB").convert("RGBA"))
        img.paste(self._sky_cache[1])

    def draw_celestial(self, img, d):
        lay = self.layout
        light = self.light
        hour = self.hour
        night_amount = max(0.0, min(1.0, (0.7 - light) / 0.25))
        clear = 1 - max(self.weather.darkness * 1.5, self.weather.fog)
        if night_amount > 0 and clear > 0.2:
            star_t = math.floor(self.time)          # twinkle steps once per second
            for x, y, phase, size in self.stars:
                twinkle = math.sin(star_t * (1.5 + size) + phase)
                if twinkle > -0.3 and size * night_amount * clear > 0.15:
                    d.point((x, y), fill=P.mix(P.SKY_KEYS[0][1], P.STAR, night_amount * (0.6 + 0.4 * twinkle)))
        # Sun: 6:00 -> 18:30 across the sky.
        if 5.6 < hour < 18.9:
            t = (hour - 5.6) / 13.3
            x = int(lay.w * (0.06 + 0.88 * t))
            y = int(lay.horizon - math.sin(t * math.pi) * (lay.horizon * 0.82)) + 2
            radius = 5 + (2 if self.heat > 0.5 else 0) + (1 if t < 0.12 or t > 0.88 else 0)
            color = P.mix((255, 244, 180), (255, 150, 70), abs(t - 0.5) * 2 if abs(t - 0.5) > 0.35 else 0)
            if self.heat > 0.2:
                r2 = radius + 3 + int(math.sin(math.floor(self.time * 2) / 2 * 4) + 1)
                d.ellipse((x - r2, y - r2, x + r2, y + r2), fill=P.mix(color, (255, 255, 255), 0.3))
            d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        # Moon: 18:30 -> 6:00, real phase.
        if hour > 18.2 or hour < 6.2:
            t = ((hour - 18.2) % 24) / 12.0
            x = int(lay.w * (0.08 + 0.84 * t))
            y = int(lay.horizon - math.sin(min(1, t) * math.pi) * (lay.horizon * 0.75)) + 3
            sprite = moon_sprite(5, moon_phase(self.when))
            img.alpha_composite(sprite, (x - 5, y - 5))
        if self.weather.rainbow > 0.1 and 6 < hour < 18:
            cx, cy = int(lay.w * 0.3), lay.horizon + 4
            for i, color in enumerate(((236, 70, 70), (250, 160, 60), (250, 230, 90), (90, 200, 100),
                                       (80, 140, 230), (140, 90, 200))):
                r = int(lay.horizon * 0.8) - i
                alpha_color = P.mix(self.sea_color, color, self.weather.rainbow * 0.7)
                d.arc((cx - r, cy - r, cx + r, cy + r), 190, 350, fill=alpha_color)

    def draw_clouds(self, d):
        light = self.light
        base = P.shade(P.mix((250, 250, 252), (110, 116, 128), self.weather.darkness), max(0.35, light))
        hour = self.hour
        if 17.5 < hour < 19.2 or 5.3 < hour < 6.8:
            base = P.mix(base, (250, 170, 140), 0.35)
        shadow = P.shade(base, 0.82)
        for cloud in self.clouds:
            x0, y0 = int(cloud["x"]), cloud["y"]
            for px, py, r in cloud["puffs"]:
                d.ellipse((x0 + px - r, y0 + py - r // 2 + 1, x0 + px + r, y0 + py + r // 2 + 1), fill=shadow)
            for px, py, r in cloud["puffs"]:
                d.ellipse((x0 + px - r, y0 + py - r // 2, x0 + px + r, y0 + py + r // 2 - 1), fill=base)

    def draw_sea_details(self, d):
        lay = self.layout
        wave_t = math.floor(self.time)   # waves step at 1 Hz: retro shimmer, small USB traffic
        rough = 0.3 + abs(self.weather.wind) * 0.9 + self.weather.rain * 0.4
        foam = P.shade(P.FOAM, max(0.45, self.light))
        highlight = P.mix(self.sea_color, foam, 0.35)
        rows = range(lay.horizon + 3, lay.h, 4)
        for i, y in enumerate(rows):
            depth = (y - lay.horizon) / max(1, lay.h - lay.horizon)
            spacing = int(18 - depth * 8)
            length = 2 + int(depth * 3 + rough * 2)
            shift = int((wave_t * (3 + depth * 6) + i * 7) % spacing)
            for x in range(-spacing + shift, lay.w, spacing):
                if lay.island_left - 4 < x < lay.island_right + 4 and lay.island_top - 3 < y < lay.island_bottom + 3:
                    continue
                d.line([(x, y), (x + length, y)], fill=highlight if (x // spacing + i) % 3 else foam)
        if self.volcano > 0.05:
            vx = int(lay.w * 0.12)
            vy = lay.horizon
            d.polygon([(vx - 12, vy), (vx - 3, vy - 10), (vx + 3, vy - 10), (vx + 12, vy)],
                      fill=P.shade(P.VOLCANO, max(0.5, self.light)))
            d.line([(vx - 2, vy - 10), (vx + 2, vy - 10)], fill=P.LAVA)
            for k in range(3):
                phase = (self.time * 0.5 + k / 3) % 1
                r = 1 + int(phase * 3)
                sx = vx + int(math.sin(phase * 6 + k) * 2) + int(phase * 6 * (1 if self.weather.wind >= 0 else -1))
                sy = vy - 12 - int(phase * 14)
                d.ellipse((sx - r, sy - r, sx + r, sy + r), fill=P.shade(P.SMOKE, max(0.5, self.light)))

    def _island_layer(self):
        lay = self.layout
        key = (lay.w, lay.h, round(self.light, 2))
        if self._island_cache[0] == key:
            return self._island_cache[1]
        layer = Image.new("RGBA", (lay.w, lay.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        light = max(0.4, self.light)
        sand, shade, bright, wet = (P.shade(c, light) for c in (P.SAND, P.SAND_SHADE, P.SAND_LIGHT, P.SAND_WET))
        box = (lay.island_left, lay.island_top, lay.island_right, lay.island_bottom + 6)
        d.ellipse((box[0] - 4, box[1] + 2, box[2] + 4, box[3] + 2), fill=wet)
        d.ellipse(box, fill=sand)
        d.ellipse((box[0] + 6, box[1] + 1, box[2] - 10, box[1] + (box[3] - box[1]) // 2), fill=bright)
        d.chord((box[0], box[1] + 3, box[2], box[3]), 20, 160, fill=shade)
        rng = random.Random(42)
        for _ in range((lay.island_right - lay.island_left) // 3):
            x = rng.randint(lay.island_left + 8, lay.island_right - 8)
            y = rng.randint(lay.island_top + 2, lay.island_bottom - 2)
            d.point((x, y), fill=shade if rng.random() < 0.6 else bright)
        # Rocks
        rx, ry = lay.rocks_x, lay.ground + 3
        for dx, dy, r in ((0, 0, 5), (6, 2, 3), (-5, 2, 3)):
            d.ellipse((rx + dx - r, ry + dy - r, rx + dx + r, ry + dy + r // 2 + 1),
                      fill=P.shade(P.ROCK, light), outline=P.shade(P.OUTLINE, 1))
            d.point((rx + dx - r // 2, ry + dy - r // 2), fill=P.shade(P.ROCK_LIGHT, light))
        # Bushes around the palm base
        for dx, r in ((-9, 5), (8, 4), (-2, 3)):
            bx, by = lay.palm_x + dx, lay.ground - 1
            d.ellipse((bx - r, by - r, bx + r, by + 2), fill=P.shade(P.BUSH, light), outline=P.OUTLINE)
            d.point((bx - 1, by - r + 1), fill=P.shade(P.BUSH_LIGHT, light))
        self._island_cache = (key, layer)
        return layer

    def draw_island(self, img, d):
        lay = self.layout
        img.alpha_composite(self._island_layer())
        light = max(0.4, self.light)
        # Shore foam ring (animated)
        foam = P.shade(P.FOAM, light)
        t = math.floor(self.time)
        cx = (lay.island_left + lay.island_right) / 2
        rx = (lay.island_right - lay.island_left) / 2 + 3
        ry = (lay.island_bottom + 6 - lay.island_top) / 2 + 2
        cy = (lay.island_top + lay.island_bottom + 6) / 2 + 1
        for k in range(28):
            a = k / 28 * math.pi * 2 + t * 0.15
            if math.sin(a) < -0.2:
                continue
            x = cx + math.cos(a) * (rx + math.sin(t * 2 + k) * 1.2)
            y = cy + math.sin(a) * ry
            d.point((round(x), round(y)), fill=foam)
        self._draw_fire(d, light)
        self._draw_raft(d, light)
        for i, kind in enumerate(self.items[-6:]):
            x = lay.rocks_x + 12 + i * 7
            if x < lay.island_right - 6:
                draw_item(d, kind, x, lay.ground + 5)
        for i in range(self.clutter):
            x = lay.island_left + 18 + i * 8
            draw_item(d, "crate" if i % 2 else "barrel", x, lay.ground + 7)
        if self.chest_full:
            draw_item(d, "chest_full", lay.rocks_x - 12, lay.ground + 6)

    def draw_palm(self, img, d, front=False):
        lay = self.layout
        top_x, top_y, height, lean = self.palm_crown()
        light = max(0.4, self.light)
        trunk, trunk_dark = P.shade(P.PALM_TRUNK, light), P.shade(P.PALM_TRUNK_DARK, light)
        if not front:
            segments = 9
            prev = (lay.palm_x, lay.ground)
            for i in range(1, segments + 1):
                t = i / segments
                x = lay.palm_x + lean * (t ** 1.8)
                y = lay.ground - height * t
                width = max(2, 4 - int(t * 2))
                d.line([prev, (x, y)], fill=trunk, width=width + 1)
                d.point((round(x) - 1, round(y)), fill=trunk_dark)
                prev = (x, y)
            for k in range(min(3, self.coconuts)):
                cx, cy = round(top_x) - 2 + k * 2, round(top_y) + 2 + (k % 2)
                d.ellipse((cx - 2, cy - 1, cx + 1, cy + 2), fill=P.shade(P.COCONUT, light), outline=P.OUTLINE)
            return
        # Fronds (drawn after the character so he can stand "under" them).
        frond_t = math.floor(self.time * 4) / 4      # fronds move at 4 Hz (small dirty area)
        sway = math.sin(frond_t * 1.6) * (1 + abs(self.weather.wind) * 3) + self.weather.wind * 8
        sway += math.sin(self.time * 20) * 5 * self.palm_shake
        leaf, leaf_dark, leaf_light = (P.shade(c, light) for c in (P.PALM_LEAF, P.PALM_LEAF_DARK, P.PALM_LEAF_LIGHT))
        for index, (angle, length) in enumerate(((-160, 18), (-120, 15), (-60, 15), (-20, 18), (-95, 12),
                                                (175, 14), (10, 13))):
            a = math.radians(angle + sway * (0.6 if index % 2 else 1))
            points = []
            for k in range(6):
                t = k / 5
                droop = t * t * 9
                points.append((top_x + math.cos(a) * length * t, top_y + math.sin(a) * length * t + droop))
            d.line(points, fill=leaf_dark, width=3)
            d.line(points, fill=leaf if index % 3 else leaf_light, width=1)
            for px, py in points[1:]:
                d.point((round(px), round(py) + 2), fill=leaf_dark)

    def _draw_fire(self, d, light):
        lay = self.layout
        x, y = lay.fire_x, lay.ground + 4
        for dx in (-4, -2, 0, 2, 4):
            d.point((x + dx, y + 1), fill=P.shade(P.ROCK_DARK, light))
        d.line([(x - 4, y), (x + 4, y - 1)], fill=P.shade(P.WOOD_DARK, light), width=2)
        d.line([(x - 4, y - 1), (x + 4, y)], fill=P.shade(P.WOOD, light), width=1)
        if not self.fire_lit or self.weather.rain > 0.7:
            return
        flicker = int(self.time * 8)
        for k, (color, h, w) in enumerate(((P.FIRE_OUTER, 7, 4), (P.FIRE_MID, 5, 3), (P.FIRE_CORE, 3, 1))):
            jitter = ((flicker * (k + 3)) % 3) - 1
            d.polygon([(x - w, y - 1), (x + w, y - 1), (x + jitter, y - 1 - h - (flicker + k) % 2)], fill=color)
        if flicker % 3 == 0:
            d.point((x + (flicker % 5) - 2, y - 9 - flicker % 4), fill=P.FIRE_MID)

    def _draw_raft(self, d, light):
        lay = self.layout
        stage = min(6, self.raft_stage)
        x0, y = lay.raft_x - 8 + int(self.raft_dx), lay.ground + 7
        if self.raft_broken > 0.01:
            for i in range(5):
                px = x0 + i * 5 + (i % 2) * 3
                d.line([(px, y + (i % 3) - 1), (px + 4, y + (i % 2))], fill=P.shade(P.WOOD, light), width=2)
            return
        for i in range(min(5, stage)):
            d.line([(x0, y - i * 2), (x0 + 16, y - i * 2)], fill=P.shade(P.WOOD if i % 2 else P.WOOD_DARK, light), width=2)
        if stage >= 6:
            d.line([(x0 + 8, y - 8), (x0 + 8, y - 20)], fill=P.shade(P.WOOD_DARK, light))
            d.polygon([(x0 + 9, y - 20), (x0 + 15, y - 12), (x0 + 9, y - 12)], fill=P.shade(P.SAIL, light))

    def draw_weather(self, img, d):
        w = self.weather
        lay = self.layout
        if w.rain > 0.05:
            count = int(len(self.rain_drops) * w.rain)
            slant = 2 + int(w.wind * 3)
            color = P.shade(P.RAIN, max(0.5, self.light))
            fall = (self.time * 160) % lay.h
            for i in range(count):
                x0, y0 = self.rain_drops[i]
                x = (x0 + self.time * 30 * w.wind) % lay.w
                y = (y0 + fall) % lay.h
                d.line([(x, y), (x + slant * 0.5, y + 3)], fill=color)
        if w.fog > 0.05:
            fog = Image.new("RGBA", img.size, (200, 206, 214, int(110 * w.fog)))
            img.alpha_composite(fog)
        if w.flash > 0.5:
            flash = Image.new("RGBA", img.size, (255, 255, 255, int(150 * (w.flash - 0.5) * 2)))
            img.alpha_composite(flash)
        if self.heat > 0.3:
            t = int(self.time * 2)          # heat shimmer at 2 Hz
            for k in range(6):
                x = (k * 37 + t * 3) % lay.w
                y = lay.horizon - 4 - (k * 5) % 12
                d.point((x, y), fill=P.mix(self.sea_color, (255, 255, 255), 0.4))
