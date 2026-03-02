# PLANNING.md — Project Improvement Roadmap

## Files Analyzed
**Total files read:** 2  
**Total lines analyzed:** 1629  
**Large files (>500 lines) confirmed read in full:** 
- `main.py` (1266 lines) - Confirmed read all lines.

## Current State Summary
The project works visually and utilizes a GTK4 UI with python-usb. However, it requires architectural decoupling, has high cyclomatic complexity (Radon F/D grades), blocks the GTK UI thread with synchronous subprocesses, and lacks test coverage. Accessibility (Orca) is fundamentally flawed because interactive widgets in complex layouts (like `Gtk.Scale`) lack accessible name relations.

## Critical (fix immediately)
- [ ] Create Test Suite: Project currently lacks tests. Need to create a test suite (pytest).
- [ ] UI Thread Blocking: `config_gui.py:269/300` — `subprocess.run` blocks the GTK main loop. → Use `GLib.Thread` or async approach so the UI doesn't freeze.
- [ ] Backend Efficiency: `main.py:309` — spawning `sensors` via `subprocess.check_output` every 1 second in a loop causes high load. → Replace with `psutil.sensors_temperatures()`.
- [ ] Notification Anti-Pattern: `config_gui.py:308` — Usage of `AdwToastOverlay` directly violates GTK HIG. → Replace with alternative inline feedback (e.g., changing Save button state or using an inline `Gtk.InfoBar`/label).
- [ ] Thread Safety: `main.py:254` — `monitor_thread` writes to global `SYSTEM_STATS` dict while `render_dashboard` reads it concurrently. → Protect with `threading.Lock()`.

## High Priority (code quality)
- [ ] Bare Excepts: `main.py:73, 209, 388, etc.` and `config_gui.py:285` — 14 instances of `except:` that mask bugs. → Change to `except Exception as e:` and pass or log.
- [ ] Subprocess Error Handling: `main.py:215` — `lspci` command without timeouts/error handling. → Add timeout.
- [ ] Unused Variables/Imports: Clean up Vulture & Ruff unused items (`GLib`, `font_lg`, etc.).
- [ ] Deprecated Image Methods: `main.py:806, 1118` — `Image.ANTIALIAS` is removed in newer Pillow. → Standardize cleanly on `Image.Resampling.LANCZOS`.

## Medium Priority (UX improvements)  
- [ ] Destructive Actions without Confirmation: `config_gui.py:235` — "Restaurar Padrões" alters settings instantly without confirmation. → Add a confirmation dialog before resetting settings.
- [ ] Cognitive Load: Max 5-7 elements. 

## Low Priority (polish & optimization)
- [ ] SVG Rendering: Pre-render/cache `rsvg-convert` outputs faster or remove sync calls in hot loops.

## Architecture Recommendations
Move `monitor_thread` and data polling logic into a separate module (`hw_monitor.py`) to reduce `main.py` cyclomatic complexity. However, for a quick fix, we will just reduce the inline complexity of `render_dashboard`.

## UX Recommendations
- **Forgiving design**: Provide an explicitly cancelable action for `Restore Defaults` so users feel safe. 
- **Feedback loops**: Give immediate visual confirm to the user via checkmarks or label changes instead of Toasts.
- **Language**: Translate tech labels to more user-friendly labels where appropriate.

## Orca Screen Reader Compatibility
**Issues found:**
- [ ] `Gtk.Scale`: `config_gui.py:116` — Orca announces sliding bar but doesn't map it to "Brilho". → `self.scale_brightness.update_property([Gtk.AccessibleProperty.LABEL], [GLib.Variant('s', "Brilho")])` or explicitly set its property.
- [ ] `Gtk.MenuButton`: `config_gui.py:196` — Orca reads nothing but "button" (tooltip isn't always reliable). → Assign an accessible label "Menu Principal".
- [ ] `Gtk.Image`: `config_gui.py:67` — Logo image could confuse Orca. → Mark it as `Gtk.AccessibleRole.PRESENTATION`.

**Test checklist for manual verification:**
- [ ] Launch app with Orca running (`orca &; ./app`)
- [ ] Navigate entire UI using only Tab/Shift+Tab
- [ ] Verify Orca announces every button, field, and state change
- [ ] Test form submission flow without looking at screen
- [ ] Verify error messages are announced by Orca

## Accessibility Checklist (General)
- [ ] All interactive elements have accessible labels
- [ ] Keyboard navigation works for all flows
- [ ] Color is never the only indicator
- [ ] Text is readable at 2x font size
- [ ] Focus indicators are visible

## Tech Debt
- Radon F/D scores: Refactor `render_dashboard_landscape` into smaller helpers.
- Ruff: 27 violations (fix linting).

## Metrics (before)
- Total files: 2
- Total lines: 1629
- Ruff issues: 27
- Vulture warnings: 2 (in project)
- Radon C+ grades: 6
