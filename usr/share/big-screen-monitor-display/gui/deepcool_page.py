"""DeepCool coolers in 'My Displays': card text, face preview and the detail page.

DeepCool coolers are telemetry devices: the firmware draws fixed fields from
numbers the service sends. Nothing here renders a theme for them. The preview
is a drawing of the cooler's face from the last values the service sent
(``status.metrics``); without the service it shows sample values marked DEMO.
"""

import grp
import json
import os
import stat
import time
import types

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from bsmd import settings, themes  # noqa: E402
from bsmd.displays.deepcool import conflicts, metrics, models, preview  # noqa: E402
from bsmd.displays.deepcool.models import FREQ, METRIC_LABELS, TEMP  # noqa: E402
from bsmd.i18n import N_, _  # noqa: E402
from gui import components as ui  # noqa: E402

PREVIEW_SIZE = (480, 300)
DEMO_VALUES = metrics.Values(temp=52.0, usage=23.0, power=65.0, freq=4200.0, ram=41.0, gpu_temp=48.0)
DISPLAY_TYPE = {"segment": N_("Numeric display"), "lcd": N_("LCD screen (information mode)")}
COMPAT_KIND = {"native": "success", "adapted": "accent", "partial": "warning", "unsupported": "error"}
INTERVALS = (("0.5", N_("Every 0.5 s")), ("1", N_("Every second (recommended)")), ("2", N_("Every 2 s")),
             ("3", N_("Every 3 s")), ("5", N_("Every 5 s")))
ROTATIONS = (("0", N_("Normal")), ("90", N_("90°")), ("180", N_("180°")), ("270", N_("270°")))
GROUP = "big-screen-monitor"


def family_of(entry, own):
    """DeepCool family of a display entry, or None for any other display."""
    ids = [((entry.status or {}).get("source") or {}).get("profile"), own.get("profile")]
    if entry.candidate and entry.candidate.best:
        ids.append(entry.candidate.best.profile.id)
    for profile_id in ids:
        if profile_id in models.FAMILIES:
            return models.FAMILIES[profile_id]
    return None


def live_metrics(entry):
    """The last frame the service sent to this cooler, if it is running it."""
    status = entry.status or {}
    if status.get("state") not in ("healthy", "degraded"):
        return None
    return status.get("metrics") or None


def frame_for(family, effective, entry):
    """(Frame, demo) for the preview: the service's last frame, else sample values."""
    data = live_metrics(entry)
    if data:
        return metrics.Frame(data.get("family", family.id), dict(data.get("fields") or {}), data.get("main"),
                             bool(data.get("alarm")), bool(data.get("fahrenheit")), tuple(data.get("missing") or ()),
                             data.get("preset", "essentials"), data.get("source_theme")), False
    return metrics.build_frame(family, effective, DEMO_VALUES, time.monotonic()), True


def mode_text(effective):
    preset, theme = metrics.preset_for(effective)
    name = _(metrics.PRESETS[preset][0])
    if theme:
        info = themes.REGISTRY.get(theme)
        return _("{preset} (from {theme})").format(preset=name, theme=_(info.name.split(" — ")[0]) if info else theme)
    return name


def compatibility_text(family, effective):
    state, text = metrics.compatibility(family, effective.get("theme", "standard"))
    return state, _(metrics.COMPATIBILITY[state]), _(text) if text else ""


def card_subtitle(family, effective, state):
    return " · ".join((state, _(DISPLAY_TYPE[family.display]), mode_text(effective)))


def card_tooltip(family, entry, effective):
    _state, label, _text = compatibility_text(family, effective)
    product = entry.candidate.device.product if entry.candidate else ""
    pid = entry.candidate.device.pid if entry.candidate else None
    lines = [models.model_name(pid, product) if pid is not None else family.name, "DeepCool",
             _(DISPLAY_TYPE[family.display]), family.protocol,
             ", ".join(_(METRIC_LABELS[m]) for m in family.fields),
             _("Compatibility with the theme: {state}").format(state=label)]
    return "\n".join(lines)


def thumbnail_work(family, effective, entry):
    frame, demo = frame_for(family, effective, entry)
    return lambda: preview.render(family, frame, PREVIEW_SIZE, demo=demo)


def face_renderer(window, display_id):
    """Preview callable for a cooler the service drives (dashboard), or None for other displays."""
    status = next((d for d in (window.status or {}).get("displays") or [] if d.get("id") == display_id), None)
    if status is None:
        return None
    entry = types.SimpleNamespace(id=display_id, status=status, candidate=None)
    family = family_of(entry, {})
    if family is None:
        return None

    def draw():
        current = next((d for d in (window.status or {}).get("displays") or [] if d.get("id") == display_id),
                       status)
        entry.status = current
        frame, demo = frame_for(family, settings.merged(window.values, display_id), entry)
        return preview.render(family, frame, PREVIEW_SIZE, demo=demo)
    return draw


def node_access(path):
    """Human description of who may open a device node (no device is opened)."""
    if not path:
        return _("No HID node found for this cooler.")
    try:
        info = os.stat(path)
    except OSError as error:
        return f"{path}: {error.strerror}"
    try:
        group = grp.getgrgid(info.st_gid).gr_name
    except KeyError:
        group = str(info.st_gid)
    mode = stat.filemode(info.st_mode)
    text = f"{path} · {mode} · {_('group')} {group}"
    if group != GROUP:
        text += "\n" + _("The service group has no access: reinstall the package or replug the cooler so the udev "
                         "rule applies.")
    return text


class DeepCoolDetail:
    """Detail page of one DeepCool cooler (built by DisplaysPage)."""

    def __init__(self, displays_page, entry, family):
        self.owner = displays_page
        self.window = displays_page.window
        self.entry = entry
        self.family = family
        self.display_id = entry.id
        self.page = self._build()

    # ------------------------------------------------------------ helpers
    def _effective(self):
        return settings.merged(self.window.values, self.display_id)

    def _set(self, key, value):
        self.owner._set(self.display_id, key, value)
        self._refresh_preview()
        self._update_mode_rows()

    def _info_row(self, group, title, subtitle="—", lines=0):
        row = Adw.ActionRow(title=title, subtitle=subtitle, subtitle_selectable=True)
        row.add_css_class("property")
        if lines:
            row.set_subtitle_lines(lines)
        group.add(row)
        return row

    # ------------------------------------------------------------ build
    def _build(self):
        family, entry, display_id = self.family, self.entry, self.display_id
        own = self.owner._entry_settings(display_id)
        effective = self._effective()
        combo = self.owner._combo
        title = own.get("name") or entry.title

        self.preview = ui.DisplayPreview(_("{name} display face").format(name=title), height=300,
                                         ratio=PREVIEW_SIZE[0] / PREVIEW_SIZE[1])
        self.preview.set_caption(_("A drawing of what the cooler shows, from the values the service sends. "
                                   "The cooler draws its own digits: no image is sent to it."))

        window = self.window
        window._loading, loading = True, window._loading
        try:
            identity = Adw.PreferencesGroup(title=_("This cooler"))
            name = Adw.EntryRow(title=_("Name"), text=own.get("name", ""), show_apply_button=True)
            name.connect("apply", lambda r: self.owner._set(display_id, "name", r.get_text().strip()[:40] or None))
            identity.add(name)
            enabled = Adw.SwitchRow(title=_("Use this cooler"), active=own.get("enabled", True))
            enabled.connect("notify::active", lambda r, _p: self.owner._set(display_id, "enabled",
                                                                            None if r.get_active() else False))
            identity.add(enabled)
            device = entry.candidate.device if entry.candidate else None
            self._info_row(identity, _("Model"), models.model_name(device.pid, device.product) if device
                           else entry.title)
            self._info_row(identity, _("Maker"), "DeepCool")
            self._info_row(identity, _("Display type"), _(DISPLAY_TYPE[family.display]))
            self._info_row(identity, _("Protocol"), family.protocol, lines=3)
            if family.notes:
                self._info_row(identity, _("About this model"), "\n".join(_(note) for note in family.notes), lines=6)
            self._info_row(identity, _("Metrics shown"), ", ".join(_(METRIC_LABELS[m]) for m in family.fields))
            self.compat_row = self._info_row(identity, _("Compatibility with the theme"), lines=4)
            self.compat_pill = ui.pill("—")
            self.compat_row.add_suffix(self.compat_pill)
            matrix = Adw.ExpanderRow(title=_("Compatibility with every theme"),
                                     subtitle=_("How each theme is represented on this cooler"))
            for info in themes.available():
                state, text = metrics.compatibility(family, info.id)
                row = Adw.ActionRow(title=GLib.markup_escape_text(_(info.name.split(" — ")[0])),
                                    subtitle=GLib.markup_escape_text(_(text) if text else "—"))
                row.set_subtitle_lines(4)
                row.add_suffix(ui.pill(_(metrics.COMPATIBILITY[state]), COMPAT_KIND.get(state)))
                matrix.add_row(row)
            identity.add(matrix)

            # Display: what the field(s) show.
            show = Adw.PreferencesGroup(title=_("Display"))
            theme_options = [(info.id, _(info.name.split(" — ")[0])) for info in themes.available()]
            show.add(combo(_("Theme"), theme_options, effective.get("theme", "standard"),
                           lambda value: self._set("theme", value),
                           _("With \"Follow the theme\", the cooler shows what best represents it.")))
            preset_options = [("auto", _("Follow the theme"))] + [(key, _(label)) for key, (label, _d) in
                                                                  metrics.PRESETS.items()]
            self.preset_row = combo(_("Presentation"), preset_options, own.get("dc_preset", "auto"),
                                    lambda value: self._set("dc_preset", None if value == "auto" else value))
            show.add(self.preset_row)
            self.mode_row = self._info_row(show, _("Showing now"), lines=3)
            self.main_row = None
            if family.layout == "single":
                choices = [("auto", _("Alternate every 5 seconds"))] + [(m, _(METRIC_LABELS[m]))
                                                                       for m in family.main_choices]
                self.main_row = combo(_("Configurable field"), choices, own.get("dc_main", "auto"),
                                      lambda value: self._set("dc_main", None if value == "auto" else value),
                                      _("Used by the CPU Custom presentation. A value the computer cannot "
                                        "measure is never shown."))
                show.add(self.main_row)
            else:
                self._info_row(show, _("Fields"), _("This cooler always shows {fields}; the presentation does not "
                                                    "change them.").format(
                    fields=", ".join(_(METRIC_LABELS[m]) for m in family.fields)), lines=3)

            # CPU information.
            cpu = Adw.PreferencesGroup(title=_("CPU information"))
            if family.fahrenheit and TEMP in family.fields:
                cpu.add(combo(_("Temperature unit"), [("c", _("Celsius (°C)")), ("f", _("Fahrenheit (°F)"))],
                              own.get("dc_temp_unit", "c"),
                              lambda value: self._set("dc_temp_unit", None if value == "c" else value)))
            if FREQ in family.fields:
                cpu.add(combo(_("Frequency"), [("max", _("Fastest core")), ("average", _("Average of all cores"))],
                              own.get("dc_freq_source", "max"),
                              lambda value: self._set("dc_freq_source", None if value == "max" else value)))
            self.values_row = self._info_row(cpu, _("Current values"), lines=6)

            # Alerts.
            alerts = Adw.PreferencesGroup(title=_("Alerts"))
            if family.software_alarm:
                alarm = Adw.SwitchRow(title=_("Temperature alarm"),
                                      subtitle=_("Lights the cooler's alarm indicator at the threshold."),
                                      active=own.get("dc_alarm", True))
                alarm.connect("notify::active", lambda r, _p: self._set("dc_alarm", None if r.get_active() else False))
                alerts.add(alarm)
                threshold = Adw.SpinRow.new_with_range(60, 100, 1)
                threshold.set_title(_("Alarm threshold (°C)"))
                threshold.set_value(own.get("dc_alarm_temp", 90))
                threshold.connect("notify::value", lambda r, _p: self._set(
                    "dc_alarm_temp", None if int(r.get_value()) == 90 else int(r.get_value())))
                alerts.add(threshold)
            if family.firmware_alarm:
                self._info_row(alerts, _("Firmware alarm"), _("Built into the cooler: {limits}. It stays active "
                                                              "and is never changed by this program.").format(
                    limits=family.firmware_alarm), lines=3)
            if not family.software_alarm and not family.firmware_alarm:
                self._info_row(alerts, _("Alarm"), _("This cooler has no alarm indicator."))

            # Performance.
            performance = Adw.PreferencesGroup(title=_("Performance"))
            performance.add(combo(_("Update interval"), [(k, _(v)) for k, v in INTERVALS],
                                  own.get("dc_interval", "1"),
                                  lambda value: self._set("dc_interval", None if value == "1" else value),
                                  _("Each update is one small USB packet; faster updates use a little more CPU.")))
            self.transfer_row = self._info_row(performance, _("Updates"))

            # Advanced.
            advanced = Adw.PreferencesGroup(title=_("Advanced"))
            if family.id == "deepcool_mystique":
                advanced.add(combo(_("Screen rotation"), [(k, _(v)) for k, v in ROTATIONS],
                                   own.get("dc_rotation", "0"),
                                   lambda value: self._set("dc_rotation", None if value == "0" else value)))
            if family.id == "deepcool_ld":
                zeros = Adw.SwitchRow(title=_("Leading zeros"), subtitle=_("Shows 045 instead of 45."),
                                      active=own.get("dc_lead_zeros", True))
                zeros.connect("notify::active", lambda r, _p: self._set("dc_lead_zeros",
                                                                        None if r.get_active() else False))
                advanced.add(zeros)
            options = [("auto", _("Automatic ({model})").format(model=family.name))] + [
                (f.id, f.name) for f in models.FAMILIES.values()]
            advanced.add(combo(_("Model / protocol"), options, own.get("profile", "auto"),
                               lambda value: self.owner._model_changed(display_id, value),
                               _("Choose manually only if detection is wrong.")))
            self.reconnect = Adw.ActionRow(title=_("Reconnect"), subtitle=_("Closes and reopens this cooler only"),
                                           activatable=True)
            self.reconnect.add_prefix(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
            self.reconnect.connect("activated", lambda *_: self.owner.command({"action": "reconnect",
                                                                                "display": display_id}))
            advanced.add(self.reconnect)

            # Diagnostics.
            diagnostics = Adw.PreferencesGroup(title=_("Diagnostics"))
            copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text=_("Copy the diagnostics"),
                              valign=Gtk.Align.CENTER)
            copy.add_css_class("flat")
            ui.set_label(copy, _("Copy the diagnostics"))
            copy.connect("clicked", lambda _b: self._copy_diagnostics())
            diagnostics.set_header_suffix(copy)
            self.diag = {}
            for key, label in (("state", _("State")), ("usb", _("USB")), ("access", _("Permissions")),
                               ("sources", _("Sensors")), ("missing", _("Unavailable values")),
                               ("conflicts", _("Other DeepCool programs")), ("updated", _("Last update")),
                               ("validation", _("Validation"))):
                self.diag[key] = self._info_row(diagnostics, label, lines=6)
            self.state_pill = ui.pill("—")
            self.diag["state"].add_suffix(self.state_pill)
        finally:
            window._loading = loading

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        for group in (identity, show):
            side.append(group)
        lower = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        for group in (cpu, alerts, performance, diagnostics, advanced):
            lower.append(group)
        content = ui.page_layout(ui.adaptive_split(self.preview, side), lower, maximum=1400)
        page = ui.navigation_page(title, content, tag=f"display-{display_id}")
        page.deepcool = self
        self._conflicts = None
        self._check_conflicts()
        self._update_mode_rows()
        self._refresh_preview()
        return page

    # ------------------------------------------------------------ updates
    def _check_conflicts(self):
        self.window.worker.submit("deepcool-conflicts", conflicts.find_conflicts,
                                  lambda result, error: self._conflicts_found(result if error is None else None))

    def _conflicts_found(self, found):
        self._conflicts = found or []
        if found:
            lines = []
            for item in found:
                if item["kind"] == "unit":
                    state = _("enabled") if item.get("enabled") else _("installed")
                    lines.append(f"{item['name']} ({state}) — " + _(conflicts.HINT).format(unit=item["name"]))
                else:
                    lines.append(_("{name} is running (process {pid}, {project}). Close it before using the "
                                   "cooler here.").format(**item))
            text = "\n".join(lines) + "\n" + _("Nothing was stopped: you decide.")
        else:
            text = _("None found.")
        self.diag["conflicts"].set_subtitle(GLib.markup_escape_text(text))

    def _update_mode_rows(self):
        effective = self._effective()
        preset, _theme = metrics.preset_for(effective)
        if self.main_row is not None:
            self.main_row.set_sensitive(preset == "custom")
        description = metrics.PRESETS[preset][1]
        self.mode_row.set_subtitle(GLib.markup_escape_text(f"{mode_text(effective)} — {_(description)}"))
        state, label, text = compatibility_text(self.family, effective)
        ui.set_pill(self.compat_pill, label, COMPAT_KIND.get(state))
        self.compat_row.set_subtitle(GLib.markup_escape_text(text or "—"))

    def _refresh_preview(self):
        frame, demo = frame_for(self.family, self._effective(), self.entry)
        image = preview.render(self.family, frame, PREVIEW_SIZE, demo=False)
        self.preview.picture.set_paintable(ui.texture_from_image(image))
        self.preview.set_badge(_("DEMO · sample values") if demo else _("Live"), demo=demo)
        self.frame = frame

    def update(self, entry, state_text, kind):
        self.entry = entry
        status = entry.status or {}
        data = live_metrics(entry) or {}
        ui.set_pill(self.state_pill, state_text, kind)
        self.diag["state"].set_subtitle(_("for {seconds:.0f} s").format(seconds=status.get("state_since_s", 0))
                                        if status else _("The service is not driving this cooler."))
        candidate = entry.candidate
        details = ((status.get("device") or {}).get("details") or {})
        hidraw = details.get("hidraw") or (candidate.device.hidraws[0] if candidate and candidate.device.hidraws
                                           else "")
        usb = []
        if candidate:
            usb.append(_("USB {ids} at port {path}").format(ids=candidate.device.ids, path=candidate.device.path))
            if candidate.device.product:
                usb.append(_("product \"{name}\"").format(name=candidate.device.product))
        if hidraw:
            usb.append(hidraw)
        if details.get("se_variant"):
            usb.append(_("SE variant (no report id)"))
        self.diag["usb"].set_subtitle(GLib.markup_escape_text(" · ".join(usb) or _("Not connected")))
        if self.family.transport == "hid":
            self.diag["access"].set_subtitle(GLib.markup_escape_text(node_access(hidraw)))
        else:
            self.diag["access"].set_subtitle(_("USB device {path}: access granted to the service group by the "
                                               "package's udev rule.").format(
                path=candidate.device.path if candidate else "—"))
        sources = []
        if data.get("temp_source"):
            sources.append(_("Temperature: {source}").format(source=data["temp_source"]))
        if data.get("power_source"):
            sources.append(_("Power: {source} ({status})").format(source=data["power_source"],
                                                                 status=data.get("power_status") or "—"))
        self.diag["sources"].set_subtitle(GLib.markup_escape_text("\n".join(sources) or "—"))
        reasons = data.get("reasons") or {}
        missing = [f"{_(METRIC_LABELS[m])}: {_(r)}" for m, r in reasons.items()
                   if m in METRIC_LABELS and m in self.family.fields]
        if data.get("missing"):
            missing.append(_("Sent as 0 because the cooler has no blank value: {fields}").format(
                fields=", ".join(_(METRIC_LABELS[m]) for m in data["missing"] if m in METRIC_LABELS)))
        self.diag["missing"].set_subtitle(GLib.markup_escape_text("\n".join(missing) or _("None")))
        updated = data.get("updated")
        self.diag["updated"].set_subtitle(_("{seconds:.0f} s ago").format(seconds=max(0, time.time() - updated))
                                          if updated else "—")
        model = models.model_for(candidate.device.pid) if candidate else None
        validation = _("B — implemented from documented protocols and verified against reference data; not yet "
                       "tested on a real cooler by this project.")
        if model is not None:
            validation += "\n" + _("Reference projects: {state}").format(state=model.community)
        self.diag["validation"].set_subtitle(GLib.markup_escape_text(validation))
        stats = status.get("stats") or {}
        self.transfer_row.set_subtitle(
            _("{sent} updates · {ms:.1f} ms per update · {recoveries} recoveries").format(
                sent=stats.get("frames_sent", 0), ms=stats.get("transfer_ms", 0),
                recoveries=status.get("recoveries", 0)) if status else "—")
        self.reconnect.set_sensitive(bool(status))
        self._update_values(data)
        self._update_mode_rows()
        self._refresh_preview()

    def _update_values(self, data):
        fields = data.get("fields") or {}
        if not data:
            self.values_row.set_subtitle(_("Shown when the service is driving the cooler."))
            return
        lines = []
        for metric in self.family.fields:
            value = fields.get(metric)
            if value is None or metric in (data.get("missing") or ()):
                lines.append(f"{_(METRIC_LABELS[metric])}: —")
                continue
            unit = ("°F" if data.get("fahrenheit") else "°C") if metric == TEMP else models.METRIC_UNITS[metric]
            lines.append(f"{_(METRIC_LABELS[metric])}: {value:.0f} {unit}")
        if data.get("main"):
            lines.append(_("On the field now: {metric}").format(metric=_(METRIC_LABELS[data["main"]])))
        self.values_row.set_subtitle(GLib.markup_escape_text("\n".join(lines)))

    def diagnostics_text(self):
        report = {"model": self.family.name, "family": self.family.id,
                  "protocol": self.family.protocol, "validation": "B",
                  "settings": {k: v for k, v in self._effective().items() if k.startswith("dc_") or k == "theme"},
                  "status": {k: (self.entry.status or {}).get(k) for k in ("state", "source", "device", "stats",
                                                                           "metrics", "recoveries")},
                  "conflicts": self._conflicts}
        if self.entry.candidate:
            report["usb"] = self.entry.candidate.describe()
        for key, row in self.diag.items():
            report.setdefault("rows", {})[key] = row.get_subtitle()
        return json.dumps(report, indent=2, ensure_ascii=False, default=str)

    def _copy_diagnostics(self):
        Gdk.Display.get_default().get_clipboard().set(self.diagnostics_text())
        self.window.toast(_("Diagnostics copied."))


def unsupported_rows(devices):
    """(title, subtitle) for DeepCool devices this program identifies but does not drive."""
    rows = []
    for device in devices:
        if device.vid != models.VENDOR or models.family_for(device.pid) is not None:
            continue
        model = models.model_for(device.pid)
        note = _(model.note) if model and model.note else _("Unknown DeepCool device.")
        rows.append((models.model_name(device.pid, device.product),
                     f"{device.ids} · {note} " + _("Nothing is sent to it.")))
    return rows

