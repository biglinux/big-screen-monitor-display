"""ActivePlayerManager: which MPRIS session the display follows.

The policy is a pure function of the player list (with the instants each one
started playing and was last active, both measured by the agent) and the
previous choice, so the agent and every display that uses the same options
pick the same player.

Modes
    auto    keep the current player while it plays; another player takes over
            only after playing for ``STEAL_AFTER`` seconds while the current one
            is paused/stopped/gone, and never with a clip shorter than
            ``SHORT_CLIP`` (notification sounds, previews on hover).
    last    the most recently active player wins at once.
    fixed   the player matching the pattern; ``auto`` while it is absent.
``auto_switch=False`` keeps the current player while it exists at all.
Ignored applications are never chosen.
"""

from . import model

MODES = ("auto", "last", "fixed")
STEAL_AFTER = 2.0
SHORT_CLIP = 8_000_000      # µs


class ActivePlayerManager:
    def __init__(self, mode="auto", fixed="", ignore=(), auto_switch=True):
        self.current = None
        self.configure(mode, fixed, ignore, auto_switch)

    def configure(self, mode="auto", fixed="", ignore=(), auto_switch=True):
        self.mode = mode if mode in MODES else "auto"
        self.fixed = (fixed or "").strip()
        self.ignore = [pattern for pattern in ignore if pattern]
        self.auto_switch = bool(auto_switch)

    @classmethod
    def from_settings(cls, values):
        manager = cls()
        manager.apply_settings(values)
        return manager

    def apply_settings(self, values):
        self.configure(values.get("bmp_player_mode", "auto"), values.get("bmp_player_fixed", ""),
                       model.split_patterns(values.get("bmp_player_ignore", "")),
                       values.get("bmp_auto_switch", True))

    # ------------------------------------------------------------ policy
    def eligible(self, players):
        return [p for p in players if not any(model.matches(p, pattern) for pattern in self.ignore)]

    def choose(self, players, now):
        players = self.eligible(players)
        by_bus = {p["bus"]: p for p in players}
        current = by_bus.get(self.current)
        if self.mode == "fixed" and self.fixed:
            pinned = [p for p in players if model.matches(p, self.fixed)]
            if pinned:
                # Several instances (Firefox windows): the playing / most recent one.
                self.current = max(pinned, key=_activity)["bus"]
                return self.current
        if not players:
            self.current = None
            return None
        playing = [p for p in players if p["status"] == "Playing"]
        if self.mode == "last":
            choice = max(playing or players, key=_activity)
            if current and current["status"] == "Playing" and choice is not current and \
                    _activity(choice) <= _activity(current):
                choice = current
            self.current = choice["bus"]
            return self.current
        if current is not None:
            if current["status"] == "Playing" or not self.auto_switch:
                return self.current
            stable = [p for p in playing if self._can_steal(p, now)]
            if stable:
                self.current = max(stable, key=_activity)["bus"]
            return self.current
        # Nothing chosen yet (start, or the player closed): whatever plays, else the most recent.
        candidates = [p for p in playing if not _short(p)] or playing or players
        self.current = max(candidates, key=_activity)["bus"]
        return self.current

    @staticmethod
    def _can_steal(player, now):
        since = player.get("playing_since_mono")
        return since is not None and now - since >= STEAL_AFTER and not _short(player)


def _short(player):
    length = player.get("length_us")
    return length is not None and length < SHORT_CLIP


def _activity(player):
    return (player.get("status") == "Playing", player.get("last_active_mono") or 0.0)


def pick(snapshot, manager, now):
    """The chosen player dict of a snapshot (or None)."""
    if not snapshot:
        return None
    bus = manager.choose(snapshot["players"], now)
    return next((p for p in snapshot["players"] if p["bus"] == bus), None)
