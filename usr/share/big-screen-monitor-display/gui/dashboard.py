"""Home section: what the displays show right now, their real state and the
next useful action.

Every value comes from the service status file and the settings being
edited; with no display the preview is labelled DEMO and the rows say so.
"""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from bsmd import settings, themes  # noqa: E402
from bsmd.i18n import N_, _  # noqa: E402

from . import components as ui  # noqa: E402

STATE_TEXT = {"healthy": N_("Working"), "degraded": N_("Transient errors"), "recovering": N_("Reconnecting"),
              "disconnected": N_("Not connected"), "retrying": N_("Waiting for the display"),
              "failed": N_("Not responding"), "starting": N_("Starting"), "stopped": N_("Stopped")}
STATE_KIND = {"healthy": "success", "degraded": "warning", "recovering": "warning", "retrying": "warning",
              "starting": "accent", "failed": "error", "disconnected": "error", "stopped": "error"}
PROFILE_TEXT = {"auto": N_("Automatic"), "economy": N_("Economy"), "balanced": N_("Balanced"), "fluid": N_("Fluid")}
ORIENTATION_TEXT = {"horizontal": N_("Landscape"), "vertical": N_("Portrait"),
                    "horizontal_flipped": N_("Landscape, upside down"),
                    "vertical_flipped": N_("Portrait, upside down")}


def theme_title(theme_id):
    info = themes.REGISTRY.get(theme_id) or themes.REGISTRY["standard"]
    return _(info.name.split(" — ")[0])


def describe_display(status_display):
    """(name, model, resolution, connection) of one entry of status['displays']."""
    device = status_display.get("device") or {}
    source = status_display.get("source") or {}
    name = status_display.get("name") or device.get("model") or status_display.get("id")
    model = source.get("name") or device.get("model") or "—"
    resolution = f"{device['width']} × {device['height']}" if device.get("width") else "—"
    transport = {"usb": "USB", "serial": _("USB serial"), "memory": _("Simulated")}.get(source.get("transport"),
                                                                                       source.get("transport") or "—")
    where = source.get("usb_path") or source.get("port") or status_display.get("id")
    connection = f"{transport} · {where}" if where else transport
    return name, model, resolution, connection


class Dashboard:
    def __init__(self, window):
        self.window = window
        self.selected = None
        self._ids = []

        icon = Gtk.Image(icon_name="big-screen-monitor-display", pixel_size=64)
        title = Gtk.Label(label=_("Big Screen Monitor Display"), xalign=0, wrap=True)
        title.add_css_class("hero-title")
        tagline = Gtk.Label(label=_("Your hardware, your information, your style."), xalign=0, wrap=True)
        tagline.add_css_class("hero-tagline")
        tagline.add_css_class("dim-label")
        self.service_pill = ui.pill(_("Checking…"))
        self.service_pill.set_halign(Gtk.Align.START)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        texts.append(title)
        texts.append(tagline)
        texts.append(self.service_pill)
        hero = Gtk.Box(spacing=18)
        hero.append(icon)
        hero.append(texts)

        self.state_card = ui.StateCard()

        # An overview: 2 frames per second are enough (the theme pages show the real rate).
        self.preview = window.live_preview(None, _("What the display shows"), height=300, follow_display=True,
                                           max_fps=2)
        self.preview_holder = self.preview
        info = Adw.PreferencesGroup(title=_("Display"))
        self.display_combo = Gtk.DropDown(model=Gtk.StringList.new([]), valign=Gtk.Align.CENTER, visible=False,
                                          tooltip_text=_("Choose the display shown here"))
        ui.set_label(self.display_combo, _("Display shown"))
        self.display_combo.connect("notify::selected", self._on_display_chosen)
        info.set_header_suffix(self.display_combo)
        self.rows = {}
        for key, label in (("name", _("Name")), ("model", _("Model")), ("resolution", _("Resolution")),
                           ("connection", _("Connection")), ("theme", _("Theme")), ("state", _("State")),
                           ("profile", _("Performance"))):
            row = Adw.ActionRow(title=label, subtitle="—", subtitle_selectable=True)
            row.add_css_class("property")
            self.rows[key] = row
            info.add(row)
        self.state_pill = ui.pill("—")
        self.rows["state"].add_suffix(self.state_pill)
        main = ui.adaptive_split(self.preview, info, threshold=820)
        main_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_card.add_css_class("card")
        main_card.add_css_class("hero-card")
        main_card.append(main)

        actions_title = Gtk.Label(label=_("Quick actions"), xalign=0)
        actions_title.add_css_class("heading")
        tiles = Gtk.FlowBox(homogeneous=True, min_children_per_line=2, max_children_per_line=6,
                            selection_mode=Gtk.SelectionMode.NONE, column_spacing=12, row_spacing=12)
        tiles.set_max_children_per_line(5)
        for icon_name, label, callback in (
                ("view-grid-symbolic", _("Change theme"), lambda: window.show_section("themes")),
                ("video-display-symbolic", _("Display settings"), self._open_display),
                ("applications-graphics-symbolic", _("Kojiro Design Studio"), lambda: window.show_section("kojiro")),
                ("system-search-symbolic", _("Look for displays"), self._scan),
                ("utilities-system-monitor-symbolic", _("Diagnose"), window.diagnose)):
            tiles.append(ui.action_tile(icon_name, label, callback))
        self.brightness_group = Adw.PreferencesGroup()
        self.brightness_row = window._scale("brightness", _("Brightness"), 0, 100, 5,
                                            _("Default for every display; a display can override it."))
        self.brightness_group.add(self.brightness_row)

        content = ui.page_layout(hero, self.state_card, main_card, actions_title, tiles, self.brightness_group,
                                 maximum=1200)
        self.page = ui.navigation_page(_("Home"), content, tag="home")

    # ------------------------------------------------------------ actions
    def _open_display(self):
        self.window.show_section("displays")
        if self.selected:
            self.window.displays_page.open_display(self.selected)

    def _scan(self):
        self.window.displays_page.refresh(force=True, announce=True)

    def _on_display_chosen(self, combo, _pspec):
        index = combo.get_selected()
        if 0 <= index < len(self._ids) and self._ids[index] != self.selected:
            self.selected = self._ids[index]
            self.window.set_preview_display(self.preview, self.selected)
            self.update()

    # ------------------------------------------------------------ state
    def update(self):
        window = self.window
        status = window.status if window.service_fresh else None
        displays = (status or {}).get("displays") or []
        ids = [d["id"] for d in displays]
        if ids != self._ids:
            self._ids = ids
            names = [describe_display(d)[0] for d in displays]
            self.display_combo.set_model(Gtk.StringList.new(names))
            self.display_combo.set_visible(len(ids) > 1)
            if self.selected not in ids:
                self.selected = ids[0] if ids else None
                window.set_preview_display(self.preview, self.selected)
            if self.selected in ids:
                self.display_combo.set_selected(ids.index(self.selected))
        current = next((d for d in displays if d["id"] == self.selected), None)
        values = window.values
        if current:
            name, model, resolution, connection = describe_display(current)
            effective = settings.merged(values, current["id"])
            state = current.get("state")
            self.preview.set_badge(None)
            caps = current.get("capabilities") or {}
            self.brightness_row.set_sensitive(caps.get("brightness", True))
            self.brightness_row.set_subtitle(
                _("Default for every display; a display can override it.") if caps.get("brightness", True)
                else _("This display has no adjustable brightness."))
        else:
            name, model, resolution, connection = (_("No display connected"), "—", "—", "—")
            effective = values
            state = None
            width, height = window._device_size()
            self.preview.set_badge(_("DEMO · {w}×{h} preview").format(w=width, h=height), demo=True)
            self.brightness_row.set_sensitive(True)
        self.rows["name"].set_subtitle(GLib.markup_escape_text(name))
        self.rows["model"].set_subtitle(GLib.markup_escape_text(model))
        resolution_text = resolution
        if current:
            resolution_text += " · " + _(ORIENTATION_TEXT.get(effective.get("orientation"), "—"))
        self.rows["resolution"].set_subtitle(resolution_text)
        self.rows["connection"].set_subtitle(GLib.markup_escape_text(connection))
        theme_text = theme_title(effective.get("theme"))
        if effective.get("theme") != (current or {}).get("settings", {}).get("theme", effective.get("theme")):
            theme_text += " · " + _("not applied yet")
        self.rows["theme"].set_subtitle(theme_text)
        self.rows["profile"].set_subtitle(_(PROFILE_TEXT.get(effective.get("performance_profile"), "—")))
        if state:
            ui.set_pill(self.state_pill, _(STATE_TEXT.get(state, state)), STATE_KIND.get(state))
            stats = current.get("stats") or {}
            self.rows["state"].set_subtitle(_("{fps:.1f} frames per second").format(fps=stats.get("fps", 0))
                                            if state in ("healthy", "degraded") else "—")
        else:
            ui.set_pill(self.state_pill, _("Demonstration") if not current else "—", "accent")
            self.rows["state"].set_subtitle("—")
        self._update_service_pill(status)
        self._update_state_card(status, current)

    def _update_service_pill(self, status):
        if status is None:
            ui.set_pill(self.service_pill, _("Service stopped"), "error")
            return
        count = sum(1 for d in status.get("displays") or [] if d.get("connected"))
        if count:
            text = _("Service running · {count} display(s)").format(count=count)
            ui.set_pill(self.service_pill, text, "success" if status.get("state") == "healthy" else "warning")
        else:
            ui.set_pill(self.service_pill, _("Service running · waiting for a display"), "warning")

    def _update_state_card(self, status, current):
        window = self.window
        card = self.state_card
        if not os.path.exists(settings.config_path()) and not window.welcome_dismissed:
            card.show("accent", "big-screen-monitor-display",
                      _("Welcome!"),
                      _("Connect your USB display, choose a theme in the gallery and press Apply. "
                        "The display updates in about a second, without restarting anything."),
                      [(_("Choose a Theme"), lambda: window.show_section("themes")),
                       (_("Not now"), self._dismiss_welcome)])
            return
        if status is None:
            card.show("error", "dialog-error-symbolic", _("The monitor service is not running"),
                      _("Nothing is sent to the displays while it is stopped. Starting it needs an "
                        "administrator password."),
                      [(_("Start Service"), lambda: window._helper_action(["service", "start"],
                                                                         _("Service started."))),
                       (_("Diagnose"), window.diagnose)])
            return
        pending = status.get("pending") or []
        unknown = window.displays_page.unknown if hasattr(window, "displays_page") else []
        if pending or unknown:
            card.show("warning", "dialog-question-symbolic", _("A display needs your choice"),
                      _("A device was found but its model could not be identified with certainty. Choose the "
                        "model in My Displays; nothing is sent to it before that."),
                      [(_("Choose Model"), lambda: window.show_section("displays"))])
            return
        if not status.get("displays"):
            card.show("warning", "video-display-symbolic", _("No display connected"),
                      _("Connect the panel over USB. If it is already connected, try another cable or port and "
                        "look again."),
                      [(_("Look Again"), self._scan), (_("Diagnose"), window.diagnose)])
            return
        if current and current.get("state") in ("failed", "disconnected", "retrying"):
            card.show("error", "dialog-warning-symbolic", _("The display is not responding"),
                      _("The service keeps retrying on its own. You can reconnect it now or run the "
                        "diagnosis to find the cause."),
                      [(_("Reconnect"), lambda: window.displays_page.command(
                          {"action": "reconnect", "display": current["id"]})),
                       (_("Diagnose"), window.diagnose)])
            return
        if status.get("stalled") or (current and current.get("state") == "degraded"):
            card.show("warning", "dialog-warning-symbolic", _("Transient communication errors"),
                      _("The display works, but some transfers failed and were repeated."),
                      [(_("Diagnose"), window.diagnose)])
            return
        card.hide()

    def _dismiss_welcome(self):
        self.window.welcome_dismissed = True
        self.state_card.hide()
