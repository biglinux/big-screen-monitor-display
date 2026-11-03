"""Stories and idle activities for Brother Away.

Each function receives the engine and yields narrative commands. Main
stories follow preparation -> event -> reaction -> resolution. ``finally``
blocks restore the world when a story is interrupted.
"""

from . import world as W
from .narrative import (EVENT, PREPARATION, REACTION, RESOLUTION, Call, Do, Emote, Phase, Say, Story,
                        Until, Wait, Walk)

RAFT_DONE = 6


def _night(e):
    return e.world.hour >= 21.5 or e.world.hour < 4.8


def _day(e):
    return 6.5 <= e.world.hour < 18.0


def _late_night(e):
    return e.world.hour >= 23.0 or e.world.hour < 5.0


def _dry(e):
    return e.world.weather.rain < 0.3


def _float(e, text, x, y, seconds=1.5, color=(255, 255, 255)):
    e.world.floaters.append([text, x, y, seconds, color])


def _head_x(e):
    hero = e.hero
    return hero.x - 14 * hero.facing if hero.pose.get("lying") else hero.x


def _spot_under_crown(e):
    """Hero x so that, lying with facing -1, his head is under the crown."""
    top_x, _top_y, _h, _lean = e.world.palm_crown()
    return top_x - 14


# ------------------------------------------------------------ 5 main stories

def coconut_tree(e):
    """1. The rebellious palm tree."""
    hero, world, lay = e.hero, e.world, e.world.layout
    try:
        yield Phase(PREPARATION)
        yield Walk(_spot_under_crown(e))
        hero.facing = -1
        yield Do("sleep", 4.0)
        _float(e, "z", hero.x + 16, hero.y - 12, 1.2)
        yield Phase(EVENT)
        top_x, top_y, _h, _l = world.palm_crown()
        first = W.FallingCoconut(top_x - 7, top_y + 3, lay.ground + 1)
        world.actors.append(first)
        world.coconuts = max(0, world.coconuts - 1)
        yield Until(lambda: first.landed, 4)
        yield Do("sleep", 0.8, expr="suspicious")
        yield Emote("?", 1.4)
        yield Say("coconut_first", clip="sleep", expr="suspicious")
        yield Do("sleep", 3.0)
        top_x, top_y, _h, _l = world.palm_crown()
        second = W.FallingCoconut(_head_x(e), top_y + 3, lay.ground + 1, hit=hero.y - 6)
        world.actors.append(second)
        yield Until(lambda: second.hit_done, 4)
        yield Phase(REACTION)
        yield Emote("!!", 1.2)
        yield Do("wake_scared", 0.7)
        yield Do("get_up", 0.6)
        hero.facing = -1 if lay.palm_x < hero.x else 1
        yield Do("cross_arms", 1.4, expr="indignant")
        yield Say("coconut_hit", clip="complain")
        yield Call(lambda: setattr(world, "palm_shake", 1.0))
        yield Do("cross_arms", 1.2, expr="suspicious")
        yield Say("palm_argue", clip="talk", expr="indignant")
        yield Call(lambda: setattr(world, "palm_shake", 1.0))
        top_x, top_y, _h, _l = world.palm_crown()
        third = W.FallingCoconut(hero.x, top_y + 3, lay.ground + 1, hit=hero.y - 30)
        world.actors.append(third)
        yield Until(lambda: third.hit_done, 4)
        yield Do("stunned", 1.8)
        yield Phase(RESOLUTION)
        yield Do("stunned", 1.3, expr="perplexed", glasses_down=2)   # stares at the viewer
        e.memory.data["awaaay"] += 1
        e.memory.mark()
        yield Say("awaaay", clip="shout", seconds=2.8)
        yield Do("idle", 1.0, expr="indignant")
    finally:
        world.palm_shake = 0.0


def shark(e):
    """2. The mocking shark."""
    hero, world, lay = e.hero, e.world, e.world.layout
    fin = None
    try:
        yield Phase(PREPARATION)
        yield Walk(lay.shore_x)
        yield Do("idle", 0.6, expr="happy")
        yield Walk(lay.sea_x, clip="swim", speed=8, y=lay.swim_y)
        hero.facing = lay.shore_dir
        yield Do("swim", 2.5)
        yield Phase(EVENT)
        fin = W.Shark(hero.x + 30 * lay.shore_dir, lay.swim_y + 1, speed=7)
        fin.target = hero.x + 9 * lay.shore_dir
        hero.facing = -lay.shore_dir
        world.actors.append(fin)
        yield Until(lambda: abs(fin.x - fin.target) < 1, 6)
        yield Do("swim", 1.5, reflection_fin=True)
        yield Say("shark_reflection", clip="swim", reflection_fin=True, expr="suspicious")
        yield Do("swim", 0.8, expr="suspicious", glasses_down=1)
        hero.facing = lay.shore_dir
        yield Do("swim", 1.0, expr="scared")
        yield Phase(REACTION)
        yield Emote("!!!", 1.0)
        yield Say("shark_run", clip="run_scared", seconds=1.0)
        yield Walk(lay.island_cx, run=True, clip="run_scared", y=lay.ground)
        fin.laugh = 3.0
        _float(e, "HA HA", fin.x, fin.y - 12, 2.5, (230, 240, 255))
        e.events.append(("fx", "laugh"))
        hero.facing = lay.shore_dir
        yield Do("idle", 0.8, expr="indignant")
        yield Phase(RESOLUTION)
        yield Say("shark_argue", clip="complain")
        fin.target = lay.offscreen_sea
        yield Say("shark_argue", clip="talk", expr="indignant")
        yield Do("cross_arms", 1.5, expr="suspicious")
    finally:
        if fin is not None:
            fin.done = True


def raft(e):
    """3. The impossible raft (needs the raft built over several sessions)."""
    hero, world, lay = e.hero, e.world, e.world.layout
    wave = None
    try:
        yield Phase(PREPARATION)
        yield Walk(lay.raft_x + 22)
        hero.facing = lay.shore_dir
        yield Do("build", 2.5)
        world.raft_stage = RAFT_DONE
        yield Say("raft_done", clip="celebrate")
        yield Do("dance", 3.0)
        yield Phase(EVENT)
        yield Walk(lay.raft_x + 20)
        hero.facing = lay.shore_dir
        yield Do("push", 2.0)
        for _ in range(10):
            world.raft_dx += 2 * lay.shore_dir
            yield Wait(0.12)
        wave = W.BigWave(-10, lay.raft_x - 14, lay.ground + 6, speed=30)
        world.actors.append(wave)
        yield Until(lambda: wave.arrived, 8)
        world.raft_dx = 0
        world.raft_stage = 0
        world.raft_broken = 1.0
        e.memory.data["raft"] = 0
        e.memory.mark()
        for k in range(10):
            world.actors.append(W.Particle(lay.raft_x + k - 5, lay.ground + 4, (k - 5) * 6, -30 - k * 3,
                                           W.P.FOAM, 0.8, gravity=90))
        yield Phase(REACTION)
        yield Do("stunned", 2.2)
        yield Do("stunned", 1.5, glasses_down=2)
        yield Say("perplexed", clip="shrug", seconds=2.6)
        yield Phase(RESOLUTION)
        yield Say("raft_broken", clip="complain")
    finally:
        world.raft_dx = 0
        if wave is not None:
            wave.done = True


def ufo(e):
    """4. The extraterrestrial encounter (late night only)."""
    hero, world, lay = e.hero, e.world, e.world.layout
    ship = None
    try:
        yield Phase(PREPARATION)
        yield Walk(lay.island_cx - 6)
        hero.facing = 1
        yield Do("sleep", 3.5)
        yield Phase(EVENT)
        ship = W.UFO(lay.w + 20, -10, hero.x - 6, lay.horizon - 26)
        world.actors.append(ship)
        yield Wait(2.5)
        ship.beam = 1.0
        yield Wait(1.0)
        yield Phase(REACTION)
        yield Emote("!!", 1.0)
        yield Do("wake_scared", 0.8)
        yield Say("ufo_wake", clip="complain")
        yield Do("idle", 0.6, expr="indignant")
        yield Say("ufo_speech", clip="speech_beat", seconds=4.5)
        yield Say("ufo_speech", clip="speech_beat", seconds=4.5)
        ship.beam = 0.0
        _float(e, "...", ship.x, ship.y - 10, 1.5, (170, 255, 200))
        yield Wait(1.2)
        ship.tx, ship.ty = -40, -30
        yield Wait(1.6)
        yield Phase(RESOLUTION)
        yield Say("ufo_win", clip="celebrate")
        yield Do("dance", 2.5)
    finally:
        if ship is not None:
            ship.done = True


def philosopher(e):
    """5. The philosopher palm tree."""
    hero, world, lay = e.hero, e.world, e.world.layout
    try:
        yield Phase(PREPARATION)
        yield Walk(lay.palm_x - 26)
        hero.facing = -1
        yield Do("contemplate", 3.5)
        yield Phase(EVENT)
        yield Say("philosophy", clip="contemplate", seconds=4.5)
        yield Do("contemplate", 2.0)
        yield Say("philosophy", clip="contemplate", seconds=4.5)
        yield Phase(REACTION)
        hero.facing = 1
        yield Say("philosophy_ask", clip="sit", expr="talk", seconds=3.5)
        for k in range(8):                      # the wind bends the palm
            world.palm_lean = -k * 1.2
            yield Wait(0.1)
        yield Do("sit", 1.0, expr="happy")
        yield Phase(RESOLUTION)
        yield Say("philosophy_agree", clip="sit", expr="happy")
        for k in range(8):
            world.palm_lean = -(8 - k) * 1.2
            yield Wait(0.12)
        yield Do("sit", 1.5, expr="happy")
    finally:
        world.palm_lean = 0.0


# ------------------------------------------------------------ extra stories

def crab_glasses(e):
    hero, world, lay = e.hero, e.world, e.world.layout
    crab = None
    try:
        yield Phase(PREPARATION)
        yield Walk(lay.island_cx - 6)
        hero.facing = lay.shore_dir
        yield Do("sit", 3.0, expr="sleep")
        yield Phase(EVENT)
        crab = W.Crab(lay.island_left - 6, lay.ground + 1, hero.x - 6, speed=10)
        world.actors.append(crab)
        yield Until(lambda: crab.arrived, 10)
        crab.carry = "glasses"
        crab.target = lay.island_left - 2
        crab.speed = 16
        yield Phase(REACTION)
        yield Do("sit", 0.8, no_glasses=True, expr="perplexed")
        yield Say("no_glasses", clip="sit", no_glasses=True, expr="confused")
        yield Emote("!", 0.8)
        yield Walk(lay.shore_x - 6, run=True, clip="run", expr="furious")
        yield Say("crab", clip="complain", no_glasses=True)
        crab.carry = None
        yield Phase(RESOLUTION)
        yield Do("adjust_glasses", 1.0)
        yield Say("crab", clip="cross_arms", expr="suspicious")
    finally:
        if crab is not None:
            crab.target = lay.offscreen_sea
            crab.carry = None


def gull_lunch(e):
    hero, world, lay = e.hero, e.world, e.world.layout
    gull = None
    try:
        yield Phase(PREPARATION)
        yield Walk(lay.shore_x)
        hero.facing = lay.shore_dir
        yield Do("fish", 5.0)
        world.actors.append(W.JumpingFish(lay.shore_x - 16, lay.ground + 4, 1))
        yield Do("fish_pull", 1.2)
        yield Say("fish_caught", clip="idle", prop="fish", arm_f=(100, 40), expr="happy")
        yield Phase(EVENT)
        gull = W.Gull(lay.w + 10, lay.horizon - 20, hero.x - 4, hero.y - 22, speed=55)
        world.actors.append(gull)
        yield Until(lambda: gull.arrived, 6)
        gull.carry = "fish"
        gull.tx, gull.ty = -20, lay.horizon - 30
        yield Phase(REACTION)
        yield Do("stunned", 1.0)
        yield Say("gull", clip="complain")
        yield Phase(RESOLUTION)
        yield Do("shrug", 1.2)
    finally:
        if gull is not None:
            gull.done = True


def message_bottle(e):
    world, lay = e.world, e.world.layout
    bottle = None
    try:
        yield Phase(PREPARATION)
        bottle = W.FloatingItem("bottle", -8, lay.ground + 5, lay.island_left + 2, speed=7)
        world.actors.append(bottle)
        yield Until(lambda: bottle.arrived, 30)
        yield Phase(EVENT)
        yield Emote("!", 1.0)
        yield Walk(lay.shore_x)
        bottle.done = True
        yield Say("bottle_found", clip="idle", prop="bottle", arm_f=(90, 30), expr="happy")
        yield Do("read", 3.0)
        yield Phase(REACTION)
        yield Say("bottle_read", clip="read")
        yield Phase(RESOLUTION)
        yield Do("shrug", 1.2)
        items = e.memory.data["items"]
        items.append("bottle")
        e.memory.data["items"] = items[-12:]
        world.items = list(e.memory.data["items"])
        e.memory.mark()
    finally:
        if bottle is not None:
            bottle.done = True


def ship_asleep(e):
    hero, world, lay = e.hero, e.world, e.world.layout
    vessel = None
    try:
        yield Phase(PREPARATION)
        yield Walk(lay.island_cx - 4)
        hero.facing = -1
        yield Do("sleep", 2.0)
        yield Phase(EVENT)
        vessel = W.Ship(-14, lay.horizon + 2, 6.0)
        world.actors.append(vessel)
        while not vessel.done:
            _float(e, "z", hero.x + 16, hero.y - 12, 1.0)
            yield Do("sleep", 1.6)
        yield Phase(REACTION)
        yield Do("wake_scared", 0.6)
        yield Do("idle", 0.8, expr="suspicious")
        yield Phase(RESOLUTION)
        yield Say("ship_missed", clip="scratch_head")
    finally:
        if vessel is not None:
            vessel.done = True


def mermaid(e):
    hero, world, lay = e.hero, e.world, e.world.layout
    siren = None
    try:
        yield Phase(PREPARATION)
        siren = W.Mermaid(max(8, lay.island_left - 14), lay.ground + 5)
        world.actors.append(siren)
        yield Wait(2.0)
        yield Phase(EVENT)
        yield Emote("?", 1.0)
        yield Walk(lay.shore_x)
        hero.facing = lay.shore_dir
        yield Say("mermaid_call", clip="complain")
        yield Say("coconut_hit", clip="talk", expr="indignant")
        yield Phase(REACTION)
        siren.leaving = True
        yield Wait(1.5)
        yield Phase(RESOLUTION)
        yield Say("mermaid_gone", clip="shrug")
    finally:
        if siren is not None:
            siren.leaving = True


def treasure(e):
    hero, world, lay = e.hero, e.world, e.world.layout
    yield Phase(PREPARATION)
    yield Walk(lay.rocks_x + 10)
    hero.facing = -1
    yield Do("build", 4.0, prop=None)
    yield Phase(EVENT)
    for k in range(8):
        world.actors.append(W.Particle(lay.rocks_x - 4, lay.ground + 3, (k - 4) * 8, -25, W.P.SAND_SHADE,
                                       0.6, gravity=80))
    yield Emote("!!", 1.0)
    yield Do("stunned", 1.4, expr="perplexed", glasses_down=2)
    yield Phase(REACTION)
    yield Say("treasure", clip="celebrate")
    yield Phase(RESOLUTION)
    items = e.memory.data["items"]
    if "chest" not in items:
        items.append("chest")
    e.memory.data["items"] = items[-12:]
    world.items = list(e.memory.data["items"])
    e.memory.mark()
    yield Do("dance", 2.0)


def stars_night(e):
    hero, lay = e.hero, e.world.layout
    yield Phase(PREPARATION)
    yield Walk(lay.fire_x - 10)
    hero.facing = 1
    yield Do("contemplate", 3.0)
    yield Phase(EVENT)
    yield Do("sit", 1.0, arm_f=(150, 0), hand_f="point")
    yield Phase(REACTION)
    yield Say("night", clip="contemplate")
    yield Phase(RESOLUTION)
    yield Do("contemplate", 3.0, expr="sad")


def rain_complaint(e):
    lay = e.world.layout
    yield Phase(PREPARATION)
    yield Walk(lay.palm_x - 6)
    yield Phase(EVENT)
    yield Do("idle", 1.0, expr="sad")
    yield Phase(REACTION)
    yield Say("storm" if e.world.weather.state == "storm" else "rain", clip="complain")
    yield Phase(RESOLUTION)
    yield Do("cross_arms", 2.0, expr="sad")


def fish_bait(e):
    hero, world, lay = e.hero, e.world, e.world.layout
    yield Phase(PREPARATION)
    yield Walk(lay.shore_x)
    hero.facing = lay.shore_dir
    yield Say("fish_wait", clip="fish")
    yield Do("fish", 4.0)
    yield Phase(EVENT)
    world.actors.append(W.JumpingFish(lay.shore_x - 20, lay.ground + 4, 1))
    yield Do("fish_pull", 1.0)
    yield Phase(REACTION)
    yield Say("fish_lost", clip="fish", expr="indignant")
    yield Phase(RESOLUTION)
    yield Do("fish", 2.0, expr="suspicious")


# ------------------------------------------------------------ idle activities

def stroll(e):
    lay = e.world.layout
    target = e.rng.uniform(lay.walk_min, lay.walk_max)
    yield Walk(target)
    micro = e.rng.choice(("idle", "adjust_glasses", "scratch_head", "shake_dreads", "idle"))
    yield Do(micro, e.rng.uniform(1.2, 2.5))
    yield Do("idle", e.rng.uniform(2.0, 5.0))


def sit_horizon(e):
    lay = e.world.layout
    yield Walk(e.rng.uniform(lay.island_cx - 10, lay.walk_max - 10))
    e.hero.facing = 1
    yield Do("sit", e.rng.uniform(6, 12))
    if e.rng.random() < 0.3:
        yield Say("idle", clip="sit")
    yield Do("contemplate", e.rng.uniform(4, 8))


def nap(e):
    yield Walk(_spot_under_crown(e))
    e.hero.facing = -1
    for _ in range(e.rng.randint(4, 8)):
        _float(e, "z", e.hero.x + 16, e.hero.y - 12, 1.2)
        yield Do("sleep", 2.5)
    yield Do("get_up", 0.8)


def fishing(e):
    lay = e.world.layout
    yield Walk(lay.shore_x)
    e.hero.facing = lay.shore_dir
    yield Do("fish", e.rng.uniform(8, 16))
    if e.rng.random() < 0.5:
        e.world.actors.append(W.JumpingFish(lay.shore_x - 18, lay.ground + 4, 1))
        yield Do("fish_pull", 1.0)
        yield Say("fish_caught", clip="idle", prop="fish", arm_f=(100, 40), expr="happy")
    else:
        yield Do("fish", e.rng.uniform(5, 10))


def build_raft(e):
    lay = e.world.layout
    yield Walk(lay.raft_x + 22)
    e.hero.facing = lay.shore_dir
    yield Do("build", e.rng.uniform(5, 9))
    if e.settings.get("ba_story_continuity", True):
        e.memory.data["raft"] = min(RAFT_DONE, e.memory.data["raft"] + 1)
        e.memory.mark()
    e.world.raft_stage = e.memory.data["raft"]
    e.world.raft_broken = 0.0
    if e.rng.random() < 0.4:
        yield Say("raft_build", clip="idle", expr="happy")


def dance_break(e):
    yield Say("dance", clip="dance", seconds=2.0)
    yield Do("dance", e.rng.uniform(3, 6))


def palm_talk(e):
    lay = e.world.layout
    yield Walk(lay.palm_x - 14)
    e.hero.facing = 1
    yield Say("palm_talk", clip="talk")
    yield Do("idle", 2.0, expr="happy")


def swim(e):
    lay = e.world.layout
    yield Walk(lay.shore_x)
    yield Walk(lay.sea_x, clip="swim", speed=8, y=lay.swim_y)
    yield Do("swim", e.rng.uniform(4, 8))
    e.hero.facing = -lay.shore_dir
    yield Walk(lay.shore_x, clip="swim", speed=8, y=lay.ground)
    yield Do("shake_dreads", 1.5)


def climb_palm(e):
    hero, lay = e.hero, e.world.layout
    yield Walk(lay.palm_x - 3)
    hero.facing = 1
    for k in range(16):
        hero.offset_y = -k
        yield Do("climb", 0.25)
    yield Do("climb", 1.5, expr="happy")
    yield Do("fall", 0.4)
    for k in range(4):
        hero.offset_y = -15 + (k + 1) * 4
        yield Wait(0.05)
    hero.offset_y = 0
    yield Do("sit", 0.6, expr="perplexed")
    yield Do("get_up", 0.8)
    yield Say("coconut_hit", clip="complain")


def night_fire(e):
    lay = e.world.layout
    e.world.fire_lit = True
    yield Walk(lay.fire_x - 10)
    e.hero.facing = 1
    yield Do("sit", e.rng.uniform(10, 18))
    if e.rng.random() < 0.4:
        yield Say("night", clip="contemplate")


def morning_greeting(e):
    yield Say("morning", clip="celebrate", seconds=3.0)
    yield Do("shake_dreads", 1.5)


# Telemetry reactions (chosen by the theme when a sensor crosses a threshold)

def react_heat(e):
    yield Say("heat", clip="fan")
    yield Do("fan", 4.0)


def react_hot(e):
    yield Walk(e.world.layout.palm_x + 8)
    yield Say("hot_shade", clip="fan")
    yield Do("sit", 6.0, expr="sad")


def react_ram(e):
    yield Do("scratch_head", 1.5)
    yield Say("ram", clip="shrug")


def react_disk(e):
    yield Walk(e.world.layout.rocks_x - 18)
    e.hero.facing = -1
    yield Say("disk", clip="push", seconds=3.0)


def react_gpu(e):
    e.hero.facing = -1
    yield Do("point", 1.0)
    yield Say("gpu", clip="point")


def build_registry():
    stories = [
        Story("coconut_tree", coconut_tree, 1.2, "common", 900, when=_dry),
        Story("philosopher", philosopher, 1.0, "common", 900),
        Story("shark", shark, 1.0, "uncommon", 1500, when=lambda e: _day(e) and _dry(e)),
        Story("raft", raft, 3.0, "uncommon", 1800,
              when=lambda e: e.memory.data["raft"] >= RAFT_DONE and _dry(e)),
        Story("ufo", ufo, 2.5, "rare", 3600, when=_night),
        Story("crab_glasses", crab_glasses, 1.0, "uncommon", 1500, when=_dry),
        Story("gull_lunch", gull_lunch, 1.0, "uncommon", 1500, when=lambda e: _day(e) and _dry(e)),
        Story("message_bottle", message_bottle, 0.8, "uncommon", 2400),
        Story("ship_asleep", ship_asleep, 1.0, "rare", 3600, when=lambda e: _day(e)),
        Story("mermaid", mermaid, 1.0, "rare", 3600, when=_dry),
        Story("treasure", treasure, 1.0, "rare", 5400, when=lambda e: "chest" not in e.memory.data["items"]),
        Story("stars_night", stars_night, 1.5, "common", 1800, when=lambda e: _night(e) and _dry(e)),
        Story("rain_complaint", rain_complaint, 3.0, "common", 900, when=lambda e: e.world.weather.rain > 0.4),
        Story("fish_bait", fish_bait, 0.8, "uncommon", 1800, when=_dry),
    ]
    activities = [
        Story("stroll", stroll, 3.0, cooldown=0, kind="activity"),
        Story("sit_horizon", sit_horizon, 2.0, cooldown=60, kind="activity"),
        Story("nap", nap, 1.0, cooldown=300, kind="activity",
              when=lambda e: not (8 < e.world.hour < 12) or e.world.weather.rain < 0.3),
        Story("fishing", fishing, 1.5, cooldown=180, kind="activity", when=_dry),
        Story("build_raft", build_raft, 1.6, cooldown=240, kind="activity",
              when=lambda e: _dry(e) and e.memory.data["raft"] < RAFT_DONE),
        Story("dance_break", dance_break, 0.6, cooldown=600, kind="activity"),
        Story("palm_talk", palm_talk, 0.7, cooldown=600, kind="activity"),
        Story("swim", swim, 0.8, cooldown=600, kind="activity", when=lambda e: _day(e) and _dry(e)),
        Story("climb_palm", climb_palm, 0.5, cooldown=900, kind="activity", when=_dry),
        Story("night_fire", night_fire, 3.0, cooldown=120, kind="activity",
              when=lambda e: (e.world.hour >= 18.5 or e.world.hour < 5.5) and _dry(e)),
        Story("late_nap", nap, 5.0, cooldown=60, kind="activity", when=_late_night),
        Story("morning_greeting", morning_greeting, 50.0, cooldown=6 * 3600, kind="activity",
              when=lambda e: 6.0 <= e.world.hour < 9.0),
        Story("react_heat", react_heat, 0.0, cooldown=600, kind="activity"),
        Story("react_hot", react_hot, 0.0, cooldown=600, kind="activity"),
        Story("react_ram", react_ram, 0.0, cooldown=900, kind="activity"),
        Story("react_disk", react_disk, 0.0, cooldown=1800, kind="activity"),
        Story("react_gpu", react_gpu, 0.0, cooldown=900, kind="activity"),
    ]
    return stories, activities


MAIN_STORIES = ("coconut_tree", "shark", "raft", "ufo", "philosopher")
