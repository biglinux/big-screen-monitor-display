"""Geometry: normalised widget boxes <-> panel pixels, anchors, reflow, snapping.

A layout is designed on a reference canvas (``ref``). On a panel of another
size every widget is scaled by ``s = min(W/ref_w, H/ref_h)`` (uniform, so
circles stay round and text keeps its proportions) and placed by its anchor:
a top-right widget keeps its distance to the top-right corner, a centred one
stays centred. With the reference aspect ratio all anchors coincide, so the
composition is simply scaled. ``from_pixels`` is the exact inverse, which
lets the editor work on any panel size.
"""

import copy

ANCHOR_PARTS = {"tl": ("t", "l"), "tc": ("t", "c"), "tr": ("t", "r"), "ml": ("m", "l"), "c": ("m", "c"),
                "mr": ("m", "r"), "bl": ("b", "l"), "bc": ("b", "c"), "br": ("b", "r")}


def auto_anchor(widget):
    cx, cy = widget["x"] + widget["w"] / 2, widget["y"] + widget["h"] / 2
    horizontal = "l" if cx < 1 / 3 else ("r" if cx > 2 / 3 else "c")
    vertical = "t" if cy < 1 / 3 else ("b" if cy > 2 / 3 else "m")
    for name, parts in ANCHOR_PARTS.items():
        if parts == (vertical, horizontal):
            return name
    return "c"


def anchor_of(widget):
    anchor = widget.get("anchor", "auto")
    return auto_anchor(widget) if anchor not in ANCHOR_PARTS else anchor


def scale(target, ref):
    return min(target[0] / ref[0], target[1] / ref[1])


def _place(start, size, extent, ref_extent, factor, part):
    """Pixel start of a span along one axis."""
    scaled = size * factor
    if part in ("l", "t"):
        return start * factor
    if part in ("r", "b"):
        return extent - (ref_extent - start - size) * factor - scaled
    return extent / 2 + (start + size / 2 - ref_extent / 2) * factor - scaled / 2


def _unplace(pixel, scaled, extent, ref_extent, factor, part):
    size = scaled / factor
    if part in ("l", "t"):
        return pixel / factor
    if part in ("r", "b"):
        return ref_extent - (extent - pixel - scaled) / factor - size
    return (pixel + scaled / 2 - extent / 2) / factor + ref_extent / 2 - size / 2


def to_pixels(widget, target, ref):
    """(x, y, w, h) in panel pixels (floats)."""
    rw, rh = ref
    width, height = target
    factor = scale(target, ref)
    vertical, horizontal = ANCHOR_PARTS[anchor_of(widget)]
    x, y, w, h = widget["x"] * rw, widget["y"] * rh, widget["w"] * rw, widget["h"] * rh
    return (_place(x, w, width, rw, factor, horizontal), _place(y, h, height, rh, factor, vertical),
            w * factor, h * factor)


def from_pixels(widget, box, target, ref):
    """Normalised x, y, w, h for a pixel box, keeping the widget's anchor."""
    rw, rh = ref
    width, height = target
    factor = scale(target, ref)
    vertical, horizontal = ANCHOR_PARTS[anchor_of(widget)]
    px, py, pw, ph = box
    x = _unplace(px, pw, width, rw, factor, horizontal)
    y = _unplace(py, ph, height, rh, factor, vertical)
    return {"x": x / rw, "y": y / rh, "w": pw / factor / rw, "h": ph / factor / rh}


def int_box(box):
    x, y, w, h = box
    return int(round(x)), int(round(y)), max(1, int(round(w))), max(1, int(round(h)))


# ---------------------------------------------------------------- portrait reflow

FULL_WIDTH_TYPES = {"separator", "text", "processes", "cores"}
BOTTOM_TYPES = {"clock"}
PARTNERS = {"cpu": "gpu", "gpu": "cpu", "net_down": "net_up", "net_up": "net_down", "fan": "encdec",
            "encdec": "fan", "ram": "swap", "swap": "ram"}


def reflow_portrait(widgets, ref, ref_portrait):
    """Portrait arrangement of a landscape layout, used until the user edits one.

    Wide widgets get a row of their own; the others are paired two per row,
    keeping related widgets side by side (CPU+GPU, download+upload, fan+video
    engine). The clock goes to the bottom. Widgets keep their aspect ratio and
    the z-order is preserved.
    """
    rw, rh = ref
    pw, ph = ref_portrait
    margin = pw * 0.04
    gap = pw * 0.03
    usable = pw - 2 * margin
    column = (usable - gap) / 2
    frames = [w for w in widgets if w.get("visible", True) and w["type"] == "frame"]
    ordered = sorted((w for w in widgets if w.get("visible", True) and w["type"] != "frame"),
                     key=lambda w: (w["type"] in BOTTOM_TYPES, w["y"], w["x"]))

    def is_full(widget):
        return widget["type"] in FULL_WIDTH_TYPES or widget["type"] in BOTTOM_TYPES or widget["w"] * rw > column * 1.35

    rows, pending = [], list(ordered)
    while pending:
        widget = pending.pop(0)
        if is_full(widget):
            rows.append([widget])
            continue
        partner_type = PARTNERS.get(widget["type"])
        halves = [w for w in pending if not is_full(w)]
        pending_types = {w["type"] for w in halves}
        partner = next((w for w in halves if w["type"] == partner_type), None)
        if partner is None:     # do not take a widget whose own partner is still waiting
            partner = next((w for w in halves if PARTNERS.get(w["type"]) not in pending_types), None) or \
                next(iter(halves), None)
        if partner is not None:
            pending.remove(partner)
            rows.append([widget, partner])
        else:
            rows.append([widget])
    placed = []
    top = margin
    for row in rows:
        slot = usable if len(row) == 1 and is_full(row[0]) else column
        sizes = []
        for widget in row:
            width, height = widget["w"] * rw, widget["h"] * rh
            factor = slot / width if is_full(widget) else min(1.0, slot / width) if width else 1.0
            if widget["type"] in BOTTOM_TYPES:
                factor = min(factor, 1.4)
            sizes.append((width * factor, height * factor))
        row_h = max(h for _w, h in sizes)
        total_w = sum(w for w, _h in sizes) + gap * (len(row) - 1)
        x = margin + (usable - total_w) / 2 if len(row) == 1 else margin
        for index, (widget, (w, h)) in enumerate(zip(row, sizes)):
            if len(row) > 1:
                x = margin + index * (column + gap) + (column - w) / 2
            clone = copy.deepcopy(widget)
            clone.update({"x": x / pw, "y": (top + (row_h - h) / 2) / ph, "w": w / pw, "h": h / ph,
                          "anchor": "auto"})
            placed.append(clone)
        top += row_h + gap
    used = top - gap + margin
    if used > ph:      # too tall: shrink around the centre line so everything stays visible
        factor = ph / used
        for widget in placed:
            cx = widget["x"] + widget["w"] / 2
            widget["w"] *= factor
            widget["h"] *= factor
            widget["y"] *= factor
            widget["x"] = cx - widget["w"] / 2
    elif used < ph:    # spread the rows over the free height
        offset = (ph - used) / 2 / ph
        for widget in placed:
            widget["y"] += offset
    for widget in frames:
        clone = copy.deepcopy(widget)
        clone.update({"x": 0.015, "y": 0.01, "w": 0.97, "h": 0.98, "anchor": "auto"})
        placed.insert(0, clone)
    order = {w["id"]: i for i, w in enumerate(widgets)}
    placed.sort(key=lambda w: order.get(w["id"], 0))       # keep the z-order
    return placed


# ---------------------------------------------------------------- editor helpers

def align(boxes, mode, canvas=None):
    """Align pixel boxes {id: (x, y, w, h)}; with one box, align to the canvas."""
    if not boxes:
        return {}
    if len(boxes) == 1 and canvas:
        bounds = (0, 0, canvas[0], canvas[1])
    else:
        bounds = (min(b[0] for b in boxes.values()), min(b[1] for b in boxes.values()),
                  max(b[0] + b[2] for b in boxes.values()), max(b[1] + b[3] for b in boxes.values()))
    x0, y0, x1, y1 = bounds
    result = {}
    for key, (x, y, w, h) in boxes.items():
        if mode == "left":
            x = x0
        elif mode == "right":
            x = x1 - w
        elif mode == "hcenter":
            x = (x0 + x1) / 2 - w / 2
        elif mode == "top":
            y = y0
        elif mode == "bottom":
            y = y1 - h
        elif mode == "vcenter":
            y = (y0 + y1) / 2 - h / 2
        result[key] = (x, y, w, h)
    return result


def distribute(boxes, axis):
    """Equal gaps between three or more boxes along ``axis`` ("h" or "v")."""
    if len(boxes) < 3:
        return dict(boxes)
    index = 0 if axis == "h" else 1
    ordered = sorted(boxes.items(), key=lambda item: item[1][index])
    start = ordered[0][1][index]
    end = ordered[-1][1][index] + ordered[-1][1][index + 2]
    total = sum(box[index + 2] for _key, box in ordered)
    gap = (end - start - total) / (len(ordered) - 1)
    result, cursor = {}, start
    for key, box in ordered:
        box = list(box)
        box[index] = cursor
        cursor += box[index + 2] + gap
        result[key] = tuple(box)
    return result


def snap_value(value, targets, threshold):
    """Closest target within ``threshold``: (snapped value, target or None)."""
    best, best_target = value, None
    distance = threshold
    for target in targets:
        if abs(value - target) <= distance:
            best, best_target, distance = target, target, abs(value - target)
    return best, best_target


def snap_box(box, others, canvas, grid=0, threshold=6, margin=0):
    """Snap a moving box to the grid, canvas edges/centre/margins and other boxes.

    Returns the snapped box and the guide lines used [("v"|"h", position)].
    """
    x, y, w, h = box
    guides = []
    xs = [0, canvas[0], canvas[0] / 2]
    ys = [0, canvas[1], canvas[1] / 2]
    if margin:
        xs += [margin, canvas[0] - margin]
        ys += [margin, canvas[1] - margin]
    for ox, oy, ow, oh in others:
        xs += [ox, ox + ow, ox + ow / 2]
        ys += [oy, oy + oh, oy + oh / 2]
    best_dx, guide_x = None, None
    for edge in (x, x + w / 2, x + w):
        snapped, target = snap_value(edge, xs, threshold)
        if target is not None and (best_dx is None or abs(snapped - edge) < abs(best_dx)):
            best_dx, guide_x = snapped - edge, target
    best_dy, guide_y = None, None
    for edge in (y, y + h / 2, y + h):
        snapped, target = snap_value(edge, ys, threshold)
        if target is not None and (best_dy is None or abs(snapped - edge) < abs(best_dy)):
            best_dy, guide_y = snapped - edge, target
    if best_dx is not None:
        x += best_dx
        guides.append(("v", guide_x))
    elif grid:
        x = round(x / grid) * grid
    if best_dy is not None:
        y += best_dy
        guides.append(("h", guide_y))
    elif grid:
        y = round(y / grid) * grid
    return (x, y, w, h), guides


def overlaps(box, others):
    x, y, w, h = box
    return [i for i, (ox, oy, ow, oh) in enumerate(others)
            if x < ox + ow and ox < x + w and y < oy + oh and oy < y + h]
