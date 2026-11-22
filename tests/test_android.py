"""Android displays: BSDP protocol, hub (pairing, auth, limits) and the runtime end to end.

The phone is played by tests/android_client.py, which speaks BSDP like the
app does (TLS, HELLO/CHALLENGE, rectangles, PRESENTED, touches).
"""

import json
import os
import secrets
import socket
import threading
import time
import zlib

import pytest
from PIL import Image, ImageChops, ImageDraw

from android_client import Client, decode, discover, free_port_pair
from bsmd import health, settings, touch
from bsmd.displays.android import protocol as bsdp
from bsmd.displays.android.driver import AndroidDisplay, render_size
from bsmd.displays.android.hub import AndroidHub
from bsmd.displays.android.link import Link
from bsmd.displays.base import DisplayError
from test_runtime import FakeNotifier, FastRuntime, wait_for

HERE = os.path.dirname(__file__)


# ------------------------------------------------------------------ protocol

def test_framing_round_trip_and_limits():
    data = bsdp.json_message(bsdp.HELLO, {"a": 1}) + bsdp.message(bsdp.PING, b"\0\0\0\7")
    parser = bsdp.Parser(limit=bsdp.MAX_CLIENT_PAYLOAD, kinds=bsdp.CLIENT_KINDS)
    out = []
    for byte in data:                         # one byte at a time: partial headers and payloads
        out += parser.feed(bytes([byte]))
    assert [m.kind for m in out] == [bsdp.HELLO, bsdp.PING]
    assert out[0].json() == {"a": 1}
    with pytest.raises(bsdp.ProtocolError):
        bsdp.Parser().feed(b"XX\x01\x01\0\0\0\0")
    with pytest.raises(bsdp.ProtocolError):
        bsdp.Parser().feed(b"BS\x02\x01\0\0\0\0")
    with pytest.raises(bsdp.ProtocolError):       # computer -> app types are refused from an app
        bsdp.Parser(kinds=bsdp.CLIENT_KINDS).feed(bsdp.message(bsdp.RECT, b""))
    with pytest.raises(bsdp.ProtocolError):       # oversized before the payload even arrives
        bsdp.Parser(limit=1024).feed(bsdp.HEADER.pack(b"BS", 1, bsdp.STATS, 4096))
    with pytest.raises(bsdp.ProtocolError):
        bsdp.Message(bsdp.HELLO, b"[1,2]").json()
    with pytest.raises(bsdp.ProtocolError):
        bsdp.Message(bsdp.HELLO, b"\xff\xfe").json()


def hello_body(**extra):
    body = {"proto": 1, "device_id": "0123456789abcdef0123", "name": "Galaxy", "model": "S24",
            "manufacturer": "Samsung", "android": "14", "sdk": 34, "app_version": "1.0",
            "screen": {"w": 2340, "h": 1080}, "view": {"w": 2340, "h": 1080}, "density": 450,
            "formats": ["fill", "rgb-zlib", "jpeg", "nonsense"], "transport": "wifi",
            "nonce": bsdp.b64e(b"n" * 16)}
    body.update(extra)
    return body


def test_hello_is_validated():
    hello = bsdp.Hello.parse(hello_body(name="Galaxy\x00\x1b[31m" + "x" * 100))
    assert hello.name.startswith("Galaxy") and "\x1b" not in hello.name and len(hello.name) <= 40
    assert hello.formats == (bsdp.FMT_FILL, bsdp.FMT_RGB_ZLIB, bsdp.FMT_JPEG)
    for bad in ({"proto": 2}, {"device_id": "../../etc"}, {"device_id": "ABC"}, {"nonce": "short"},
                {"view": {"w": 10, "h": 10}}, {"screen": "x"}):
        with pytest.raises(bsdp.ProtocolError):
            bsdp.Hello.parse(hello_body(**bad))
    assert bsdp.Hello.parse(hello_body(transport="satellite")).transport == "other"


def sample_image(size=(320, 200)):
    image = Image.new("RGB", size, (20, 30, 40))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 150, 60), fill=(200, 80, 20))
    draw.text((20, 100), "CPU 42%  GPU 61 °C", fill=(255, 255, 255))
    for x in range(160, 320):                 # photographic-ish gradient with noise
        for y in range(0, 200, 2):
            draw.point((x, y), fill=((x * 7 + y * 3) % 256, (y * 5) % 256, (x * y) % 256))
    return image


@pytest.mark.parametrize("quality", ["lossless", "balanced", "economy"])
def test_encode_rect_round_trip(quality):
    image = sample_image()
    for box in ((0, 0, 320, 200), (10, 10, 150, 60), (200, 0, 320, 120)):
        encoded = bsdp.encode_rect(image, box, image.size, quality)
        x, y, w, h, cw, ch, fmt, _ = bsdp.RECT_HEADER.unpack_from(encoded.payload)
        assert (x, y, x + w, y + h) == box and (cw, ch) == image.size
        part = decode(fmt, w, h, encoded.payload[bsdp.RECT_HEADER.size:])
        diff = ImageChops.difference(part, image.crop(box)).getextrema()
        if fmt in (bsdp.FMT_FILL, bsdp.FMT_RGB_ZLIB):
            assert all(high == 0 for _low, high in diff)      # exact
        else:
            assert quality != "lossless" and fmt == bsdp.FMT_JPEG
    assert bsdp.encode_rect(image, (10, 10, 150, 60), image.size, quality).fmt == bsdp.FMT_FILL


def test_encode_rect_respects_the_formats_the_app_has():
    image = sample_image()
    encoded = bsdp.encode_rect(image, (0, 0, 320, 200), image.size, "economy", (bsdp.FMT_RGB_ZLIB,))
    assert encoded.fmt == bsdp.FMT_RGB_ZLIB


def test_sas_and_proofs_are_bound_to_every_input():
    fp, sn, cn, dev = b"f" * 32, b"s" * 32, b"c" * 16, "0123456789abcdef"
    code = bsdp.sas_code(fp, sn, cn, dev)
    assert len(code) == 6 and code.isdigit()
    assert code != bsdp.sas_code(b"g" * 32, sn, cn, dev)          # another certificate (a MITM)
    proof = bsdp.auth_proof(b"k" * 32, sn, cn, dev)
    assert proof != bsdp.auth_proof(b"k" * 32, sn, cn, dev + "0")
    assert proof != bsdp.pair_proof(b"k" * 32, sn, cn, dev)       # labels separate the two uses


def build_vectors():
    """Byte-exact vectors the Kotlin tests check (android/app/src/test)."""
    token, server_nonce, client_nonce, dev = bytes(range(32)), bytes(range(32, 64)), bytes(range(64, 80)), \
        "00112233445566778899aabbccddeeff"
    fp = bytes(range(100, 132))
    image = Image.new("RGB", (4, 2), (1, 2, 3))
    image.putpixel((3, 1), (250, 128, 7))
    rect = bsdp.encode_rect(image, (0, 0, 4, 2), (4, 2), "lossless")
    return {
        "device_id": dev, "token": bsdp.b64e(token), "server_nonce": bsdp.b64e(server_nonce),
        "client_nonce": bsdp.b64e(client_nonce), "fingerprint": bsdp.b64e(fp),
        "auth_proof": bsdp.b64e(bsdp.auth_proof(token, server_nonce, client_nonce, dev)),
        "pair_proof": bsdp.b64e(bsdp.pair_proof(token, server_nonce, client_nonce, dev)),
        "sas": bsdp.sas_code(fp, server_nonce, client_nonce, dev),
        "display_id": bsdp.display_id(dev),
        "ping": bsdp.message(bsdp.PING, bsdp.TOKEN_BODY.pack(0x01020304)).hex(),
        "touch": bsdp.touch(bsdp.TOUCH_MOVE, 513, 260, 123456789).hex(),
        "presented": bsdp.message(bsdp.PRESENTED, bsdp.PRESENTED_BODY.pack(77, 12, 1)).hex(),
        "present": bsdp.present(77, (1280, 720)).hex(),
        "brightness": bsdp.message(bsdp.BRIGHTNESS, bytes([55])).hex(),
        "rect_zlib": bsdp.message(bsdp.RECT, rect.payload).hex(),
        "rect_zlib_pixels": [list(image.getpixel((x, y))) for y in range(2) for x in range(4)],
        "rect_fill": bsdp.message(bsdp.RECT, bsdp.rect(8, 9, 10, 11, (64, 48), bsdp.FMT_FILL, b"\x10\x20\x30")).hex(),
        "json_view": bsdp.json_message(bsdp.VIEW, {"w": 1080, "h": 2340}).hex(),
    }


def test_shared_vectors_are_current():
    path = os.path.join(HERE, "data", "bsdp-vectors.json")
    expected = build_vectors()
    if os.environ.get("BSM_WRITE_VECTORS"):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(expected, handle, indent=1, sort_keys=True)
            handle.write("\n")
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle) == expected


def test_render_size_follows_profile_and_choice():
    assert render_size((2340, 1080), {"performance_profile": "auto"}) == (1280, 591)
    assert render_size((2340, 1080), {"performance_profile": "economy"}) == (960, 443)
    assert render_size((1080, 2340), {"performance_profile": "fluid"}) == (886, 1920)
    assert render_size((2340, 1080), {"android_resolution": "native"}) == (2340, 1080)
    assert render_size((800, 480), {"android_resolution": "1920"}) == (800, 480)     # never upscaled


# ------------------------------------------------------------------ hub

@pytest.fixture
def hub(tmp_path):
    hubs = []

    def make(**kwargs):
        made = AndroidHub(str(tmp_path / "state"), host_name="Test PC", usb=False, **kwargs)
        port = free_port_pair()
        assert made.listen(port, host="127.0.0.1"), made.error
        hubs.append(made)
        return made
    yield make
    for made in hubs:
        made.stop()


def open_ticket(hub_):
    ticket, secret = secrets.token_hex(8), bsdp.b64e(secrets.token_bytes(16))
    hub_.open_pairing(ticket, secret, 60)
    return ticket, secret


def test_identity_is_created_once_and_private(tmp_path, hub):
    first = hub()
    directory = os.path.join(str(tmp_path / "state"), "android")
    assert oct(os.stat(directory).st_mode & 0o777) == "0o700"
    assert oct(os.stat(os.path.join(directory, "server.key")).st_mode & 0o777) == "0o600"
    fp, server_id = first.identity.fingerprint, first.identity.server_id
    first.stop()
    again = hub()
    assert (again.identity.fingerprint, again.identity.server_id) == (fp, server_id)


def test_discovery_answers_without_secrets(hub):
    made = hub()
    reply = discover(made.port)
    assert reply["name"] == "Test PC" and reply["port"] == made.port and reply["server_id"] == made.identity.server_id
    assert reply["fp"] == made.identity.fingerprint_b64 and reply["pairing"] is False
    assert "token" not in json.dumps(reply) and "secret" not in json.dumps(reply)


def test_pairing_by_ticket_then_authentication(hub):
    made = hub()
    ticket, secret = open_ticket(made)
    client = Client(made.port)
    assert client.login(ticket, secret), client.reject
    assert client.challenge["need"] == "pair" and client.challenge["fp"] == made.identity.fingerprint_b64
    assert len(client.token) == 32 and client.welcome["display_id"] == bsdp.display_id(client.device_id)
    assert client.welcome["fp"] == bsdp.b64e(client.cert_fp)
    assert wait_for(lambda: made.available(client.device_id))
    client.close()
    # The ticket was single use.
    other = Client(made.port)
    assert not other.login(ticket, secret) and other.reject["reason"] == bsdp.R_EXPIRED
    # The paired phone comes back with its token (challenge-response, pinned certificate).
    again = Client(made.port, device_id=client.device_id, token=client.token, pinned=client.cert_fp)
    assert again.login() and again.challenge["need"] == "auth" and "token" not in again.welcome
    paired = made.status()["paired"]
    assert [p["name"] for p in paired] == ["Pixel Test"] and "token" not in json.dumps(paired)
    again.close()


def test_wrong_secrets_are_refused_and_rate_limited(hub):
    made = hub()
    ticket, secret = open_ticket(made)
    client = Client(made.port)
    assert client.login(ticket, secret)
    client.close()
    bad = Client(made.port, device_id=client.device_id, token=b"x" * 32)
    assert not bad.login() and bad.reject["reason"] == bsdp.R_AUTH
    stranger = Client(made.port, token=b"y" * 32)       # never paired
    assert not stranger.login() and stranger.reject["reason"] == bsdp.R_UNKNOWN
    wrong_ticket = Client(made.port)
    assert not wrong_ticket.login("0123456789abcdef", secret) and wrong_ticket.reject["reason"] == bsdp.R_EXPIRED
    for _ in range(6):
        attempt = Client(made.port, device_id=client.device_id, token=b"z" * 32)
        try:
            attempt.login()
        except (OSError, ConnectionError, TimeoutError):
            break
    # Banned now: even the right token is turned away for a while.
    blocked = Client(made.port, device_id=client.device_id, token=client.token)
    with pytest.raises((OSError, ConnectionError, TimeoutError)):
        blocked.login()
    assert made.counters["auth_failed"] >= 5


def test_pairing_by_confirmation(hub):
    made = hub()
    client = Client(made.port).connect()
    client.hello()
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("ok", client.pair_confirm()))
    thread.start()
    assert wait_for(lambda: made.status()["requests"])
    request = made.status()["requests"][0]
    assert request["code"] == bsdp.sas_code(client.cert_fp, bsdp.b64d(client.challenge["nonce"]),
                                            bsdp.b64d(client.nonce), client.device_id)
    assert request["name"] == "Pixel Test"
    made.decide(request["request"], True)
    thread.join(5)
    assert result["ok"] and client.token is not None
    assert made.status()["requests"] == []
    client.close()


def test_pairing_by_confirmation_can_be_refused(hub):
    made = hub()
    client = Client(made.port).connect()
    client.hello()
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("ok", client.pair_confirm()))
    thread.start()
    assert wait_for(lambda: made.status()["requests"])
    made.decide(made.status()["requests"][0]["request"], False)
    thread.join(5)
    assert result["ok"] is False and client.reject["reason"] == bsdp.R_DENIED
    assert made.status()["paired"] == []
    client.close()


def test_other_protocol_version_is_told_to_update(hub):
    made = hub()
    client = Client(made.port).connect()
    assert client.hello({"proto": 2}) is None and client.reject["reason"] == bsdp.R_VERSION
    client.close()


def test_handshake_rejects_garbage_and_silence(hub):
    made = hub()
    import ssl
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    with socket.create_connection(("127.0.0.1", made.port)) as raw, context.wrap_socket(raw) as sock:
        sock.sendall(b"GET / HTTP/1.1\r\n\r\n")
        sock.settimeout(5)
        assert sock.recv(100) == b""                      # closed, nothing leaked
    with socket.create_connection(("127.0.0.1", made.port)) as raw:     # not even TLS
        raw.sendall(b"hello\r\n")
        raw.settimeout(5)
        try:
            data = raw.recv(100)
        except ConnectionResetError:
            data = b""                                    # reset: closed as well
        # Closed, or a TLS alert record (0x15) first, depending on the OpenSSL build: never BSDP data.
        assert data == b"" or data[0] == 0x15
    assert wait_for(lambda: made.counters["tls_failed"] >= 1, timeout=3)


def test_revoking_drops_the_connection(hub):
    made = hub()
    ticket, secret = open_ticket(made)
    client = Client(made.port)
    assert client.login(ticket, secret)
    assert made.revoke(client.welcome["display_id"]) == [client.device_id]
    assert wait_for(lambda: client.bye is not None or not client.running)
    client.close()
    again = Client(made.port, device_id=client.device_id, token=client.token)
    assert not again.login() and again.reject["reason"] == bsdp.R_UNKNOWN


def test_link_answers_pings_and_bounds_its_backlog():
    a, b = socket.socketpair()
    link = Link(a, transport="usb-accessory", address="usb").start()
    try:
        b.sendall(bsdp.message(bsdp.PING, bsdp.TOKEN_BODY.pack(99)))
        b.settimeout(3)
        reply = bsdp.Parser().feed(b.recv(100))
        assert reply[0].kind == bsdp.PONG and bsdp.parse_token(reply[0].payload) == 99
        b.sendall(bsdp.json_message(bsdp.STATS, {}) * 80)     # nobody handles them yet
        assert wait_for(lambda: not link.alive, timeout=3)
    finally:
        link.close()
        b.close()


# ------------------------------------------------------------------ runtime end to end

@pytest.fixture
def android_runtime(tmp_path):
    started = []

    def start(data=None):
        config = tmp_path / "settings.json"
        made = AndroidHub(str(tmp_path / "state"), host_name="Test PC", usb=False)
        port = free_port_pair()
        assert made.listen(port, host="127.0.0.1")
        # Network off, USB on: the runtime keeps a loopback listener on this port.
        # Animated by default: frames keep coming even on an idle CI machine.
        settings.save(dict(data or {"theme": "brother_away"}, android_port=port), str(config))
        app = FastRuntime(settings.SettingsStore(str(config)), notifier=FakeNotifier(),
                          status_file=str(tmp_path / "run" / "status.json"),
                          state_directory=str(tmp_path / "state"), scan=lambda: [], android=made)
        app.SESSION_LINGER = 1.0
        app.backoff = health.Backoff(base=0.05, cap=0.2, jitter=0)
        result = {}
        thread = threading.Thread(target=lambda: result.setdefault("code", app.run()), daemon=True)
        thread.start()
        started.append((app, thread))
        return app, made, config
    yield start
    for app, thread in started:
        app.stop()
        thread.join(5)


def paired_client(made, **kwargs):
    ticket, secret = open_ticket(made)
    client = Client(made.port, **kwargs)
    assert client.login(ticket, secret), client.reject
    return client


def test_phone_becomes_a_display_with_real_frames(android_runtime):
    app, made, _config = android_runtime()
    client = paired_client(made, view=(1600, 720))
    display = client.welcome["display_id"]
    assert wait_for(lambda: display in app.sessions and app.sessions[display].link.state == health.HEALTHY)
    assert wait_for(lambda: client.frames >= 3, timeout=10)
    session = app.sessions[display]
    assert session.driver.native_size == (1280, 576) and client.canvas.size == (1280, 576)
    assert client.config["orientation"] == "landscape" and client.config["canvas"] == [1280, 576]
    assert session.name() == "Pixel Test"
    # What the phone shows is what the theme drew (lossless over the loopback "cable").
    assert wait_for(lambda: session.stats["frames_sent"] >= 3)
    status = app.status()
    entry = next(d for d in status["displays"] if d["id"] == display)
    assert entry["device"]["driver"] == "android" and entry["capabilities"]["orientation"] == "device"
    assert status["android"]["connected"][0]["in_use"] is True
    client.close()
    assert wait_for(lambda: session.link.state != health.HEALTHY, timeout=10)


def test_rotation_redraws_at_the_new_aspect(android_runtime):
    app, made, _config = android_runtime()
    client = paired_client(made, view=(1280, 720))
    display = client.welcome["display_id"]
    assert wait_for(lambda: client.frames >= 2, timeout=10)
    client.set_view(720, 1280)
    assert wait_for(lambda: client.canvas is not None and client.canvas.size == (720, 1280), timeout=10)
    assert app.sessions[display].driver.native_size == (720, 1280)
    client.close()


def test_touch_swipe_changes_only_this_phones_theme(android_runtime):
    app, made, _config = android_runtime()
    client = paired_client(made, view=(1280, 720))
    display = client.welcome["display_id"]
    assert wait_for(lambda: client.frames >= 2, timeout=10)
    session = app.sessions[display]
    before = session.settings()["theme"]
    client.swipe(1000, 360, 300, 360)
    themes = list(settings.THEME_IDS)
    expected = themes[(themes.index(before) + 1) % len(themes)]
    assert wait_for(lambda: session.settings()["theme"] == expected, timeout=5)
    assert app.store.get()["theme"] == before            # the global setting is untouched
    client.close()


def test_app_menu_commands_are_checked(android_runtime):
    app, made, _config = android_runtime()
    client = paired_client(made)
    display = client.welcome["display_id"]
    assert wait_for(lambda: client.frames >= 2, timeout=10)
    session = app.sessions[display]
    client.command({"cmd": "set", "key": "android_auto_rotate", "value": True})
    assert wait_for(lambda: client.config and client.config["orientation"] == "auto", timeout=5)
    client.command({"cmd": "set", "key": "language", "value": "en"})           # not settable from a phone
    client.command({"cmd": "set", "key": "android_quality", "value": "ultra"})  # invalid value
    client.command({"cmd": "reboot"})                                         # not a command at all
    client.command({"cmd": "menu"})
    assert wait_for(lambda: session.touch.page == "menu", timeout=5)
    assert "language" not in session.touch.overrides.values
    assert "android_quality" not in session.touch.overrides.values
    assert session.driver.stats["dropped_commands"] >= 1
    client.close()


def test_transport_switch_keeps_one_display(android_runtime):
    app, made, _config = android_runtime()
    first = paired_client(made, transport="wifi")
    display = first.welcome["display_id"]
    assert wait_for(lambda: first.frames >= 2, timeout=10)
    # The same phone connects again (USB plugged in): the old link is replaced.
    second = Client(made.port, device_id=first.device_id, token=first.token, transport="usb-tether")
    assert second.login()
    assert wait_for(lambda: first.bye is not None or not first.running, timeout=5)
    assert wait_for(lambda: second.frames >= 2, timeout=10)
    assert [d for d in app.sessions if d.startswith("android-")] == [display]
    frames_first = first.frames
    time.sleep(0.5)
    assert first.frames == frames_first                    # nothing more reaches the old connection
    second.close()


def test_stalled_phone_does_not_block_the_others(android_runtime):
    # An animated theme: there is always a new frame waiting for the stalled phone
    # (a static theme on an idle computer may legitimately send nothing new).
    app, made, _config = android_runtime({"theme": "brother_away"})
    slow = paired_client(made, name="Slow")
    fast = paired_client(made, name="Fast")
    assert wait_for(lambda: slow.frames >= 1 and fast.frames >= 1, timeout=10)
    slow.hold_presented = True                             # this phone stops drawing
    before = fast.frames
    assert wait_for(lambda: fast.frames >= before + 3, timeout=10)
    slow_session = app.sessions[slow.welcome["display_id"]]
    assert wait_for(lambda: slow_session.link.state != health.HEALTHY, timeout=15)
    assert app.sessions[fast.welcome["display_id"]].link.state == health.HEALTHY
    slow.close()
    fast.close()


def test_disabled_phone_is_turned_away(android_runtime):
    app, made, config = android_runtime()
    client = paired_client(made)
    display = client.welcome["display_id"]
    assert wait_for(lambda: display in app.sessions)
    data = settings.read_file(str(config))[0]
    data["displays"] = {display: {"enabled": False}}
    settings.save(data, str(config))
    assert wait_for(lambda: display not in app.sessions, timeout=8)
    assert wait_for(lambda: client.bye is not None, timeout=5) and client.bye["reason"] == "disabled"


def test_spool_commands_reach_the_hub(android_runtime, tmp_path):
    app, made, _config = android_runtime()
    ticket, secret = secrets.token_hex(8), bsdp.b64e(secrets.token_bytes(16))
    app._spool_command({"action": "android_pair_open", "display": "*", "ticket": ticket, "secret": secret,
                        "seconds": 60})
    assert made.pairing.is_open()
    client = Client(made.port)
    assert client.login(ticket, secret)
    display = client.welcome["display_id"]
    assert wait_for(lambda: display in app.sessions)
    app._spool_command({"action": "android_revoke", "display": display})
    assert display not in app.sessions and made.status()["paired"] == []
    status = json.dumps(app.status())
    assert secret not in status and bsdp.b64e(client.token) not in status
    client.close()


def test_spool_validation_of_android_commands():
    good = {"action": "android_pair_open", "display": "*", "ticket": "0123456789abcdef",
            "secret": bsdp.b64e(b"s" * 16), "seconds": 5000}
    assert settings.validate_command(good)["seconds"] == 900
    assert settings.validate_command(dict(good, secret="short")) is None
    assert settings.validate_command(dict(good, ticket="nothex!!nothex!!")) is None
    assert settings.validate_command({"action": "android_approve", "request": "zz"}) is None
    assert settings.validate_command({"action": "android_revoke", "display": "usb-1-2"}) is None
    assert settings.validate_command({"action": "android_revoke", "display": "android-0123456789ab"})
    assert settings.DISPLAY_ID.match("android-0123456789ab") and not settings.DISPLAY_ID.match("android-XYZ")


# ------------------------------------------------------------------ media controls

def test_media_controls_reach_the_agent_and_only_whitelisted(tmp_path):
    from bsmd.media import ipc
    from bsmd.media.hub import MediaHub
    path = str(tmp_path / "media.sock")
    media = MediaHub(path)
    media.server = ipc.Server(path, media.on_message, authorize=lambda uid: True)
    assert media.server.start()
    publisher = ipc.Publisher([path])
    received = []
    publisher.on_command = received.append
    publisher.start()
    try:
        publisher.publish({"type": "snapshot", "v": 1, "players": [], "active": None, "volume": {}},
                          coalesce="snapshot")
        assert wait_for(lambda: media.states)
        assert media.command("next") is True
        assert media.command("launch_browser") is False
        media.server.send(os.getuid(), {"type": "command", "action": "rm -rf"})   # forged: dropped by the agent
        assert wait_for(lambda: received == ["next"], timeout=3)
        time.sleep(0.3)
        assert received == ["next"]
    finally:
        publisher.stop()
        media.stop()


def test_touch_bar_shows_media_controls_only_when_they_work():
    class Host:
        snapshot = {"players": [{"bus": "org.mpris.MediaPlayer2.x", "status": "Playing", "title": "Song",
                                 "artist": "Band", "can": {"next": True, "previous": False, "pause": True,
                                                           "play": True, "control": True}}],
                    "active": "org.mpris.MediaPlayer2.x", "volume": {"available": False}}
        sent = []

        def base_settings(self):
            return {"theme": "big_media_player", "touch_media": True}

        def request(self, *args):
            pass

        def wake(self):
            pass

        def name(self):
            return "Phone"

        def state(self):
            return "healthy"

        def media(self):
            return self.snapshot

        def media_command(self, action, value=0.0):
            self.sent.append(action)
            return True

        def brightness_supported(self):
            return True

    host = Host()
    ui = touch.TouchUI(host, thumbnails=False)
    ui.handle(touch.DOWN, 100, 100)
    ui.handle(touch.UP, 100, 100)
    ui.decorate(Image.new("RGB", (1280, 720)), host.base_settings())
    actions = [(action, arg) for _box, action, arg in ui.buttons]
    assert ("media", "next") in actions and ("media", "play_pause") in actions
    assert ("media", "previous") not in actions                      # the player cannot go back
    assert not any(arg in ("volume_up", "mute") for _a, arg in actions)    # no volume control here
    box = next(box for box, action, arg in ui.buttons if arg == "next")
    ui.handle(touch.DOWN, (box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    ui.handle(touch.UP, (box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    assert host.sent == ["next"]


def test_driver_refuses_a_dead_link():
    with pytest.raises(DisplayError):
        AndroidDisplay(None)


def test_zlib_rect_is_plain_rgb():
    image = Image.new("RGB", (3, 1), (9, 8, 7))
    payload = bsdp.encode_rect(image, (0, 0, 3, 1), (3, 1), "lossless", (bsdp.FMT_RGB_ZLIB,)).payload
    assert zlib.decompress(payload[bsdp.RECT_HEADER.size:]) == bytes([9, 8, 7] * 3)


# ------------------------------------------------------------------ USB accessory (AOA)

from bsmd.displays.android import aoa  # noqa: E402
from bsmd.displays.discovery import UsbDevice  # noqa: E402


def fake_device(root, name, vid, pid, serial="", interfaces=(), product="Phone"):
    path = root / name
    path.mkdir(parents=True)
    for key, value in (("idVendor", f"{vid:04x}"), ("idProduct", f"{pid:04x}"), ("serial", serial),
                       ("busnum", "3"), ("devnum", "7"), ("product", product), ("manufacturer", "Maker")):
        (path / key).write_text(value + "\n")
    for index, (cls, sub, proto) in enumerate(interfaces):
        iface = path / f"{name}:1.{index}"
        iface.mkdir()
        (iface / "bInterfaceClass").write_text(cls)
        (iface / "bInterfaceSubClass").write_text(sub)
        (iface / "bInterfaceProtocol").write_text(proto)


def test_android_phones_are_recognised_by_their_interfaces(tmp_path):
    fake_device(tmp_path, "3-1", 0x04E8, 0x6860, "R58M", [aoa.MTP])              # Samsung, file transfer
    fake_device(tmp_path, "3-2", 0x18D1, 0x4EE7, "PIX", [aoa.ADB])              # Pixel, debugging
    fake_device(tmp_path, "3-3", 0x1908, 0x0102, "", [("ff", "00", "00")])      # AX206 display
    fake_device(tmp_path, "3-4", 0x18D1, 0x2D00, "R58M", [("ff", "ff", "00")])  # already an accessory
    phones = aoa.android_phones(str(tmp_path))
    assert [p["path"] for p in phones] == ["3-1", "3-2"]
    assert phones[0]["serial"] == "R58M" and phones[0]["bus"] == 3 and phones[0]["address"] == 7


class FakeTimeout(Exception):
    pass


class FakeUsb:
    """Just enough of pyusb (usb.core + usb.util) for AOA."""
    USBTimeoutError = FakeTimeout
    ENDPOINT_IN, ENDPOINT_OUT = 0x80, 0x00

    def __init__(self, device):
        self.device = device
        self.util = self

    def find(self, **_kwargs):
        return self.device

    @staticmethod
    def endpoint_direction(address):
        return address & 0x80

    def claim_interface(self, device, _interface):
        device.claimed = True

    def release_interface(self, device, _interface):
        device.claimed = False

    def dispose_resources(self, _device):
        pass

    @staticmethod
    def find_descriptor(intf, custom_match):
        return next((ep for ep in intf if custom_match(ep)), None)


class Endpoint:
    def __init__(self, sock, address):
        self.sock = sock
        self.bEndpointAddress = address

    def read(self, size, timeout=500):
        self.sock.settimeout(timeout / 1000)
        try:
            data = self.sock.recv(size)
        except socket.timeout:
            raise FakeTimeout() from None
        if not data:
            raise OSError("unplugged")
        return data

    def write(self, data, timeout=3000):
        self.sock.sendall(bytes(data))
        return len(data)


class AccessoryDevice:
    bus, address = 3, 9

    def __init__(self, protocol=2):
        self.protocol = protocol
        self.transfers = []
        self.claimed = False
        self.pc_end, self.phone_end = socket.socketpair()

    def ctrl_transfer(self, request_type, request, value, index, data=None, timeout=None):
        self.transfers.append((request_type, request, index, bytes(data) if isinstance(data, bytes) else data))
        if request == aoa.GET_PROTOCOL:
            return bytes([self.protocol, 0])
        return 0

    def is_kernel_driver_active(self, _interface):
        return False

    def set_configuration(self):
        pass

    def get_active_configuration(self):
        return {(0, 0): [Endpoint(self.pc_end, 0x81), Endpoint(self.pc_end, 0x01)]}


def test_switch_sends_the_aoa_sequence():
    device = AccessoryDevice()
    assert aoa.switch_to_accessory({"vid": 1, "pid": 2, "bus": 3, "address": 9}, usb_core=FakeUsb(device)) == 2
    requests = [(t[1], t[2]) for t in device.transfers]
    assert requests == [(51, 0)] + [(52, i) for i in range(6)] + [(53, 0)]
    assert device.transfers[2][3] == b"BigScreenMonitorDisplay\0"       # model string the app filters on
    old = AccessoryDevice(protocol=0)
    with pytest.raises(DisplayError):
        aoa.switch_to_accessory({"vid": 1, "pid": 2, "bus": 3, "address": 9}, usb_core=FakeUsb(old))
    assert [t[1] for t in old.transfers] == [51]                       # nothing else sent to it
    for dev in (device, old):
        dev.pc_end.close()
        dev.phone_end.close()


def test_auto_switch_only_for_phones_paired_over_usb(tmp_path):
    fake_device(tmp_path, "3-1", 0x04E8, 0x6860, "KNOWN", [aoa.MTP])
    fake_device(tmp_path, "3-2", 0x04E8, 0x6860, "STRANGER", [aoa.MTP])
    switched = []
    clock = [100.0]
    auto = aoa.AutoSwitcher(str(tmp_path), switch=switched.append, clock=lambda: clock[0])
    status = {"paired": [{"display_id": "android-0123456789ab", "usb": aoa.serial_hash("KNOWN")}]}
    assert [p["serial"] for p in auto.step(status)] == ["KNOWN"]
    assert auto.step(status) == []                                     # once per plug (a minute)
    clock[0] += 61
    assert len(auto.step(status)) == 1
    assert auto.step(status, enabled=False) == [] and aoa.AutoSwitcher(str(tmp_path)).step({"paired": []}) == []
    assert "KNOWN" not in json.dumps(status)                           # only a hash is remembered


def test_accessory_link_pairs_and_is_remembered(tmp_path):
    device = AccessoryDevice()
    made = AndroidHub(str(tmp_path / "state"), host_name="Test PC", usb=False)
    made.prepare()
    info = UsbDevice(path="3-1", vid=aoa.GOOGLE_VID, pid=0x2D00, serial="R58M", bus=3, address=9)
    watcher = aoa.AccessoryWatcher(made, scan=lambda: [info], usb_core=FakeUsb(device), usb_util=FakeUsb(device))
    made.aoa = watcher
    try:
        watcher.step({"android_usb": True})
        assert device.claimed and "3-1" in watcher.bridges
        client = Client(sock=device.phone_end, transport="usb-accessory").connect()
        challenge = client.hello()
        assert challenge["need"] == "pair" and challenge["fp"] == ""          # no TLS on the cable
        result = {}
        thread = threading.Thread(target=lambda: result.setdefault("ok", client.pair_confirm()))
        thread.start()
        assert wait_for(lambda: made.status()["requests"])
        assert made.status()["requests"][0]["transport"] == "usb-accessory"
        made.decide(made.status()["requests"][0]["request"], True)
        thread.join(5)
        assert result["ok"] and wait_for(lambda: made.available(client.device_id))
        assert made.status()["paired"][0]["usb"] == aoa.serial_hash("R58M")
        watcher.step({"android_usb": False})                              # switched off: nothing new adopted
    finally:
        made.stop()
        device.pc_end.close()
        device.phone_end.close()


def test_touch_menu_offers_calibration_only_where_it_exists():
    class Host:
        calibrate = False

        def base_settings(self):
            return {"theme": "standard"}

        def request(self, *args):
            pass

        def wake(self):
            pass

        def name(self):
            return "Phone"

        def state(self):
            return "healthy"

        def can_calibrate(self):
            return self.calibrate

        def device_oriented(self):
            return True

    host = Host()
    ui = touch.TouchUI(host, thumbnails=False)
    ui.command("menu")
    ui.decorate(Image.new("RGB", (1280, 720)), host.base_settings())
    assert "calibrate" not in [action for _box, action, _arg in ui.buttons]
    host.calibrate = True
    ui.decorate(Image.new("RGB", (1280, 720)), host.base_settings())
    assert "calibrate" in [action for _box, action, _arg in ui.buttons]
    ui.command("menu")
    ui._open("orientation", ui.clock())
    ui.decorate(Image.new("RGB", (1280, 720)), host.base_settings())
    assert ("orientation", "auto") in [(a, arg) for _box, a, arg in ui.buttons]     # phones can follow the sensor
