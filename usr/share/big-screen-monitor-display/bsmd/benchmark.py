"""Rendering and encoding benchmark (``main.py --benchmark``).

Measures, on this machine, what each panel family costs per frame: theme
rendering, pixel conversion (RGB565, BGRA, PNG/JPEG) and how much of a
frame partial updates actually send. Link times are *estimates* derived from
typical throughput figures (docs/16-benchmarks.md); only real hardware can
confirm them, so the report labels them as such.
"""

import platform
import statistics
import time

from . import frames, telemetry, themes
from .displays import turing_usb

# Landscape sizes of the supported families (and the simulator extremes).
DEFAULT_SIZES = ("160x80", "480x320", "480x480", "800x480", "1024x600", "1280x720", "1920x480")
# Rough effective throughput (bytes/s) per link, for estimates only.
LINKS = {
    "serial (Turing A / WeAct / Kipye)": ("rgb565", 1_000_000),
    "serial (Turing C, BGRA)": ("bgra", 1_000_000),
    "usb (AX206)": ("rgb565", 6_700_000),          # measured: 768 KB in ~115 ms (docs/05)
    "usb (Turing USB, PNG/JPEG)": ("png", 8_000_000),
}


def _ms(samples):
    return round(statistics.median(samples) * 1000, 2) if samples else None


def _time(func, repeat=3):
    samples = []
    result = None
    for _ in range(repeat):
        start = time.perf_counter()
        result = func()
        samples.append(time.perf_counter() - start)
    return samples, result


def bench_size(size, theme_ids, frames_per_theme):
    from .runtime import RenderContext
    from .settings import defaults
    width, height = size
    settings = defaults()
    result = {"size": f"{width}x{height}", "themes": {}, "encoding": {}}
    last = None
    for theme_id in theme_ids:
        ctx = RenderContext(preview=True)
        theme = themes.create(theme_id, ctx)
        render_times, changed = [], []
        previous_key = None
        for _ in range(frames_per_theme):
            start = time.perf_counter()
            image = theme.render(width, height, dict(settings, theme=theme_id), ctx)
            render_times.append(time.perf_counter() - start)
            key = frames.image_key(image)
            rects = frames.plan_rects(key, previous_key, 32, 16, 24)
            if previous_key is not None:
                area = width * height if rects is None else sum(map(frames.rect_area, rects))
                changed.append(area / (width * height))
            previous_key = key
            last = image
        theme.close()
        result["themes"][theme_id] = {"render_ms": _ms(render_times[1:] or render_times),
                                      "first_frame_ms": round(render_times[0] * 1000, 1),
                                      "changed_fraction": round(statistics.mean(changed), 3) if changed else None}
    if last is None:
        return result
    encoding = result["encoding"]
    samples, rgb565 = _time(lambda: frames.image_to_rgb565(last, "<").tobytes())
    encoding["rgb565_ms"], encoding["rgb565_bytes"] = _ms(samples), len(rgb565)
    samples, bgra = _time(lambda: frames.image_to_bgra(last))
    encoding["bgra_ms"], encoding["bgra_bytes"] = _ms(samples), len(bytes(bgra))
    samples, (_cmd, png) = _time(lambda: turing_usb.encode_frame(last), repeat=2)
    encoding["png_or_jpeg_ms"], encoding["png_or_jpeg_bytes"] = _ms(samples), len(png)
    samples, _ = _time(lambda: turing_usb.encrypt_header(turing_usb.command_header(102)))
    encoding["usb_header_ms"] = _ms(samples)
    estimates = {}
    for link, (kind, throughput) in LINKS.items():
        payload = {"rgb565": len(rgb565), "bgra": len(bytes(bgra)), "png": len(png)}[kind]
        seconds = payload / throughput
        estimates[link] = {"full_frame_ms_estimated": round(seconds * 1000, 1),
                           "max_full_fps_estimated": round(1 / seconds, 1) if seconds else None}
    result["links"] = estimates
    return result


def run(sizes=None, themes_=None, frames=6):
    collector = telemetry.Collector()
    collector.prime()
    collector.sample_once()
    sizes = [tuple(int(v) for v in text.lower().split("x")) for text in (sizes or DEFAULT_SIZES)]
    theme_ids = list(themes_ or ("standard", "gkrellm", "planet", "old_computer", "brother_away"))
    return {"machine": {"python": platform.python_version(), "cpu": platform.processor() or platform.machine()},
            "frames_per_theme": frames,
            "results": [bench_size(size, theme_ids, frames) for size in sizes],
            "note": ("link times are estimates from nominal throughput (panel-side decoding and firmware limits "
                     "not included); validate on real hardware")}


def format_report(report):
    lines = [f"Python {report['machine']['python']} on {report['machine']['cpu']}, "
             f"{report['frames_per_theme']} frames per theme", ""]
    for result in report["results"]:
        lines.append(f"== {result['size']}")
        for theme_id, data in result["themes"].items():
            changed = data["changed_fraction"]
            lines.append(f"   {theme_id:<14} render {data['render_ms']:>7} ms   first {data['first_frame_ms']:>7} ms"
                         f"   changed/frame {'-' if changed is None else f'{changed:.0%}'}")
        enc = result.get("encoding") or {}
        if enc:
            lines.append(f"   encode: RGB565 {enc['rgb565_ms']} ms ({enc['rgb565_bytes']} B), "
                         f"BGRA {enc['bgra_ms']} ms ({enc['bgra_bytes']} B), "
                         f"PNG/JPEG {enc['png_or_jpeg_ms']} ms ({enc['png_or_jpeg_bytes']} B), "
                         f"USB header {enc['usb_header_ms']} ms")
        for link, estimate in (result.get("links") or {}).items():
            lines.append(f"   {link:<34} full frame ~{estimate['full_frame_ms_estimated']} ms "
                         f"(~{estimate['max_full_fps_estimated']} fps, estimated)")
        lines.append("")
    lines.append(report["note"])
    return "\n".join(lines)
