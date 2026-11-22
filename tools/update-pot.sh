#!/usr/bin/env bash
# Extract the translatable strings (_ / N_ / ngettext) into
# locale/big-screen-monitor-display.pot and merge them into every
# locale/*.po. New messages arrive untranslated; changed ones keep the old
# translation as fuzzy for review (docs/i18n.md). en.po mirrors the source.
set -euo pipefail
cd "$(dirname "$0")/.."

DOMAIN=big-screen-monitor-display
POT="locale/$DOMAIN.pot"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' usr/share/big-screen-monitor-display/bsmd/__init__.py)

find usr -name '*.py' | LC_ALL=C sort > "${TMPDIR:-/tmp}/$DOMAIN.files"
xgettext --from-code=UTF-8 -L Python -k_ -kN_ -kngettext:1,2 \
    --package-name="$DOMAIN" --package-version="$VERSION" \
    -f "${TMPDIR:-/tmp}/$DOMAIN.files" -o "$POT"
rm -f "${TMPDIR:-/tmp}/$DOMAIN.files"
sed -i 's/charset=CHARSET/charset=UTF-8/;/^"POT-Creation-Date:/d' "$POT"

for po in locale/*.po; do
    if [ "$(basename "$po")" = en.po ]; then
        # English is the source: every message is its own translation
        # (a message that became plural comes back fuzzy: emptied, then refilled)
        msgmerge --quiet --no-wrap --no-fuzzy-matching --update --backup=none "$po" "$POT"
        msgattrib --clear-fuzzy --empty --no-wrap -o "$po" "$po"
        msgen --no-wrap -o "$po" "$po"
    else
        msgmerge --quiet --no-wrap --update --backup=none "$po" "$POT"
    fi
    msgattrib --no-obsolete --no-wrap -o "$po" "$po"
    msgfmt --check --statistics -o /dev/null "$po" 2>&1 | sed "s|^|$po: |"
done
