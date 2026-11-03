"""Animation clips: functions of local time ``t`` (seconds) returning pose
overrides. Time is quantised ("animating on twos", 8 drawings per second)
so limbs snap between strong poses instead of sliding like tweened vectors.
"""

import math

STEP = 1 / 8


def q(t, step=STEP):
    return math.floor(t / step) * step


def _wave(t, speed):
    return math.sin(q(t) * speed)


def idle(t):
    breath = _wave(t, 2.2)
    return {"bob": 0.6 * breath, "arm_f": (8 + breath * 2, 10), "arm_b": (-8 - breath * 2, 10)}


def walk(t):
    phase = q(t, 1 / 10) * 9
    swing = math.sin(phase)
    return {"leg_f": (26 * swing, max(0, -swing) * 34), "leg_b": (-26 * swing, max(0, swing) * 34),
            "arm_f": (-24 * swing, 18), "arm_b": (24 * swing, 18), "bob": -abs(math.cos(phase)) * 1.2,
            "lean": 4}


def run(t):
    phase = q(t, 1 / 12) * 14
    swing = math.sin(phase)
    contact = abs(math.cos(phase))
    return {"leg_f": (45 * swing, max(0, -swing) * 70 + 10), "leg_b": (-45 * swing, max(0, swing) * 70 + 10),
            "arm_f": (-50 * swing + 20, 90), "arm_b": (50 * swing + 20, 90), "bob": -contact * 2.5,
            "lean": 14, "squash": 1.0 + (0.08 if contact > 0.9 else -0.04)}


def run_scared(t):
    pose = run(t)
    pose.update({"arm_f": (160 + 10 * math.sin(q(t) * 30), 10), "arm_b": (-160, -10), "fright": 1.0,
                 "expr": "scared"})
    return pose


def sit(t):
    breath = _wave(t, 1.8)
    return {"hip_drop": 11, "leg_f": (88, 4), "leg_b": (84, 10), "arm_b": (-35, -10),
            "arm_f": (25, 30), "bob": 0.4 * breath, "lean": -4}


def contemplate(t):
    pose = sit(t)
    pose.update({"arm_f": (40, 120), "head_tilt": 5, "expr": "thoughtful"})
    return pose


def point(t):
    return {"arm_f": (95, 0), "hand_f": "point", "lean": 3, "bob": 0.5 * _wave(t, 2)}


def point_up(t):
    return {"arm_f": (170, 0), "hand_f": "point", "lean": -3}


def cross_arms(t):
    return {"arms_crossed": True, "bob": 0.4 * _wave(t, 1.5), "lean": -3}


def scratch_head(t):
    scratch = 1 if int(t * 8) % 2 else 0
    return {"arm_f": (150, 70 + scratch * 12), "expr": "confused", "head_tilt": 4, "head_dx": scratch * 0.4}


def adjust_glasses(t):
    k = min(1.0, t * 3)
    return {"arm_f": (120 * k, 100 * k), "glasses_down": 2 if 0.3 < t < 0.9 else 0, "expr": "suspicious"}


def shake_dreads(t):
    return {"head_dx": 1.6 * math.sin(q(t, 1 / 12) * 26), "arm_f": (30, 40), "arm_b": (-30, 40),
            "expr": "happy"}


def talk(t):
    gesture = math.sin(q(t) * 4)
    return {"mouth": 1.0 if int(t * 8) % 3 else 0.0, "arm_f": (55 + 25 * gesture, 50 - 20 * gesture),
            "bob": 0.5 * gesture, "expr": "talk"}


def talk_viewer(t):
    pose = talk(t)
    pose["lean"] = 2
    return pose


def laugh(t):
    k = math.sin(q(t, 1 / 12) * 22)
    return {"lean": -10 + 4 * k, "bob": 1.2 * k, "arm_f": (30, 100), "arm_b": (-30, 100), "expr": "laughing",
            "squash": 1 + 0.05 * k}


def complain(t):
    shake = math.sin(q(t, 1 / 12) * 24)
    return {"arm_f": (140 + 12 * shake, 40), "arm_b": (-140 - 12 * shake, -40), "expr": "furious",
            "mouth": 1.0, "lean": 5, "bob": 0.8 * shake}


def shout(t):
    # Anticipation (crouch) then a big stretch.
    if t < 0.35:
        return {"squash": 0.88, "arm_f": (20, 60), "arm_b": (-20, 60), "expr": "indignant", "lean": 6}
    shake = math.sin(q(t, 1 / 12) * 30)
    return {"squash": 1.1, "arm_f": (150, 30 + 10 * shake), "arm_b": (-150, -30), "expr": "shout",
            "fright": 0.35, "lean": -6, "head_dx": shake * 0.8}


def sleep(t):
    return {"lying": True, "expr": "sleep", "bob": 0.4 * _wave(t, 1.2)}


def wake_scared(t):
    if t < 0.15:
        return {"lying": True, "expr": "scared"}
    k = min(1.0, (t - 0.15) / 0.3)
    return {"squash": 0.85 + 0.35 * (1 - abs(1 - 2 * k)), "fright": 1.0 - k * 0.6, "expr": "scared",
            "arm_f": (160, 20), "arm_b": (-160, -20), "bob": -6 * math.sin(k * math.pi)}


def dance(t):
    beat = int(t * 4) % 4
    arms = [((160, 20), (-20, 30)), ((20, 30), (-160, -20)), ((120, 60), (-120, -60)), ((60, 90), (-60, 90))]
    legs = [((15, 25), (-5, 0)), ((5, 0), (-15, 25)), ((10, 10), (-10, 10)), ((0, 0), (0, 0))]
    return {"arm_f": arms[beat][0], "arm_b": arms[beat][1], "leg_f": legs[beat][0], "leg_b": legs[beat][1],
            "bob": -1.5 if beat % 2 else 0, "expr": "happy", "head_dx": 0.8 if beat % 2 else -0.8,
            "squash": 0.95 if beat % 2 == 0 else 1.04}


def fish(t):
    pose = sit(t)
    bob = 1 if int(t * 2) % 2 else 0
    pose.update({"arm_f": (70 + bob * 3, 40), "prop": "rod", "expr": "thoughtful"})
    return pose


def fish_pull(t):
    pose = sit(t)
    yank = math.sin(q(t, 1 / 12) * 25)
    pose.update({"arm_f": (110 + 15 * yank, 20), "prop": "rod", "expr": "furious", "lean": -10 - 3 * yank})
    return pose


def swim(t):
    stroke = math.sin(q(t, 1 / 10) * 8)
    return {"submerge": 18, "arm_f": (110 + 60 * stroke, 30), "arm_b": (-110 + 60 * stroke, 30),
            "lean": 20, "bob": 0.8 * stroke, "expr": "neutral"}


def build(t):
    hit = int(t * 3) % 2
    return {"arm_f": (150 if hit else 40, 20 if hit else 60), "prop": "hammer", "lean": 12,
            "squash": 0.96 if not hit else 1.0, "expr": "thoughtful", "leg_f": (25, 50), "leg_b": (-20, 20)}


def carry(t):
    pose = walk(t)
    pose.update({"arm_f": (80, 50), "arm_b": (-60, 80), "prop": "plank"})
    return pose


def climb(t):
    alt = int(t * 3) % 2
    return {"arm_f": (170 if alt else 140, 10), "arm_b": (-140 if alt else -170, -10),
            "leg_f": (50 if alt else 20, 70), "leg_b": (20 if alt else 50, 70), "lean": 8}


def fall(t):
    k = min(1.0, t / 0.5)
    return {"lean": -40 * k, "arm_f": (150, 20), "arm_b": (-150, -20), "expr": "scared", "fright": 0.8,
            "bob": 4 * k, "squash": 1 - 0.1 * k}


def get_up(t):
    k = min(1.0, t / 0.8)
    return {"hip_drop": 11 * (1 - k), "leg_f": (80 * (1 - k), 60 * (1 - k)), "leg_b": (60 * (1 - k), 70 * (1 - k)),
            "arm_b": (-40, 20), "expr": "indignant"}


def fan(t):
    wave = int(t * 6) % 2
    return {"arm_f": (120 + wave * 25, 80), "prop": "leaf", "expr": "sad", "bob": 0.4 * _wave(t, 2)}


def look_back(t):
    return {"head_dx": -1.5, "expr": "suspicious", "glasses_down": 1}


def shrug(t):
    k = min(1.0, t * 4)
    return {"arm_f": (60 * k, 90 * k), "arm_b": (-60 * k, -90 * k), "bob": -1 * k, "expr": "perplexed",
            "glasses_down": 1.5}


def celebrate(t):
    jump = abs(math.sin(q(t, 1 / 10) * 6))
    return {"arm_f": (165, 10), "arm_b": (-165, -10), "bob": -4 * jump, "expr": "happy",
            "squash": 1.05 if jump > 0.5 else 0.94}


def stunned(t):
    return {"expr": "perplexed", "head_tilt": 6, "arm_f": (5, 0), "arm_b": (-5, 0), "glasses_down": 1}


def push(t):
    k = math.sin(q(t) * 6)
    return {"arm_f": (85, 10), "arm_b": (75, 20), "lean": 22, "leg_f": (25, 40), "leg_b": (-35, 10),
            "expr": "furious", "bob": 0.6 * k}


def read(t):
    return {"arm_f": (60, 80), "arm_b": (50, 80), "prop": "paper", "expr": "thoughtful", "lean": 4}


def speech_beat(t):
    """Grand speech: alternating pointing and open arms."""
    beat = int(t * 1.5) % 3
    if beat == 0:
        return {"arm_f": (170, 0), "hand_f": "point", "mouth": 1.0 if int(t * 8) % 3 else 0, "expr": "talk"}
    if beat == 1:
        return {"arm_f": (100, 40), "arm_b": (-100, -40), "mouth": 1.0 if int(t * 8) % 3 else 0, "expr": "talk"}
    return {"arm_f": (95, 0), "hand_f": "point", "mouth": 1.0 if int(t * 8) % 2 else 0, "expr": "indignant"}


CLIPS = {name: func for name, func in globals().items()
         if callable(func) and not name.startswith("_") and name not in ("q",)}
