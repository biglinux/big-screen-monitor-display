#!/usr/bin/env python3
"""Generate docs/compatibilidade.md from the display registry (bsmd/displays/registry.py).

    tools/make_compat.py            rewrite the page
    tools/make_compat.py --check    exit 1 when the page is out of date (tests do this)
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "usr", "share", "big-screen-monitor-display"))

from bsmd.displays import registry  # noqa: E402

OUT = os.path.join(ROOT, "docs", "compatibilidade.md")
LEVELS = {
    "A": "✅ A — testado no aparelho",
    "B": "🧪 B — implementado, aguardando teste físico",
    "C": "🔬 C — protocolo conhecido, em implementação",
    "D": "🔎 D — em investigação",
    "E": "⛔ E — não suportado",
}
ISSUE = "https://github.com/ruscher/big-screen-monitor-display/issues/new?template=1-hardware.yml"


def usb_ids(profile):
    ids = []
    for rule in profile.rules:
        vid = "????" if rule.vid is None else f"{rule.vid:04x}"
        pids = [f"{pid:04x}" for pid in rule.pids] or ["*"]
        ids += [f"`{vid}:{pid}`" for pid in pids]
    return " ".join(dict.fromkeys(ids)) or "—"


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def render():
    lines = [
        "# Compatibilidade de hardware",
        "",
        "<!-- Gerado por tools/make_compat.py a partir de bsmd/displays/registry.py. Não edite à mão. -->",
        "",
        "Cada família lista os identificadores USB que o serviço reconhece. A detecção só",
        "lê o `sysfs`; nada é enviado a um aparelho antes de você escolher o modelo.",
        "",
        "| Nível | Significado |",
        "| --- | --- |",
    ]
    lines += [f"| **{key}** | {text.split(' — ', 1)[1]} |" for key, text in LEVELS.items()]
    lines += [
        "",
        f"**Tem um aparelho nível B?** [Conte se funciona]({ISSUE}): um relato confirmando",
        "já promove o driver para A.",
        "",
        "| Família | Fabricante | Modelos | IDs USB | Resolução | Transporte | Nível |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for profile in sorted(registry.PROFILES, key=lambda p: (p.validation, p.name.lower())):
        lines.append("| " + " | ".join(cell(value) for value in (
            f"**{profile.name}**", profile.vendor, ", ".join(profile.models) or "—", usb_ids(profile),
            profile.resolutions, profile.transport, LEVELS.get(profile.validation, profile.validation))) + " |")
    lines += [
        "",
        "Fora do USB: celulares e tablets **Android** (Wi-Fi, cabo USB sem depuração ou",
        "Tailscale) são nível A; os clientes experimentais para aparelhos antigos",
        "(Windows CE, Palm OS 5) ficam em [`device-clients/`](../device-clients/).",
        "",
    ]
    return "\n".join(lines)


def main(argv):
    text = render()
    if "--check" in argv:
        with open(OUT, encoding="utf-8") as fh:
            if fh.read() != text:
                print("docs/compatibilidade.md desatualizado: rode tools/make_compat.py", file=sys.stderr)
                return 1
        return 0
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
