# Ícone da janela no Big WindowMaker

**Branch:** `feat/tray-symbolic-wm-icon` · **Data:** 22/11/2026

## Sintoma

Com o Big Screen Monitor Display aberto no Big WindowMaker, a barra de
aplicativos (appicons do `big-wm-tabbed-dock`) mostrava o ícone genérico
"exec" em vez do ícone oficial, e o item não tinha comando para reabrir o app.

## Diagnóstico

Sessão de teste: **Big WindowMaker Wayland** (`wlmaker --start_xwayland`,
`XDG_CURRENT_DESKTOP=wlmaker`, `big-wm-tabbed-dock` 0.3.2).

O `big-wm-appicons` associa cada janela a um `.desktop` nesta ordem
(`src/core/btd-desktop.c`, `btd_desktop_index_match`):

1. `<app_id>.desktop`, depois `StartupWMClass`/nome do arquivo iguais ao `app_id`;
2. o `.desktop` de onde o GIO lançou o processo (`GIO_LAUNCHED_DESKTOP_FILE`);
3. `WM_CLASS` (X11) contra `StartupWMClass`;
4. nome do executável (`python3` é ambíguo e é descartado);
5. último componente do `app_id` reverso-DNS.

O que a janela publicava (medido):

| Sessão | Propriedade | Valor | Casa com o lançador? |
|---|---|---|---|
| Wayland | `app_id` (GTK 4 = `application_id`) | `br.com.biglinux.BigScreenMonitorDisplay` | **não** — o arquivo era `big-screen-monitor-display.desktop` |
| X11 (`GDK_BACKEND=x11`, `xprop`) | `WM_CLASS` | `big-screen-monitor-display`, `big-screen-monitor-display` | sim (`StartupWMClass`) |
| X11 | `_GTK_APPLICATION_ID` | `br.com.biglinux.BigScreenMonitorDisplay` | não |
| X11 | `_NET_WM_ICON` | **ausente** | — o Window Maker X11 fica sem ícone próprio |

Plist gerado pelo dock antes da correção (`/run/user/1000/big-wm-appicons.plist`):

```
Name = "br.com.biglinux.BigScreenMonitorDisplay";
AppID = "br.com.biglinux.BigScreenMonitorDisplay";
Icon = "big-wm-app-br.com.biglinux.BigScreenMonitorDisplay.png";   // ícone genérico "exec", sem CommandLine
```

## Causa raiz

Identidade inconsistente: o GTK 4 publica o **id da aplicação** como `app_id`
no Wayland, e o lançador tinha outro nome. Nenhum passo do algoritmo acima liga
`br.com.biglinux.BigScreenMonitorDisplay` a `big-screen-monitor-display.desktop`
(GNOME Shell e KDE Plasma fazem a mesma busca por `<app_id>.desktop` e só
acertavam por heurística). No X11, além disso, a janela não definia ícone,
então não havia `_NET_WM_ICON`.

## Correção (identidade, não caminho de ícone)

| Arquivo | Mudança |
|---|---|
| `usr/share/applications/br.com.biglinux.BigScreenMonitorDisplay.desktop` | o lançador passa a ter o nome do `app_id` (padrão freedesktop, como os demais `br.com.biglinux.*`); `Icon` e `StartupWMClass` inalterados |
| `bsmd/__init__.py` | `APPLICATION_ID` e `DESKTOP_FILE` num só lugar |
| `config_gui.py` | usa `APPLICATION_ID`; `Gtk.Window.set_default_icon_name(APP_ID)` (vira `_NET_WM_ICON` no X11 em todas as janelas, inclusive diálogos) |
| `install-system.sh` | remove o `big-screen-monitor-display.desktop` antigo na atualização (só se for nosso) |
| `uninstall-system.sh` | conhece os dois nomes |

Resultado da identidade:

* Wayland: `app_id` = `br.com.biglinux.BigScreenMonitorDisplay` = nome do `.desktop`.
* X11: `WM_CLASS` = `big-screen-monitor-display` = `StartupWMClass`; `_NET_WM_ICON` 48×48 publicado.
* Bandejas Qt: já eram coerentes (`setDesktopFileName(app_id)` =
  `big-screen-monitor-tray.desktop` / `big-screen-monitor-deepcool.desktop`);
  agora há teste para isso.

## Evidências

**Wayland (wlmaker), testado de verdade.** Janela aberta a partir do worktree,
com o novo `.desktop` copiado temporariamente para `~/.local/share/applications`
e o `big-wm-appicons` reiniciado (ele só indexa os `.desktop` ao iniciar):

```
Name = "Big Screen Monitor Display";
AppID = "br.com.biglinux.BigScreenMonitorDisplay";
CommandLine = "gtk-launch br.com.biglinux.BigScreenMonitorDisplay.desktop";
Icon = "big-wm-app-br.com.biglinux.BigScreenMonitorDisplay.desktop.png";   // ícone oficial
```

O PNG gerado em `~/.local/share/wlmaker/icons/` é o ícone oficial do app.
Depois do teste o arquivo temporário foi removido e o dock reiniciado.

**X11 (Xwayland, `GDK_BACKEND=x11`), propriedades verificadas com `xprop`.**
`WM_CLASS` e `_NET_WM_ICON` conferidos; o Window Maker X11 em si **não** foi
testado (a sessão era Wayland).

**Testes automatizados:** `tests/test_window_identity.py` (nome do `.desktop` =
id da aplicação, `StartupWMClass`, ícone, ícone padrão definido, bandejas Qt,
instalador) e `tests/test_install.py::test_upgrade_replaces_the_launcher_renamed_after_the_application_id`.

## Limitações

* O `big-wm-appicons` 0.3.2 lê os `.desktop` só ao iniciar: depois de instalar
  esta versão, o ícone certo aparece na próxima sessão (ou reiniciando
  `app-big\x2dwm\x2dwayland\x2dappicons@autostart.service`). Isso é do dock.
* Fixar o app no dock com o nome antigo: um atalho fixado pelo usuário para
  `big-screen-monitor-display.desktop` precisa ser refeito uma vez.
* KDE Plasma, GNOME, Cinnamon e XFCE não foram testados nesta sessão; a mudança
  segue a convenção que eles usam (`<app_id>.desktop`), sem caminho absoluto.
