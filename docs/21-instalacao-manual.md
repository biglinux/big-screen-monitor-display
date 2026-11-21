# 21 — Instalação manual (openSUSE, Regata OS, Debian/Ubuntu, Fedora, Arch)

No Arch, Manjaro e BigLinux use o **pacote** (`pkgbuild/PKGBUILD`): o pacman
resolve as dependências e remove tudo com `pacman -R`. O `install-system.sh`
existe para as distribuições sem pacote e recusa sobrescrever um pacote
instalado.

## Instalar

```bash
git clone https://github.com/biglinux/big-screen-monitor-display.git
cd big-screen-monitor-display
./install-system.sh --print-deps      # o que será instalado neste sistema
sudo ./install-system.sh              # dependências + arquivos + serviço
```

A família vem do `/etc/os-release` (`ID` e `ID_LIKE`), não da presença de
`zypper` ou `pacman`:

| Família | Reconhece | Gerenciador | Observações |
| --- | --- | --- | --- |
| suse | openSUSE Tumbleweed/Leap/Slowroll, Regata OS, SLE | `zypper install --no-recommends` | pacotes com a versão do Python (`python313-psutil`, `python313-PyQt6`...); `pkexec` é um pacote à parte |
| arch | Arch, Manjaro, BigLinux, BigCommunity, EndeavourOS, Garuda, CachyOS | `pacman -S --needed` (nunca `-Sy`) | se faltar atualizar o sistema, o instalador para e pede `pacman -Syu` |
| debian | Debian, Ubuntu, Mint, Pop!_OS | `apt-get update` (só os índices) + `apt-get install --no-install-recommends` | `pkexec` à parte |
| fedora | Fedora, RHEL, Rocky, Alma | `dnf install` | |

Python 3.10 ou mais novo é exigido (openSUSE Leap 15 traz o 3.6: use
Tumbleweed ou Slowroll). Nunca é feito upgrade do sistema.

Essenciais: Pillow, numpy, psutil, PyUSB, pySerial, PyGObject + pycairo, GTK 4,
libadwaita, PyQt6 (bandejas), libusb, pciutils, rsvg-convert, fontconfig,
polkit/pkexec, gettext. Opcionais (só listados no fim, nunca instalados
sozinhos): lm_sensors, OpenRGB, playerctl, ferramentas de áudio.

## O que o instalador garante

* `/etc/big-screen-monitor-display/settings.json` **nunca** é substituído; antes
  de um upgrade fica uma cópia verificada (`cmp`) `settings.json.pre-install-<data>`
  (as três mais novas são mantidas). Para voltar: copie a cópia por cima.
* `/etc/xdg/autostart/big-screen-monitor-media.desktop` alterado pelo usuário é
  mantido (a versão nova vai para `.new`).
* Diretório do aplicativo substituído por inteiro (módulos removidos não ficam).
* Rodar de novo é seguro: mesma lista de arquivos, o serviço mantém o estado
  (um serviço desativado não é reativado num upgrade: `try-restart`).
* Nenhum usuário fixo e nenhum grupo extra: o acesso aos painéis é pelo
  `uaccess`/grupo do udev (doc 04); o grupo `dialout` (todas as portas
  seriais) não é usado.
* Lista exata do que foi instalado em `/usr/lib/big-screen-monitor-display/install-manifest`.
* Arquivos da primeira versão das bandejas (`deepcool-digital(.sh)`,
  `screen-monitor-tray(.sh)`, seus `.desktop` e ícones) são removidos — só se
  apontarem para este programa.

## Desinstalar

```bash
sudo ./uninstall-system.sh            # mantém as configurações
sudo ./uninstall-system.sh --purge    # também /etc/big-screen-monitor-display (cópia em /var/backups)
```

Remove exatamente o que está no manifesto (e os nomes antigos acima), para o
serviço antes e devolve os painéis SmartMonitor ao normal. Arquivos pessoais
não são apagados: entradas de autostart das bandejas em `~/.config/autostart`
são apenas listadas.

## Testar sem root

```bash
./install-system.sh --destdir /tmp/raiz      # instala só os arquivos em /tmp/raiz
./uninstall-system.sh --destdir /tmp/raiz
python -m pytest tests/test_install.py       # instalação, upgrade, rollback, remoção
```
