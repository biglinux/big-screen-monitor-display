"""Theme thumbnails for the tray gallery, drawn by the real theme engine.

Runs as a short-lived, low-priority child process so that the tray itself never
loads Pillow, numpy and the themes: ``python3 -m traykit.thumbs`` reads a JSON
job on stdin ({"size": [w, h], "out": dir, "items": [{"key", "theme", "values"}]})
and prints ``done <key>`` (or ``fail <key>``) per thumbnail written as
``<out>/<key>.png``.
"""

import json
import os
import sys

THUMB = (240, 160)


def render(theme_id, values, size):
    from bsmd import runtime, themes
    ctx = runtime.RenderContext(preview=True)
    theme = themes.create(theme_id, ctx)
    try:
        image = themes.render_for_panel(theme, size[0], size[1], dict(values, theme=theme_id), ctx)
    finally:
        theme.close()
    image.thumbnail(THUMB)
    return image


def _sample_telemetry():
    """Real values in the thumbnails (one sample, deltas over a short pause)."""
    import time
    try:
        from bsmd import telemetry
        collector = telemetry.Collector()
        collector.prime()
        time.sleep(0.25)
        collector.sample_once()
    except Exception:  # noqa: BLE001 - thumbnails without numbers are still useful
        pass


def main():
    try:
        os.nice(10)
    except OSError:
        pass
    job = json.load(sys.stdin)
    from bsmd import control, i18n
    base = control.load_settings()
    i18n.set_language(base.get("language", "auto"))
    _sample_telemetry()
    size = tuple(int(v) for v in job.get("size", (480, 320)))[:2]
    out = job["out"]
    os.makedirs(out, exist_ok=True)
    for item in job.get("items", []):
        key = item["key"]
        target = os.path.join(out, f"{key}.png")
        try:
            values = dict(base, **(item.get("values") or {}))
            image = render(item["theme"], values, size)
            tmp = target + ".tmp"
            image.save(tmp, "PNG")
            os.replace(tmp, target)
            print(f"done {key}", flush=True)
        except Exception as error:  # noqa: BLE001 - one broken theme must not stop the others (reported)
            print(f"fail {key} {type(error).__name__}: {error}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
