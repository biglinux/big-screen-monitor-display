# System name and logo (session identity)

Every theme that shows the system's name or logo (Kojiro's `distro` widget,
the Big Media Player title bar and badge, the dashboard, GKrellM and the
legacy themes) gets it from one function, `bsmd.kojiro.assets.identity()`.

1. The base is `/etc/os-release` (`NAME`, `PRETTY_NAME`, `LOGO`, `ID`).
2. The service reads which session is active on `seat0`, and its desktop, from
   logind's runtime files (`/run/systemd/seats/seat0` → `ACTIVE=`, then
   `/run/systemd/sessions/<id>` → `CLASS=`, `DESKTOP=`). This is what `sd-login`
   does. It needs no D-Bus, starts no process and works under the service's
   `DynamicUser` sandbox. Greeter and lock-screen sessions (`CLASS` other than
   `user`) are ignored.
3. If a desktop identity file in `/etc/desktop-identity/*.conf` or
   `/usr/share/desktop-identity/*.conf` lists that desktop in `DESKTOP_NAMES`,
   its `NAME` and `LOGO` (an icon name, with `LOGO_FILE` as a fallback path)
   replace the distribution's name and logo. `ID`/`ID_LIKE` stay those of the
   distribution, and `BASE_NAME` keeps its name.

```
# /usr/share/desktop-identity/big-wm.conf (installed by big-wm-session)
NAME="Big WindowMaker"
LOGO=big-wm
LOGO_FILE=/usr/share/icons/hicolor/scalable/apps/big-wm.svg
DESKTOP_NAMES=WindowMaker;wlmaker
```

The result is cached for 15 s, so a login into another desktop shows up
within that time without reading files on every frame.

The media data (player name, its icon, title, cover) still come only from
MPRIS: the identity never replaces "Spotify", "VLC" or "Firefox".

Tests: `tests/test_identity.py` (X11 and Wayland desktop names, other
desktop, greeter, no session, session switch after the cache, malformed files,
logo file without an icon in the theme).
