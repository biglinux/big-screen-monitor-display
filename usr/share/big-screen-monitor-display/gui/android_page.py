"""Android phones and tablets in "My Displays".

* group below the gallery: switches for network and USB connections, pairing
  requests waiting for an answer (code shown on both screens), paired devices
  (remove) and "Add Android…";
* "Add Android" dialog: a QR code the phone's camera opens in the app (the
  computer's certificate fingerprint and a single-use secret valid for a few
  minutes; no permanent credential), plus the manual way;
* rows on an Android display's own page (picture quality, drawing size,
  rotation, screen options, touch, media controls, remove pairing).

The pairing secret is generated here and reaches the service only through
the root-owned command spool (bsm-helper display-command); it is never
written to the world-readable status file.
"""

import secrets
import threading
import time
import urllib.parse

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from bsmd.displays.android import protocol as bsdp  # noqa: E402
from bsmd.i18n import N_, _  # noqa: E402
from gui import components as ui  # noqa: E402

PAIR_SECONDS = 300
APP_URL = "https://github.com/ruscher/big-screen-monitor-display/releases"
TRANSPORTS = {"wifi": N_("Wi-Fi"), "ethernet": N_("Ethernet"), "usb-accessory": N_("USB cable"),
              "usb-tether": N_("USB (tethering)"), "usb-adb": N_("USB (debugging)"), "network": N_("Network"),
              "other": N_("Network")}
QUALITY = (("auto", N_("Automatic (lossless over USB)")), ("lossless", N_("Lossless (sharpest)")),
           ("balanced", N_("Balanced")), ("economy", N_("Economy (least traffic)")))
RESOLUTION = (("auto", N_("Automatic (by performance)")), ("native", N_("Native resolution")),
              ("1920", N_("Up to 1920 px")), ("1280", N_("Up to 1280 px")), ("960", N_("Up to 960 px")),
              ("640", N_("Up to 640 px")))


def pairing_url(android_status, ticket, secret):
    """The text of the QR code. Names and addresses are public; the secret is single use."""
    addresses = [entry["address"] for entry in (android_status.get("addresses") or [])][:4]
    query = {"v": "1", "id": android_status.get("server_id") or "", "n": (android_status.get("name") or "")[:40],
             "fp": android_status.get("fingerprint") or "", "p": str(android_status.get("port") or 7717),
             "a": ",".join(addresses), "t": ticket, "s": secret}
    return "bsmd://pair?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)


def qr_texture(text, scale=8):
    """A QR code as a texture; None without python-qrcode (the manual way still works)."""
    try:
        import qrcode
    except ImportError:
        return None
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=scale, border=3)
    code.add_data(text)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    image = image.get_image() if hasattr(image, "get_image") else image
    return ui.texture_from_image(image.convert("RGB"))


def transport_label(transport):
    return _(TRANSPORTS.get(transport, transport or "—"))


def ago(timestamp):
    if not timestamp:
        return "—"
    seconds = max(0, time.time() - timestamp)
    if seconds < 90:
        return _("just now")
    if seconds < 5400:
        return _("{minutes} min ago").format(minutes=int(seconds // 60))
    if seconds < 129600:
        return _("{hours} h ago").format(hours=int(seconds // 3600))
    return _("{days} days ago").format(days=int(seconds // 86400))


class AndroidGroup:
    """The "Android phones and tablets" group of My Displays."""

    def __init__(self, page):
        self.page = page
        self.window = page.window
        self.dialog = None
        self.group = Adw.PreferencesGroup(
            title=_("Android phones and tablets"),
            description=_("Install the Big Screen Monitor Display app on the phone and add it here: it becomes one "
                          "more display, with its own theme and settings, and its touchscreen controls the theme."))
        add = Gtk.Button(label=_("Add Android…"), valign=Gtk.Align.CENTER)
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self.open_pairing())
        self.group.set_header_suffix(add)
        window = self.window
        self.network = window._switch("android_network", _("Connect over the network (Wi-Fi or Ethernet)"),
                                      _("The computer accepts paired phones on the local network (encrypted, "
                                        "port 7717). Off: nothing listens on the network."))
        self.usb = window._switch("android_usb", _("Connect over a USB cable"),
                                  _("Phones already paired open the app when plugged in (USB accessory, no "
                                    "debugging needed). USB tethering and USB debugging also work."))
        self.group.add(self.network)
        self.group.add(self.usb)
        self.state_row = Adw.ActionRow(title=_("Status"), subtitle="—", subtitle_selectable=True)
        self.state_row.add_css_class("property")
        self.group.add(self.state_row)
        self.dynamic = []
        self._signature = None
        self._usb_signature = None
        self.usb_rows = []

    # ------------------------------------------------------------ refresh
    def update(self):
        status = (self.window.status or {}).get("android") if self.window.status else None
        self._update_state(status)
        requests = (status or {}).get("requests") or []
        paired = (status or {}).get("paired") or []
        connected = {entry["display_id"]: entry for entry in (status or {}).get("connected") or []}
        signature = (tuple((r["request"], r["code"]) for r in requests),
                     tuple((p["display_id"], p.get("name"), p.get("last_transport"),
                            p["display_id"] in connected) for p in paired))
        if signature != self._signature:
            self._signature = signature
            self._rebuild(requests, paired, connected)
        self._update_usb(status)
        if self.dialog is not None:
            self.dialog.update(status)

    def _update_usb(self, status):
        """Phones on a USB cable right now (sysfs, read-only): offer to use one as a display."""
        from bsmd.displays.android import aoa
        try:
            phones = aoa.android_phones()
        except OSError:
            phones = []
        if not self.window.values.get("android_usb", True):
            phones = []
        signature = tuple((p["path"], p["serial"]) for p in phones)
        if signature == self._usb_signature:
            return
        self._usb_signature = signature
        for row in self.usb_rows:
            self.group.remove(row)
        self.usb_rows = []
        known = {entry.get("usb") for entry in (status or {}).get("paired") or [] if entry.get("usb")}
        for phone in phones:
            name = " ".join(part for part in (phone.get("manufacturer"), phone.get("product")) if part) or _("Phone")
            paired = aoa.serial_hash(phone["serial"]) in known
            row = Adw.ActionRow(title=GLib.markup_escape_text(name),
                                subtitle=_("On the USB cable · paired") if paired else _("On the USB cable"))
            row.add_prefix(Gtk.Image.new_from_icon_name("drive-removable-media-symbolic"))
            button = Gtk.Button(label=_("Use as Display"), valign=Gtk.Align.CENTER)
            button.set_tooltip_text(_("Asks the phone to open the Big Screen Monitor Display app (USB accessory, "
                                      "no debugging)"))
            button.connect("clicked", lambda _b, p=phone: self._use_usb(p))
            row.add_suffix(button)
            self.group.add(row)
            self.usb_rows.append(row)

    def _use_usb(self, phone):
        from bsmd.displays.android import aoa
        from bsmd.displays.base import DisplayError

        def work():
            try:
                aoa.switch_to_accessory(phone)
                message = _("Confirm on the phone: open Big Screen Monitor Display (tick \"Always\" to make it a "
                            "permanent display). The first time, allow the code shown here.")
            except DisplayError as error:
                message = _("The phone did not switch: {error}. On the phone, choose \"File transfer\" for USB "
                            "and make sure the app is installed.").format(error=error)
            except Exception as error:  # noqa: BLE001 - permission (no uaccess) and the like
                message = _("No access to the phone ({error}). Choose \"File transfer\" for USB on the phone "
                            "and try again.").format(error=error)
            GLib.idle_add(lambda: self.window.toast(message) and False)
        threading.Thread(target=work, daemon=True).start()

    def _update_state(self, status):
        if self.window.status is None:
            self.state_row.set_subtitle(_("The service is not running."))
        elif status is None:
            self.state_row.set_subtitle(_("This version of the service has no Android support yet; restart it."))
        elif status.get("error"):
            self.state_row.set_subtitle(GLib.markup_escape_text(status["error"]))
        elif status.get("network"):
            addresses = ", ".join(f"{a['address']}" for a in status.get("addresses") or []) or "—"
            self.state_row.set_subtitle(_("Waiting for phones at {addresses} (port {port})").format(
                addresses=addresses, port=status.get("port")))
        elif status.get("listening"):
            self.state_row.set_subtitle(_("Network off: only phones on a USB cable can connect."))
        else:
            self.state_row.set_subtitle(_("Off: no phone can connect."))

    def _rebuild(self, requests, paired, connected):
        for row in self.dynamic:
            self.group.remove(row)
        self.dynamic = []
        for request in requests:
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(_("{name} wants to connect").format(name=request["name"])),
                subtitle=GLib.markup_escape_text(_("Code {code} · {model} · {transport} {address}").format(
                    code=f"{request['code'][:3]} {request['code'][3:]}", model=request.get("model") or "",
                    transport=transport_label(request.get("transport")), address=request.get("address") or "")))
            row.add_prefix(Gtk.Image.new_from_icon_name("phone-symbolic"))
            row.add_css_class("android-request")
            deny = Gtk.Button(label=_("Refuse"), valign=Gtk.Align.CENTER)
            deny.connect("clicked", lambda _b, r=request["request"]: self._decide(r, False))
            allow = Gtk.Button(label=_("Allow"), valign=Gtk.Align.CENTER)
            allow.add_css_class("suggested-action")
            allow.set_tooltip_text(_("Only if the phone shows the same code"))
            allow.connect("clicked", lambda _b, r=request["request"]: self._decide(r, True))
            row.add_suffix(deny)
            row.add_suffix(allow)
            self.group.add(row)
            self.dynamic.append(row)
        for device in paired:
            live = connected.get(device["display_id"])
            where = transport_label(live["transport"]) if live else _("not connected")
            row = Adw.ActionRow(title=GLib.markup_escape_text(device.get("name") or _("Android")),
                                subtitle=GLib.markup_escape_text(" · ".join(part for part in (
                                    " ".join(p for p in (device.get("manufacturer"), device.get("model")) if p),
                                    where, _("last seen {when}").format(when=ago(device.get("last_seen"))))
                                    if part)))
            row.add_prefix(Gtk.Image.new_from_icon_name("phone-symbolic"))
            if live:
                row.add_prefix(ui.pill(_("Connected"), "success"))
            remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text=_("Remove pairing"))
            remove.add_css_class("flat")
            ui.set_label(remove, _("Remove pairing"))
            remove.connect("clicked", lambda _b, d=device: self.confirm_revoke(d["display_id"], d.get("name")))
            row.add_suffix(remove)
            self.group.add(row)
            self.dynamic.append(row)

    # ------------------------------------------------------------ actions
    def _decide(self, request_id, approved):
        self.page.command({"action": "android_approve" if approved else "android_deny", "display": "*",
                           "request": request_id})

    def confirm_revoke(self, display_id, name):
        dialog = Adw.AlertDialog(
            heading=_("Remove {name}?").format(name=name or _("this phone")),
            body=_("The phone disconnects now and has to be added again to show the themes. Its settings on this "
                   "computer are kept."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", lambda _d, answer: answer == "remove" and self.page.command(
            {"action": "android_revoke", "display": display_id}))
        dialog.present(self.window)

    def open_pairing(self):
        if self.window.status is None:
            self.window._error(_("The service is not running"),
                               _("Start the monitoring service, then add the phone."))
            return
        self.dialog = PairDialog(self)
        self.dialog.present()


class PairDialog:
    """QR code + instructions while a single-use pairing ticket is open."""

    def __init__(self, group):
        self.group = group
        self.window = group.window
        self.ticket = None
        self.secret = None
        self.expires = 0.0
        self.paired_before = None
        self.dialog = Adw.Dialog(title=_("Add Android"), content_width=560)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_top=12, margin_bottom=24,
                      margin_start=24, margin_end=24)
        self.steps = ui.caption(
            _("1. Install the Big Screen Monitor Display app on the phone ({url}).\n"
              "2. Connect the phone to the same network as this computer.\n"
              "3. Point the phone's camera at this code and open the link, or open the app and tap "
              "\"Scan the code\".").format(url=APP_URL), dim=False)
        box.append(self.steps)
        self.picture = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN, height_request=280,
                                   halign=Gtk.Align.CENTER, width_request=280)
        self.picture.update_property([Gtk.AccessibleProperty.LABEL], [_("Pairing QR code")])
        box.append(self.picture)
        self.countdown = ui.caption("", xalign=0.5)
        box.append(self.countdown)
        self.network_banner = Adw.Banner(title=_("Connections over the network are off."),
                                         button_label=_("Switch on"), revealed=False)
        self.network_banner.connect("button-clicked", lambda *_: self._enable_network())
        box.append(self.network_banner)
        manual = Adw.PreferencesGroup(
            title=_("Without the camera"),
            description=_("In the app, choose this computer in the list (or add it by address). This window then "
                          "shows a code: allow it only if the phone shows the same code."))
        self.address_row = Adw.ActionRow(title=_("Address of this computer"), subtitle="—", subtitle_selectable=True)
        self.address_row.add_css_class("property")
        manual.add(self.address_row)
        self.fp_row = Adw.ActionRow(title=_("Certificate fingerprint"), subtitle="—", subtitle_selectable=True)
        self.fp_row.add_css_class("property")
        manual.add(self.fp_row)
        box.append(manual)
        self.result = Adw.StatusPage(icon_name="emblem-ok-symbolic", visible=False)
        box.append(self.result)
        scroll = Gtk.ScrolledWindow(child=box, propagate_natural_height=True,
                                    hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar.set_content(scroll)
        self.dialog.set_child(toolbar)
        self.dialog.connect("closed", lambda *_: self._closed())
        self._timer = None

    def present(self):
        self._new_ticket()
        self.dialog.present(self.window)
        self._timer = GLib.timeout_add_seconds(1, self._tick)

    def _new_ticket(self):
        self.ticket = secrets.token_hex(8)
        self.secret = bsdp.b64e(secrets.token_bytes(18))
        self.expires = time.monotonic() + PAIR_SECONDS
        self.group.page.command({"action": "android_pair_open", "display": "*", "ticket": self.ticket,
                                 "secret": self.secret, "seconds": PAIR_SECONDS}, quiet=True)
        self.update((self.window.status or {}).get("android"))

    def update(self, status):
        status = status or {}
        paired = {p["display_id"]: p for p in status.get("paired") or []}
        if self.paired_before is None:
            self.paired_before = set(paired)
        new = [p for key, p in paired.items() if key not in self.paired_before]
        if new:
            self.paired_before = set(paired)
            self.result.set_title(_("{name} added").format(name=new[0].get("name") or _("Phone")))
            self.result.set_description(_("It now appears in My Displays. Another phone can use the new code."))
            self.result.set_visible(True)
            self._new_ticket()
            return
        network = bool(status.get("network"))
        self.network_banner.set_revealed(not network)
        addresses = [entry["address"] for entry in status.get("addresses") or []]
        port = status.get("port") or 7717
        self.address_row.set_subtitle(", ".join(f"{a}:{port}" for a in addresses) or
                                      _("Not on a network (switch the network connection on)"))
        fingerprint = status.get("fingerprint") or ""
        self.fp_row.set_subtitle(" ".join(fingerprint[i:i + 4] for i in range(0, min(len(fingerprint), 24), 4))
                                 or "—")
        if status.get("server_id") and network:
            texture = qr_texture(pairing_url(status, self.ticket, self.secret))
            if texture is not None:
                self.picture.set_paintable(texture)
                self.picture.set_visible(True)
            else:
                self.picture.set_visible(False)
                self.countdown.set_label(_("Install python-qrcode to see the QR code; the manual way below works "
                                           "without it."))
                return
        else:
            self.picture.set_visible(False)

    def _tick(self):
        remaining = int(self.expires - time.monotonic())
        if remaining <= 0:
            self._new_ticket()
            remaining = PAIR_SECONDS
        if self.picture.get_visible():
            self.countdown.set_label(_("This code changes in {minutes}:{seconds:02d}").format(
                minutes=remaining // 60, seconds=remaining % 60))
        return True

    def _enable_network(self):
        self.window._set("android_network", True)
        self.window.toast(_("Press Apply to let phones connect over the network."))

    def _closed(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None
        self.group.page.command({"action": "android_pair_close", "display": "*"}, quiet=True)
        self.group.dialog = None


def detail_rows(page, group, display_id, own):
    """Rows of an Android display's own page."""
    group.add(page._combo(_("Picture quality"), [(k, _(v)) for k, v in QUALITY], own.get("android_quality", "auto"),
                          lambda value: page._set(display_id, "android_quality", None if value == "auto" else value),
                          _("Charts and text are always sent without loss; this affects photos and wallpapers.")))
    group.add(page._combo(_("Drawing size"), [(k, _(v)) for k, v in RESOLUTION],
                          own.get("android_resolution", "auto"),
                          lambda value: page._set(display_id, "android_resolution",
                                                  None if value == "auto" else value),
                          _("Themes are drawn at this size and scaled to the screen: smaller is lighter for the "
                            "computer and the network.")))
    for key, title, subtitle, default in (
            ("android_auto_rotate", _("Rotate with the phone"),
             _("Follow the phone's sensor instead of the orientation chosen above."), False),
            ("android_keep_screen_on", _("Keep the screen on"),
             _("While the theme is shown (permanent display)."), True),
            ("android_burn_in", _("Burn-in protection"),
             _("Moves the picture by a few pixels from time to time (OLED screens)."), True),
            ("touch_enabled", _("Touchscreen"),
             _("Swipe to change theme, hold for the menu; nothing reaches the computer's mouse or keyboard."), True),
            ("touch_media", _("Media controls on the touchscreen"),
             _("Big Media Player: play, pause, next and volume on the phone (only what the player offers)."), True)):
        row = Adw.SwitchRow(title=title, subtitle=subtitle, active=own.get(key, default))
        row.connect("notify::active", lambda r, _p, k=key, d=default: page._set(
            display_id, k, None if r.get_active() == d else r.get_active()))
        group.add(row)
    remove = Adw.ActionRow(title=_("Remove pairing"), subtitle=_("The phone has to be added again"),
                           activatable=True)
    remove.add_prefix(Gtk.Image.new_from_icon_name("user-trash-symbolic"))
    remove.connect("activated", lambda *_: page.android.confirm_revoke(display_id, own.get("name")))
    group.add(remove)


def describe(status):
    """(connection, protocol, details) lines for an Android display's page."""
    device = status.get("device") or {}
    details = device.get("details") or {}
    connection = " · ".join(part for part in (transport_label(details.get("transport")), details.get("address"))
                            if part) or "—"
    protocol = _("BSDP {version} · {security}").format(
        version=bsdp.VERSION, security=_("TLS, paired device") if details.get("tls") else _("USB cable, paired device"))
    lines = []
    if details.get("android"):
        lines.append(_("Android {version} · app {app}").format(version=details["android"], app=details.get("app")))
    if details.get("screen"):
        lines.append(_("Screen {screen} · {dpi} dpi").format(screen=details["screen"], dpi=details.get("density_dpi")))
    return connection, protocol, lines
