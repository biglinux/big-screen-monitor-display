"""Themes offered by the screen tray gallery, with the variants that change
their look in one click.

Ids and keys are the real ones (``bsmd.settings`` validates every write; tests
check that the scheme lists agree with ``bsmd.dashboard`` and the settings
schema). Kojiro layouts and Big Media Player skins have their own editors in
the configuration window, which the tray opens; the tray never replaces a
Kojiro layout (that would discard the user's widgets).
"""

from dataclasses import dataclass, field

from bsmd.i18n import N_

# Placeholder pictures shown until the real thumbnails are drawn (traykit.thumbs).
PLACEHOLDERS = {
    ("standard", "dark"): "theme-standard-dark.png",
    ("standard", "cyberpunk"): "theme-standard-cyberpunk.png",
    ("standard", "neon"): "theme-standard-neon.png",
    ("standard", "dracula"): "theme-standard-dracula.png",
    ("standard", "nord"): "theme-standard-nord.png",
    ("standard", ""): "theme-standard-dark.png",
    ("planet", ""): "theme-planet.png",
    ("old_computer", ""): "theme-old_computer.png",
    ("gkrellm", ""): "theme-gkrellm.png",
    ("brother_away", ""): "ba-coconut-away.png",
    ("kojiro", ""): "kojiro-cyberpunk.png",
    ("big_media_player", ""): "bmp-bigamp.png",
}


@dataclass(frozen=True)
class Variant:
    id: str
    name: str
    values: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    summary: str
    key: str = ""                     # settings key the variants set
    variants: tuple = ()
    preferences: tuple = ()           # settings that change its look (thumbnail cache key)

    def variant(self, variant_id):
        for item in self.variants:
            if item.id == variant_id:
                return item
        return None

    def current_variant(self, values):
        return values.get(self.key, "") if self.key else ""


def _variants(key, items):
    return tuple(Variant(vid, name, {key: vid}) for vid, name in items)


# Same order and names as bsmd.dashboard.SCHEMES (checked by a test).
STD_SCHEMES = (("dark", N_("Dark")), ("light", N_("Light")), ("neon", N_("Neon")), ("cyberpunk", N_("Cyberpunk")),
               ("nord", N_("Nord")), ("dracula", N_("Dracula")), ("solarized", N_("Solarized")),
               ("high_contrast", N_("High contrast")))
PLANET_ACCENTS = (("blue", N_("Blue")), ("green", N_("Green")), ("amber", N_("Amber")), ("violet", N_("Violet")),
                  ("red", N_("Red")))
OC_SCHEMES = (("classic", N_("Classic grey")), ("slate", N_("Slate (dark)")), ("amber", N_("Amber")),
              ("plum", N_("Plum")))

THEMES = (
    Theme("standard", N_("Standard"), N_("Clean dashboard with eight colour schemes."), "std_scheme",
          _variants("std_scheme", STD_SCHEMES), ("std_*",)),
    Theme("kojiro", N_("Kojiro"), N_("Your wallpaper with freely placed hardware widgets."),
          preferences=("kojiro",)),
    Theme("planet", N_("Planet"), N_("The Earth lit right now, with the real Sun and Moon."), "planet_accent",
          _variants("planet_accent", PLANET_ACCENTS), ("planet_*",)),
    Theme("brother_away", N_("Brother Away"), N_("Animated island with 14 stories, weather and day/night."),
          preferences=("ba_*", "overlay_*")),
    Theme("old_computer", N_("Old Computer"), N_("A system monitor window from the classic desktop era."),
          "oc_scheme", _variants("oc_scheme", OC_SCHEMES), ("oc_*",)),
    Theme("gkrellm", N_("GKrellM"), N_("Stacked monitors in the classic GKrellM style."), preferences=("gk_*",)),
    Theme("big_media_player", N_("Big Media Player"), N_("15 retro and modern players that follow your music."),
          preferences=("bmp_*",)),
)
BY_ID = {theme.id: theme for theme in THEMES}

ORIENTATIONS = (("horizontal", N_("Landscape")), ("vertical", N_("Portrait")),
                ("horizontal_flipped", N_("Landscape (flipped)")), ("vertical_flipped", N_("Portrait (flipped)")))
BRIGHTNESS_PRESETS = (25, 50, 75, 100)
BRIGHTNESS_MIN = 10


def placeholder(theme_id, variant_id=""):
    return PLACEHOLDERS.get((theme_id, variant_id)) or PLACEHOLDERS.get((theme_id, ""))


def theme_values(theme_id, variant_id=""):
    """Settings written when a card (and optionally one of its variants) is chosen."""
    theme = BY_ID[theme_id]
    values = {"theme": theme_id}
    variant = theme.variant(variant_id) if variant_id else None
    if variant is not None:
        values.update(variant.values)
    return values
