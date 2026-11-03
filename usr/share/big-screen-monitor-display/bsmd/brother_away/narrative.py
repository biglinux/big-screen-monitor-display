"""Narrative Event Engine.

Stories and idle activities are Python generators that yield small
commands (walk, play a clip, say a line, wait...). The engine advances them
with the frame delta time, so nothing ever blocks the render thread, and a
story can be interrupted at any point (``generator.close()`` runs its
``finally`` clean-up).

States: IDLE -> PREPARATION -> EVENT -> REACTION -> RESOLUTION -> COOLDOWN.
Selection uses weights, cooldowns, time of day, weather, prerequisites,
recent history and persisted progress (e.g. the raft).
"""

import json
import logging
import random
import time
from datetime import date

from . import poses
from .character import DEFAULT_POSE, Puppet

log = logging.getLogger("bsmd.brother_away")

IDLE, PREPARATION, EVENT, REACTION, RESOLUTION, COOLDOWN = (
    "idle", "preparation", "event", "reaction", "resolution", "cooldown")
STORY_STATES = (PREPARATION, EVENT, REACTION, RESOLUTION)
STATE_VERSION = 1


class Hero:
    WALK_SPEED = 16.0
    RUN_SPEED = 42.0

    def __init__(self, x, y):
        self.x, self.y = float(x), float(y)
        self.facing = 1
        self.puppet = Puppet()
        self.clip = poses.idle
        self.clip_t = 0.0
        self.extra = {}
        self.expr = None
        self.speech = None          # (text, remaining seconds)
        self.emote = None           # (symbol, remaining seconds)
        self.pose = dict(DEFAULT_POSE)
        self.offset_y = 0.0         # climbing / jumping

    def play(self, clip, expr=None, **extra):
        clip = poses.CLIPS[clip] if isinstance(clip, str) else clip
        if clip is not self.clip:
            self.clip_t = 0.0
        self.clip = clip
        self.expr = expr
        self.extra = extra

    def say(self, text, seconds):
        self.speech = (text, seconds) if text else None

    def update(self, dt, wind):
        self.clip_t += dt
        pose = dict(DEFAULT_POSE)
        pose.update(self.clip(self.clip_t))
        pose.update(self.extra)
        if self.expr:
            pose["expr"] = self.expr
        if self.speech and pose.get("expr") not in ("talk",):
            pose["mouth"] = 1.0 if int(self.clip_t * 8) % 3 else 0.0
        self.pose = pose
        if self.speech:
            text, remaining = self.speech
            self.speech = (text, remaining - dt) if remaining - dt > 0 else None
        if self.emote:
            symbol, remaining = self.emote
            self.emote = (symbol, remaining - dt) if remaining - dt > 0 else None
        self.puppet.update(dt, self.x, self.y + self.offset_y, self.facing, pose, wind)


# ------------------------------------------------------------- commands -----

class Command:
    done = False

    def start(self, engine):
        pass

    def update(self, engine, dt):
        self.done = True


class Walk(Command):
    """Walk (or run/swim) to ``x``; ``y`` optionally changes along the way."""

    def __init__(self, x, run=False, clip=None, expr=None, speed=None, y=None):
        self.target, self.run, self.clip, self.expr, self.speed = x, run, clip, expr, speed
        self.y = y

    def start(self, engine):
        hero = engine.hero
        self.start_x, self.start_y = hero.x, hero.y
        lay = engine.world.layout
        self.target = max(lay.walk_min - 30, min(lay.w + 30, self.target))
        if abs(self.target - hero.x) < 1:
            if self.y is not None:
                hero.y = self.y
            self.done = True
            return
        hero.facing = 1 if self.target > hero.x else -1
        hero.play(self.clip or ("run" if self.run else "walk"), self.expr)

    def update(self, engine, dt):
        hero = engine.hero
        speed = self.speed or (hero.RUN_SPEED if self.run else hero.WALK_SPEED)
        delta = self.target - hero.x
        step = speed * dt
        if abs(delta) <= step:
            hero.x = self.target
            if self.y is not None:
                hero.y = self.y
            hero.play("idle")
            self.done = True
        else:
            hero.x += step if delta > 0 else -step
            if self.y is not None:
                span = self.target - self.start_x
                progress = (hero.x - self.start_x) / span if span else 1.0
                hero.y = self.start_y + (self.y - self.start_y) * progress


class Do(Command):
    def __init__(self, clip, seconds, expr=None, face=None, **extra):
        self.clip, self.seconds, self.expr, self.face, self.extra = clip, seconds, expr, face, extra

    def start(self, engine):
        if self.face is not None:
            engine.hero.facing = self.face
        engine.hero.play(self.clip, self.expr, **self.extra)
        self.left = self.seconds

    def update(self, engine, dt):
        self.left -= dt
        if self.left <= 0:
            self.done = True


class Say(Command):
    def __init__(self, context, seconds=None, clip="talk", expr=None, face=None, text=None, **extra):
        self.context, self.seconds, self.clip, self.expr = context, seconds, clip, expr
        self.face, self.text, self.extra = face, text, extra

    def start(self, engine):
        text = self.text or engine.line(self.context)
        if self.face is not None:
            engine.hero.facing = self.face
        if not text:
            # Dialogue disabled for this context (e.g. catchphrases off).
            engine.hero.play(self.clip, self.expr, **self.extra)
            self.left = 1.0
            return
        seconds = self.seconds or max(2.2, min(6.5, len(text) * 0.075))
        engine.hero.play(self.clip, self.expr, **self.extra)
        if engine.show_subtitles:
            engine.hero.say(text, seconds)
        engine.events.append(("say", self.context))
        self.left = seconds

    def update(self, engine, dt):
        self.left -= dt
        if self.left <= 0:
            engine.hero.speech = None
            self.done = True


class Wait(Command):
    def __init__(self, seconds):
        self.left = seconds

    def update(self, engine, dt):
        self.left -= dt
        self.done = self.left <= 0


class Until(Command):
    def __init__(self, predicate, timeout=10.0):
        self.predicate, self.left = predicate, timeout

    def update(self, engine, dt):
        self.left -= dt
        self.done = self.left <= 0 or bool(self.predicate())


class Call(Command):
    def __init__(self, func):
        self.func = func

    def start(self, engine):
        self.func()
        self.done = True


class Phase(Command):
    def __init__(self, state):
        self.state = state

    def start(self, engine):
        engine.state = self.state
        self.done = True


class Emote(Command):
    def __init__(self, symbol, seconds=1.5):
        self.symbol, self.seconds = symbol, seconds

    def start(self, engine):
        engine.hero.emote = (self.symbol, self.seconds)
        self.done = True


# ------------------------------------------------------------ persistence ---

class Memory:
    """Small persisted state: raft, souvenirs, story counters.

    Saved atomically, at most every ``SAVE_EVERY`` seconds and on close -
    never per frame.
    """

    SAVE_EVERY = 600.0

    def __init__(self, path):
        self.path = path
        self.data = {"version": STATE_VERSION, "raft": 0, "items": [], "stories": {},
                     "first_day": date.today().isoformat(), "awaaay": 0}
        self.dirty = False
        self.last_save = time.monotonic()
        self.load()

    def load(self):
        if not self.path:
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                for key in ("raft", "awaaay"):
                    if isinstance(data.get(key), int):
                        self.data[key] = max(0, min(10_000, data[key]))
                if isinstance(data.get("items"), list):
                    self.data["items"] = [str(i)[:20] for i in data["items"]][-12:]
                if isinstance(data.get("stories"), dict):
                    self.data["stories"] = {str(k)[:40]: int(v) for k, v in data["stories"].items()
                                            if isinstance(v, int)}
                if isinstance(data.get("first_day"), str):
                    self.data["first_day"] = data["first_day"][:10]
        except (OSError, ValueError, TypeError):
            pass

    def mark(self):
        self.dirty = True

    def maybe_save(self, force=False):
        if not self.path or not self.dirty:
            return
        if not force and time.monotonic() - self.last_save < self.SAVE_EVERY:
            return
        try:
            from ..settings import atomic_write_json
            atomic_write_json(self.path, self.data, mode=0o600)
            self.dirty = False
            self.last_save = time.monotonic()
        except OSError as error:
            log.debug("cannot save Brother Away state: %s", error)
            self.path = None


# --------------------------------------------------------------- engine -----

class Story:
    def __init__(self, id, func, weight=1.0, rarity="common", cooldown=600.0, when=None, kind="story"):
        self.id, self.func, self.weight, self.rarity = id, func, weight, rarity
        self.cooldown, self.when, self.kind = cooldown, when, kind


RARITY_FACTOR = {"common": 1.0, "uncommon": 0.45, "rare": 0.14}
FREQUENCY = {"low": (0.12, 420.0), "normal": (0.28, 180.0), "high": (0.5, 75.0)}


class Engine:
    def __init__(self, world, hero, dialogue, memory, rng=None, stories=(), activities=()):
        self.world, self.hero, self.dialogue, self.memory = world, hero, dialogue, memory
        self.rng = rng or random.Random()
        self.stories = list(stories)
        self.activities = list(activities)
        self.state = IDLE
        self.current = None           # (Story, generator)
        self.command = None
        self.time = 0.0
        self.last_run = {}
        self.history = []
        self.last_story_end = -1e9
        self.cooldown_until = 0.0
        self.settings = {}
        self.events = []
        self.forced = None
        self.reaction = None

    @property
    def show_subtitles(self):
        return self.settings.get("ba_subtitles", True)

    def line(self, context):
        return self.dialogue.line(context, self.settings)

    # -- selection
    def _eligible(self, items):
        out = []
        for item in items:
            last = self.last_run.get(item.id, -1e9)
            if self.time - last < item.cooldown:
                continue
            if item.when and not item.when(self):
                continue
            weight = item.weight * RARITY_FACTOR.get(item.rarity, 1.0)
            if item.id in self.history[-3:]:
                weight *= 0.15
            if weight > 0:
                out.append((item, weight))
        return out

    def _pick(self, weighted):
        total = sum(w for _, w in weighted)
        roll = self.rng.uniform(0, total)
        for item, weight in weighted:
            roll -= weight
            if roll <= 0:
                return item
        return weighted[-1][0]

    def choose(self):
        if self.forced:
            story = next((s for s in self.stories + self.activities if s.id == self.forced), None)
            self.forced = None
            if story:
                return story
        chance, gap = FREQUENCY.get(self.settings.get("ba_event_frequency", "normal"), FREQUENCY["normal"])
        if self.reaction:
            reaction, self.reaction = self.reaction, None
            item = next((a for a in self.activities if a.id == reaction), None)
            if item:
                return item
        if self.time - self.last_story_end > gap and self.rng.random() < chance:
            stories = self._eligible(self.stories)
            if stories:
                return self._pick(stories)
        activities = self._eligible(self.activities)
        return self._pick(activities) if activities else None

    def start(self, item):
        self.current = (item, item.func(self))
        self.command = None
        self.last_run[item.id] = self.time
        self.history = (self.history + [item.id])[-10:]
        self.state = PREPARATION if item.kind == "story" else IDLE
        log.debug("brother away: start %s", item.id)

    def interrupt(self):
        if self.current:
            try:
                self.current[1].close()
            except Exception:  # noqa: BLE001 - clean-up must not break rendering
                log.exception("story clean-up failed")
        self.current = None
        self.command = None
        self.hero.speech = None
        self.hero.play("idle")
        self.hero.offset_y = 0
        self.state = IDLE

    def update(self, dt, settings):
        self.settings = settings
        self.time += dt
        if self.current is None:
            if self.state == COOLDOWN and self.time < self.cooldown_until:
                pass
            else:
                self.state = IDLE
                item = self.choose()
                if item:
                    self.start(item)
        steps = 0
        while self.current is not None and steps < 8:
            steps += 1
            if self.command is None or self.command.done:
                try:
                    self.command = next(self.current[1])
                    self.command.start(self)
                except StopIteration:
                    self._finished()
                    break
                except Exception:  # noqa: BLE001
                    log.exception("story %s failed", self.current[0].id)
                    self.interrupt()
                    break
                if self.command.done:
                    continue
            self.command.update(self, dt)
            break
        self.memory.maybe_save()

    def _finished(self):
        item = self.current[0]
        if item.kind == "story":
            counts = self.memory.data["stories"]
            counts[item.id] = counts.get(item.id, 0) + 1
            self.memory.mark()
            self.last_story_end = self.time
            self.state = COOLDOWN
            self.cooldown_until = self.time + 20.0
        else:
            self.state = IDLE
        self.current = None
        self.command = None
        self.hero.offset_y = 0
