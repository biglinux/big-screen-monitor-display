"""Brother Away: procedural pixel-art puppet.

The character is drawn part by part at the logical (pixel-art) resolution
with aliased primitives, then outlined by dilating the alpha mask, so every
pose stays crisp after the integer nearest-neighbour upscale. The dreadlocks
are verlet ropes simulated in world space: they lag behind head movement,
swing while running, rise when he gets scared and drift with the wind.

Angles are in degrees measured from "straight down"; positive values point
towards where he is facing. Layer coordinates always face right; the layer
is mirrored afterwards when he faces left.
"""

import math
import random

import numpy as np
from PIL import Image, ImageDraw

from . import palette as P

LAYER_W, LAYER_H = 60, 66
ANCHOR_X, ANCHOR_Y = 30, 62        # feet centre inside the layer

DEFAULT_POSE = {
    "bob": 0.0, "squash": 1.0, "lean": 0.0, "head_tilt": 0.0, "head_dx": 0.0, "head_dy": 0.0,
    "arm_f": (8.0, 10.0), "arm_b": (-8.0, 10.0), "leg_f": (4.0, 0.0), "leg_b": (-4.0, 0.0),
    "hip_drop": 0.0, "expr": "neutral", "mouth": 0.0, "glasses_down": 0.0, "fright": 0.0,
    "prop": None, "no_glasses": False, "arms_crossed": False, "lying": False, "submerge": 0,
    "hand_f": None, "hand_b": None, "fan": 0.0,
}

# brows: (front angle, back angle, lift) ; mouth shape name
EXPRESSIONS = {
    "neutral": ((0, 0, 0), "line"),
    "happy": ((-10, -10, 1), "smile"),
    "ironic": ((15, -15, 0), "smirk"),
    "furious": ((30, 30, -1), "shout"),
    "indignant": ((25, 25, 0), "frown_open"),
    "perplexed": ((-25, -25, 2), "o"),
    "scared": ((-30, -30, 2), "o_big"),
    "suspicious": ((20, -5, 0), "flat_side"),
    "confused": ((-20, 15, 1), "wavy"),
    "thoughtful": ((10, -10, 0), "small"),
    "sad": ((-25, -25, 0), "frown"),
    "laughing": ((-15, -15, 2), "laugh"),
    "shout": ((35, 35, -1), "shout_big"),
    "sleep": ((0, 0, -1), "small"),
    "talk": ((0, 0, 0), "talk"),
}


def _rot(length, angle):
    rad = math.radians(angle)
    return math.sin(rad) * length, math.cos(rad) * length


class Lock:
    """One dreadlock: a verlet chain anchored to the head."""

    def __init__(self, anchor, length, segments, front=False, thickness=2):
        self.anchor = anchor            # (dx, dy) from head centre, facing right
        self.segment = length / segments
        self.front = front
        self.thickness = thickness
        self.points = None
        self.previous = None
        self.count = segments + 1

    def reset(self, origin):
        self.points = [(origin[0], origin[1] + i * self.segment) for i in range(self.count)]
        self.previous = list(self.points)

    def step(self, origin, gravity, wind, fright, dt, facing):
        if self.points is None:
            self.reset(origin)
        damping = 0.86
        lift = fright * 1.6 * gravity
        for i in range(1, self.count):
            x, y = self.points[i]
            px, py = self.previous[i]
            # Fright pushes the free end upwards and outwards (comic "hair up").
            side = (1 if self.anchor[0] >= 0 else -1) * facing
            # A gentle outward spread gives the mane its volume; fright flares it.
            outward = side * gravity * (0.0 if self.front else 0.12 + 0.5 * fright)
            ax = wind * gravity * 0.6 + outward
            ay = gravity - lift * (i / self.count) * 1.4
            nx = x + (x - px) * damping + ax * dt * dt
            ny = y + (y - py) * damping + ay * dt * dt
            self.previous[i] = (x, y)
            self.points[i] = (nx, ny)
        self.points[0] = origin
        self.previous[0] = origin
        for _ in range(3):
            for i in range(1, self.count):
                ax_, ay_ = self.points[i - 1]
                bx, by = self.points[i]
                dx, dy = bx - ax_, by - ay_
                dist = math.hypot(dx, dy) or 1e-6
                ratio = self.segment / dist
                self.points[i] = (ax_ + dx * ratio, ay_ + dy * ratio)


class Dreads:
    def __init__(self):
        # Back locks hang behind the head and shoulders; front ones frame the face.
        self.locks = [
            Lock((-8, -2), 17, 5, thickness=3), Lock((-7, -6), 18, 6), Lock((-4, -8), 16, 5),
            Lock((0, -8), 14, 5, thickness=3), Lock((4, -7), 13, 4), Lock((7, -4), 15, 5),
            Lock((-8, 3), 13, 4), Lock((-6, -7), 15, 5, thickness=3),
            Lock((7, -1), 13, 4, front=True), Lock((-7, 0), 14, 5, front=True),
            Lock((2, -7), 4, 2, front=True), Lock((-2, -7), 5, 2, front=True),
            Lock((5, -6), 4, 2, front=True),
        ]

    def step(self, head_world, facing, dt, wind, fright):
        gravity = 260.0
        for lock in self.locks:
            origin = (head_world[0] + lock.anchor[0] * facing, head_world[1] + lock.anchor[1])
            lock.step(origin, gravity, wind, fright, dt, facing)

    def reset(self):
        for lock in self.locks:
            lock.points = None


class Puppet:
    def __init__(self, seed=7):
        self.dreads = Dreads()
        self.facing = 1
        self.world = (0.0, 0.0)
        self._rng = random.Random(seed)

    # ----------------------------------------------------------- geometry
    def _joints(self, pose):
        squash = pose["squash"]
        hip_y = ANCHOR_Y - 15 + pose["hip_drop"]
        torso_h = 12 * squash
        lean = pose["lean"]
        hip = (ANCHOR_X, hip_y + (1 - squash) * 4)
        ldx, _ = _rot(torso_h, 180 - lean)
        shoulder = (hip[0] - ldx, hip[1] - torso_h + pose["bob"])
        head = (shoulder[0] + 1 + pose["head_dx"] + math.sin(math.radians(lean)) * 3,
                shoulder[1] - 8 * (0.6 + 0.4 * squash) + pose["head_dy"])
        return hip, shoulder, head

    def head_world_offset(self, pose):
        _hip, _shoulder, head = self._joints(pose)
        return (head[0] - ANCHOR_X) * self.facing, head[1] - ANCHOR_Y

    # ----------------------------------------------------------- update
    def update(self, dt, world_x, world_y, facing, pose, wind=0.0):
        if facing != self.facing:
            self.facing = facing
        self.world = (world_x, world_y)
        hx, hy = self.head_world_offset(pose)
        if pose.get("lying"):
            hx, hy = -14 * facing, -4
        self.dreads.step((world_x + hx, world_y + hy), facing, min(dt, 0.1), wind, pose["fright"])

    # ----------------------------------------------------------- drawing
    def render(self, pose):
        """Return the RGBA layer for ``pose`` (anchor at ANCHOR_X/ANCHOR_Y)."""
        layer = Image.new("RGBA", (LAYER_W, LAYER_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        hip, shoulder, head = self._joints(pose)
        self._draw_dreads(d, pose, head, front=False)
        self._draw_arm(d, pose, shoulder, pose["arm_b"], back=True)
        self._draw_leg(d, hip, pose["leg_b"], back=True)
        self._draw_leg(d, hip, pose["leg_f"], back=False)
        self._draw_torso(d, pose, hip, shoulder)
        self._draw_head(d, pose, head)
        self._draw_dreads(d, pose, head, front=True)
        if pose["arms_crossed"]:
            self._draw_crossed_arms(d, shoulder)
        else:
            self._draw_arm(d, pose, shoulder, pose["arm_f"], back=False)
        self._draw_prop(d, pose, shoulder)
        layer = outline(layer)
        if pose["submerge"]:
            cut = ANCHOR_Y - int(pose["submerge"])
            if cut < LAYER_H:
                layer.paste((0, 0, 0, 0), (0, max(0, cut), LAYER_W, LAYER_H))
        if pose["lying"]:
            layer = layer.transpose(Image.Transpose.ROTATE_90)
        if self.facing < 0:
            layer = layer.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        return layer

    def anchor(self, pose):
        if pose["lying"]:
            # ROTATE_90 maps the feet (bottom centre) to the right middle.
            ax, ay = ANCHOR_Y - 2, LAYER_W - ANCHOR_X
            return (LAYER_H - ax if self.facing < 0 else ax), ay + 4
        return (LAYER_W - ANCHOR_X if self.facing < 0 else ANCHOR_X), ANCHOR_Y

    def _to_layer(self, point):
        wx, wy = point
        return (ANCHOR_X + (wx - self.world[0]) * self.facing, ANCHOR_Y + (wy - self.world[1]))

    def _draw_dreads(self, d, pose, head, front):
        for index, lock in enumerate(self.dreads.locks):
            if lock.front != front or lock.points is None:
                continue
            if pose["lying"]:
                # Spread on the sand beyond the top of the head.
                spread = lock.anchor[0] * 0.25
                points = [(head[0] + lock.anchor[0] + i * spread, head[1] + lock.anchor[1] - i * lock.segment * 0.8)
                          for i in range(lock.count)]
            else:
                origin = (head[0] + lock.anchor[0], head[1] + lock.anchor[1])
                base = self._to_layer(lock.points[0])
                points = [(origin[0] + (px - base[0]), origin[1] + (py - base[1]))
                          for px, py in map(self._to_layer, lock.points)]
            pts = [(round(x), round(y)) for x, y in points]
            d.line(pts, fill=P.DREAD, width=lock.thickness)
            for i, (x, y) in enumerate(pts[1:], 1):
                if (i + index) % 2 == 0:
                    d.point((x, y), fill=P.DREAD_LIGHT)

    def _draw_leg(self, d, hip, leg, back):
        hip_angle, knee_angle = leg
        ux, uy = _rot(7, hip_angle)
        knee = (hip[0] + ux + (-1 if back else 1), hip[1] + uy)
        lx, ly = _rot(7, hip_angle - knee_angle)
        foot = (knee[0] + lx, knee[1] + ly)
        pants = P.PANTS_SHADE if back else P.PANTS
        start = (hip[0] + (-2 if back else 2), hip[1])
        d.line([start, knee], fill=pants, width=5)
        d.line([knee, foot], fill=pants, width=4)
        d.ellipse((knee[0] - 2, knee[1] - 2, knee[0] + 2, knee[1] + 2), fill=pants)
        fx, fy = round(foot[0]), round(foot[1])
        d.rectangle((fx - 2, fy - 1, fx + 3, fy + 1), fill=P.SHOE)
        d.point((fx + 3, fy), fill=P.SHOE_ACCENT)
        d.point((fx - 1, fy + 1), fill=P.SHOE_ACCENT)

    def _draw_torso(self, d, pose, hip, shoulder):
        sx, sy = shoulder
        hx, hy = hip
        squash = pose["squash"]
        half_top = 7 * (2 - squash) ** 0.5
        half_bottom = 6 * (2 - squash) ** 0.5
        # Robust shoulders (skin, tank top) then the shirt.
        d.ellipse((sx - half_top - 1, sy - 1, sx + half_top + 1, sy + 4), fill=P.SKIN)
        body = [(sx - half_top + 1, sy), (sx + half_top - 1, sy), (hx + half_bottom, hy), (hx - half_bottom, hy)]
        d.polygon(body, fill=P.SHIRT)
        d.line([(sx - half_top + 2, sy + 1), (hx - half_bottom + 1, hy - 1)], fill=P.SHIRT_LIGHT)
        # Original white print: a tiny sun over a palm.
        cx, cy = round((sx + hx) / 2) + 1, round((sy + hy) / 2)
        for px, py in ((0, -2), (-1, -1), (1, -1), (0, -1), (0, 0), (0, 1), (-2, -2), (2, -2)):
            d.point((cx + px, cy + py), fill=P.PRINT)
        # Waistband + neck.
        d.line([(hx - half_bottom, hy), (hx + half_bottom, hy)], fill=P.PANTS_SHADE, width=2)
        d.line([(hx, hy + 1), (hx, hy + 4)], fill=P.PANTS_SHADE)
        d.rectangle((sx - 1, sy - 3, sx + 2, sy), fill=P.SKIN_SHADE)

    def _draw_head(self, d, pose, head):
        hx, hy = round(head[0]), round(head[1])
        # Big caricature head (enlarged for readability), slightly 3/4 view.
        d.ellipse((hx - 7, hy - 7, hx + 7, hy + 7), fill=P.SKIN)
        d.ellipse((hx - 7, hy - 7, hx + 6, hy + 6), fill=P.SKIN)
        d.chord((hx - 7, hy - 2, hx + 7, hy + 8), 0, 180, fill=P.SKIN_SHADE)
        d.ellipse((hx - 6, hy - 7, hx + 6, hy + 6), fill=P.SKIN)
        # Cheek light and ear.
        d.point((hx + 3, hy + 2), fill=P.SKIN_LIGHT)
        d.rectangle((hx - 7, hy, hx - 6, hy + 2), fill=P.SKIN_SHADE)
        # Hair cap on top (base of the locks).
        d.chord((hx - 8, hy - 9, hx + 7, hy + 1), 180, 360, fill=P.DREAD)
        d.point((hx - 3, hy - 7), fill=P.DREAD_LIGHT)
        d.point((hx + 2, hy - 7), fill=P.DREAD_LIGHT)
        brows, mouth = EXPRESSIONS.get(pose["expr"], EXPRESSIONS["neutral"])
        if pose["mouth"] > 0.5 and mouth in ("line", "small", "smile", "smirk", "flat_side", "talk"):
            mouth = "talk"
        gy = hy - 1 + round(pose["glasses_down"])
        if pose["no_glasses"]:
            for ex in (hx - 3, hx + 3):
                d.rectangle((ex - 1, hy - 2, ex + 1, hy), fill=P.EYE_WHITE)
                d.point((ex + 1, hy - 1), fill=P.GLASSES)
        else:
            if pose["glasses_down"] >= 1.5:
                for ex in (hx - 3, hx + 3):  # peering over the glasses
                    d.point((ex, hy - 3), fill=P.EYE_WHITE)
                    d.point((ex + 1, hy - 3), fill=P.GLASSES)
            d.rectangle((hx - 6, gy - 1, hx - 1, gy + 2), fill=P.GLASSES)
            d.rectangle((hx + 1, gy - 1, hx + 6, gy + 2), fill=P.GLASSES)
            d.line([(hx - 1, gy), (hx + 1, gy)], fill=P.GLASSES)
            d.line([(hx - 7, gy), (hx - 8, gy)], fill=P.GLASSES)
            d.rectangle((hx - 5, gy, hx - 2, gy + 1), fill=P.LENS)
            d.rectangle((hx + 2, gy, hx + 5, gy + 1), fill=P.LENS)
            reflection = pose.get("reflection") or (P.LENS_GOLD, P.LENS_ORANGE)
            d.point((hx - 5, gy), fill=reflection[0])
            d.point((hx - 4, gy), fill=reflection[1])
            d.point((hx + 2, gy), fill=reflection[0])
            d.point((hx + 3, gy), fill=reflection[1])
            if pose.get("reflection_fin"):
                d.point((hx + 4, gy + 1), fill=P.SHARK_LIGHT)
                d.point((hx + 5, gy + 1), fill=P.SHARK_LIGHT)
                d.point((hx + 5, gy), fill=P.SHARK_LIGHT)
        # Eyebrows above the glasses carry most of the expression.
        front_angle, back_angle, lift = brows
        by = hy - 4 - lift + (1 if pose["no_glasses"] else 0)
        for x0, angle in ((hx + 1, front_angle), (hx - 5, -back_angle)):
            dy = round(math.tan(math.radians(angle)) * 2)
            d.line([(x0, by - dy), (x0 + 3, by + dy)], fill=P.BROW, width=1)
            d.line([(x0, by - dy - 1), (x0 + 3, by + dy - 1)], fill=P.BROW, width=1)
        # Broad nose, offset towards the facing side.
        d.rectangle((hx + 1, hy + 1, hx + 3, hy + 2), fill=P.SKIN_SHADE)
        d.point((hx + 4, hy + 2), fill=P.SKIN_DARK)
        d.point((hx + 1, hy + 2), fill=P.SKIN_DARK)
        self._draw_mouth(d, hx + 1, hy + 5, mouth, pose["mouth"])

    def _draw_mouth(self, d, mx, my, shape, amount):
        if shape == "line":
            d.line([(mx - 2, my), (mx + 2, my - 1)], fill=P.MOUTH)   # slightly asymmetric
        elif shape == "smile":
            d.line([(mx - 3, my - 1), (mx - 1, my + 1), (mx + 2, my + 1), (mx + 3, my - 2)], fill=P.MOUTH)
        elif shape == "smirk":
            d.line([(mx - 2, my + 1), (mx + 1, my + 1), (mx + 3, my - 1)], fill=P.MOUTH)
        elif shape == "flat_side":
            d.line([(mx - 1, my), (mx + 3, my)], fill=P.MOUTH)
        elif shape == "small":
            d.line([(mx - 1, my), (mx + 1, my)], fill=P.MOUTH)
        elif shape == "wavy":
            d.line([(mx - 3, my), (mx - 2, my - 1), (mx, my), (mx + 1, my - 1), (mx + 3, my)], fill=P.MOUTH)
        elif shape in ("frown", "frown_open"):
            d.line([(mx - 3, my + 1), (mx - 1, my - 1), (mx + 1, my - 1), (mx + 3, my + 1)], fill=P.MOUTH)
            if shape == "frown_open":
                d.rectangle((mx - 1, my, mx + 1, my + 1), fill=P.MOUTH)
        elif shape in ("o", "o_big"):
            r = 1 if shape == "o" else 2
            d.ellipse((mx - r, my - r + 1, mx + r, my + r + 1), fill=P.MOUTH)
        elif shape == "talk":
            h = 1 + round(amount * 2)
            d.rectangle((mx - 2, my - 1, mx + 2, my - 1 + h), fill=P.MOUTH)
            d.line([(mx - 1, my - 1), (mx + 1, my - 1)], fill=P.TEETH)
        elif shape in ("shout", "shout_big", "laugh"):
            w = 3 if shape != "shout" else 2
            h = 4 if shape == "shout_big" else 3
            d.rectangle((mx - w, my - 2, mx + w, my - 2 + h), fill=P.MOUTH)
            d.line([(mx - w + 1, my - 2), (mx + w - 1, my - 2)], fill=P.TEETH)
            d.point((mx, my - 2 + h - 1), fill=P.TONGUE)
            if shape == "laugh":
                d.point((mx + 1, my - 2 + h - 1), fill=P.TONGUE)

    def _draw_arm(self, d, pose, shoulder, arm, back):
        shoulder_angle, elbow = arm
        sx = shoulder[0] + (-6 if back else 6)
        sy = shoulder[1] + 2
        ux, uy = _rot(7, shoulder_angle)
        elbow_pt = (sx + ux, sy + uy)
        fx, fy = _rot(7, shoulder_angle + elbow)
        hand = (elbow_pt[0] + fx, elbow_pt[1] + fy)
        skin = P.SKIN_SHADE if back else P.SKIN
        d.line([(sx, sy), elbow_pt], fill=skin, width=3)
        d.line([elbow_pt, hand], fill=skin, width=3)
        d.ellipse((elbow_pt[0] - 1, elbow_pt[1] - 1, elbow_pt[0] + 1, elbow_pt[1] + 1), fill=skin)
        hx, hy = round(hand[0]), round(hand[1])
        d.ellipse((hx - 2, hy - 2, hx + 1, hy + 1), fill=skin)
        key = "hand_b" if back else "hand_f"
        pose[key + "_pos"] = (hx, hy)
        if not back and pose.get("hand_f") == "point":
            fdx, fdy = _rot(3, shoulder_angle + elbow)
            d.line([(hx, hy), (hx + fdx, hy + fdy)], fill=skin, width=1)

    def _draw_crossed_arms(self, d, shoulder):
        sx, sy = shoulder
        y = sy + 6
        d.rectangle((sx - 6, y - 1, sx + 6, y + 2), fill=P.SKIN)
        d.line([(sx - 6, y), (sx + 6, y + 1)], fill=P.SKIN_SHADE)
        d.ellipse((sx - 8, y - 2, sx - 4, y + 2), fill=P.SKIN)
        d.ellipse((sx + 4, y - 2, sx + 8, y + 2), fill=P.SKIN)

    def _draw_prop(self, d, pose, shoulder):
        prop = pose.get("prop")
        hand = pose.get("hand_f_pos")
        if not prop or not hand:
            return
        hx, hy = hand
        if prop == "rod":
            d.line([(hx - 2, hy + 2), (hx + 14, hy - 16)], fill=P.WOOD_DARK, width=1)
        elif prop == "hammer":
            d.line([(hx, hy), (hx + 1, hy - 6)], fill=P.WOOD, width=1)
            d.rectangle((hx - 1, hy - 8, hx + 3, hy - 6), fill=P.ROCK_DARK)
        elif prop == "coconut":
            d.ellipse((hx - 2, hy - 4, hx + 2, hy), fill=P.COCONUT)
        elif prop == "fish":
            d.ellipse((hx - 1, hy - 2, hx + 6, hy + 1), fill=P.FISH)
            d.polygon([(hx - 1, hy - 1), (hx - 4, hy - 3), (hx - 4, hy + 1)], fill=P.FISH)
        elif prop == "plank":
            d.rectangle((hx - 6, hy - 2, hx + 8, hy), fill=P.WOOD)
        elif prop == "bottle":
            d.rectangle((hx - 1, hy - 5, hx + 1, hy), fill=P.BOTTLE)
            d.point((hx, hy - 6), fill=P.PAPER)
        elif prop == "paper":
            d.rectangle((hx - 3, hy - 6, hx + 3, hy - 1), fill=P.PAPER)
            d.line([(hx - 2, hy - 4), (hx + 2, hy - 4)], fill=P.SAND_SHADE)
        elif prop == "leaf":
            d.polygon([(hx, hy), (hx + 5, hy - 7), (hx + 8, hy - 3)], fill=P.PALM_LEAF)


def outline(layer):
    """1 px dark outline around the silhouette (4-neighbourhood dilation)."""
    rgba = np.array(layer)
    alpha = rgba[..., 3] > 0
    grown = alpha.copy()
    grown[1:, :] |= alpha[:-1, :]
    grown[:-1, :] |= alpha[1:, :]
    grown[:, 1:] |= alpha[:, :-1]
    grown[:, :-1] |= alpha[:, 1:]
    edge = grown & ~alpha
    rgba[edge] = (*P.OUTLINE, 255)
    rgba[alpha, 3] = 255
    return Image.fromarray(rgba, "RGBA")


def tint(layer, light, warm=None):
    """Darken a sprite for the time of day; ``warm`` adds a fire/sunset tint."""
    if light >= 0.995 and not warm:
        return layer
    rgba = np.array(layer).astype(np.float32)
    rgba[..., :3] *= light
    if warm:
        color, amount = warm
        rgba[..., :3] = rgba[..., :3] * (1 - amount) + np.array(color, np.float32) * amount * light
    return Image.fromarray(np.clip(rgba, 0, 255).astype(np.uint8), "RGBA")
