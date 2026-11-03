"""Brother Away colour palette (original, VGA-inspired, limited ramps)."""

# Character
SKIN = (152, 99, 63)
SKIN_SHADE = (116, 72, 44)
SKIN_LIGHT = (184, 128, 86)
SKIN_DARK = (84, 50, 30)
DREAD = (34, 26, 22)
DREAD_LIGHT = (66, 52, 42)
GLASSES = (14, 12, 14)
LENS = (40, 30, 26)
LENS_GOLD = (255, 196, 64)
LENS_ORANGE = (240, 128, 40)
SHIRT = (22, 22, 26)
SHIRT_LIGHT = (48, 48, 56)
PRINT = (236, 236, 236)
PANTS = (214, 216, 220)
PANTS_SHADE = (170, 174, 182)
SHOE = (236, 234, 228)
SHOE_ACCENT = (244, 128, 32)
MOUTH = (70, 26, 22)
TEETH = (248, 244, 236)
TONGUE = (196, 74, 70)
OUTLINE = (24, 14, 10)
BROW = (28, 20, 16)
EYE_WHITE = (244, 244, 240)

# World
SAND = (232, 198, 112)
SAND_SHADE = (198, 160, 84)
SAND_LIGHT = (250, 224, 150)
SAND_WET = (176, 146, 92)
PALM_TRUNK = (128, 88, 52)
PALM_TRUNK_DARK = (92, 60, 34)
PALM_LEAF = (52, 148, 64)
PALM_LEAF_DARK = (30, 98, 44)
PALM_LEAF_LIGHT = (104, 186, 82)
COCONUT = (102, 66, 34)
ROCK = (122, 118, 124)
ROCK_DARK = (82, 78, 88)
ROCK_LIGHT = (164, 160, 166)
BUSH = (40, 120, 56)
BUSH_LIGHT = (84, 164, 72)
WOOD = (150, 104, 60)
WOOD_DARK = (104, 68, 36)
FIRE_OUTER = (236, 92, 24)
FIRE_MID = (252, 168, 32)
FIRE_CORE = (255, 240, 150)
SMOKE = (150, 150, 158)
FOAM = (236, 246, 252)
SHARK = (92, 104, 120)
SHARK_LIGHT = (196, 206, 214)
CRAB = (218, 70, 46)
CRAB_DARK = (150, 40, 28)
GULL = (240, 240, 236)
GULL_DARK = (120, 124, 132)
UFO = (156, 168, 182)
UFO_DARK = (88, 96, 110)
UFO_LIGHT = (130, 255, 170)
BEAM = (170, 255, 200)
BOTTLE = (64, 160, 120)
PAPER = (244, 232, 196)
GOLD = (252, 204, 60)
CHEST = (126, 78, 40)
VOLCANO = (98, 72, 64)
LAVA = (255, 110, 40)
SHIP = (70, 52, 44)
SAIL = (236, 230, 214)
FISH = (110, 170, 210)
MERMAID_TAIL = (40, 180, 160)
MERMAID_HAIR = (200, 60, 70)
RAIN = (170, 200, 236)
STAR = (250, 250, 230)
MOON = (240, 236, 210)
MOON_SHADOW = (60, 66, 92)

# Sky keyframes: hour -> (zenith, horizon, sea_top, sea_bottom, light multiplier)
SKY_KEYS = [
    (0.0, (8, 10, 30), (24, 28, 64), (14, 24, 56), (6, 12, 32), 0.45),
    (4.5, (14, 16, 44), (44, 40, 88), (20, 30, 66), (8, 16, 40), 0.5),
    (5.5, (60, 64, 128), (250, 150, 110), (60, 80, 130), (24, 40, 80), 0.7),   # dawn
    (7.0, (96, 156, 228), (252, 214, 170), (54, 128, 190), (20, 70, 130), 0.9),  # morning
    (12.0, (64, 150, 240), (176, 222, 252), (40, 140, 210), (14, 80, 150), 1.0),  # noon
    (16.0, (78, 150, 226), (200, 222, 240), (40, 130, 196), (16, 74, 140), 0.98),  # afternoon
    (18.2, (110, 86, 150), (252, 140, 70), (90, 90, 140), (30, 42, 90), 0.8),   # sunset
    (19.4, (40, 36, 88), (150, 80, 110), (36, 44, 92), (14, 22, 56), 0.6),      # dusk
    (21.0, (12, 14, 40), (30, 34, 74), (16, 26, 60), (6, 12, 34), 0.47),       # night
    (24.0, (8, 10, 30), (24, 28, 64), (14, 24, 56), (6, 12, 32), 0.45),
]

PERIODS = [
    (0.0, "late_night"), (4.5, "dawn"), (6.5, "morning"), (11.0, "noon"),
    (14.0, "afternoon"), (17.5, "sunset"), (19.0, "dusk"), (20.5, "night"), (24.0, "late_night"),
]


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(lerp(x, y, t))) for x, y in zip(c1, c2))


def shade(color, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def sky_at(hour):
    """Interpolated (zenith, horizon, sea_top, sea_bottom, light) for ``hour``."""
    for (h0, *a), (h1, *b) in zip(SKY_KEYS, SKY_KEYS[1:]):
        if h0 <= hour <= h1:
            t = (hour - h0) / (h1 - h0) if h1 > h0 else 0
            return tuple(mix(x, y, t) for x, y in zip(a[:4], b[:4])) + (lerp(a[4], b[4], t),)
    return tuple(SKY_KEYS[0][1:5]) + (SKY_KEYS[0][5],)


def period_at(hour):
    name = PERIODS[0][1]
    for start, label in PERIODS:
        if hour >= start:
            name = label
    return name
