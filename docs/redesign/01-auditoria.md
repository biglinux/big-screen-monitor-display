# 01 — Auditoria (antes do redesign)

Estado inicial: branch `v4.2-kojiro`, árvore limpa, commit `a4152aa` (v4.4.0).
Linha de base: `python3 -m pytest -q tests` → **1229 passando**, nenhum teste
de interface.

## Interface 4.4 (`usr/share/big-screen-monitor-display/`)

| Arquivo | Linhas | Papel |
| --- | --- | --- |
| `config_gui.py` | 1075 | janela única: `Adw.ViewStack` + `ViewSwitcher` no topo; abas Meus Displays, Temas, uma aba por tema (só a do tema aplicado aparecia), Desempenho, Diagnóstico; prévias e páginas de opções de todos os temas |
| `displays_page.py` | 403 | lista de `Adw.ExpanderRow` por display |
| `kojiro_page.py` / `kojiro_editor.py` | 1378 / 860 | Kojiro Design Studio (canvas Cairo, inspetor) |
| `media_player_page.py` | 780 | Big Media Player: uma `PreferencesPage` longa com prévia, controles, 15 skins em linhas e todas as opções |

### Pontos frágeis encontrados

- **Custo na abertura**: todas as abas eram construídas no início (Kojiro com
  miniaturas de predefinições, Media Player, 7 renderizadores de prévia) —
  1,2–1,4 s até desenhar e 281 MB em repouso.
- **Bloqueio do loop GTK**: `DisplaysPage.refresh()` varria a USB
  (`discovery.scan_usb`) na thread principal a cada 2 s; com o serviço parado,
  `systemctl` rodava na thread principal a cada 2 s; a consulta inicial
  `is-enabled` também.
- **Prévias acordando sem necessidade**: threads de prévia invisíveis
  acordavam 2×/s (`wait(0.5)`).
- **Navegação**: as opções de um tema só existiam enquanto ele estava aplicado
  (aba oculta); não havia como explorar Kojiro/Media Player/Brother Away sem
  aplicá-los.
- **Brother Away**: menu "Assistir a uma história" expunha 8 das **14**
  histórias existentes (`brother_away/stories.py:build_registry`).
- **Galerias**: listas de linhas com miniaturas pequenas, sem filtro/busca.
- **Contrato de widgets**: `self._widgets[key]` guardava um widget por chave,
  então dois controles da mesma configuração dessincronizavam.
- Traduções: 417 textos (4.3/4.4) sem pt-BR.

### Restrições respeitadas

- Persistência: `settings.save` (validado, atômico) via `bsm-helper` com
  Polkit; nada roda como root na janela.
- Serviço/systemd, udev, watchdog e drivers: intocados.
- `libadwaita ≥ 1.6` (PKGBUILD): sem `ToggleGroup`/`ShortcutsDialog` (1.7/1.8).

## AshyWall (`/home/ruscher/Documentos/Git/ashywall`, MIT) — padrões adotados

| Padrão | Arquivo de referência | Uso aqui |
| --- | --- | --- |
| `NavigationSplitView` + sidebar `navigation-sidebar` com cabeçalhos de grupo e contadores; colapso em `max-width: 640sp` | `ui/window.py` | `config_gui.py` |
| `NavigationView` por seção; páginas de detalhe empurradas | `ui/window.py` | todas as seções |
| Galeria de cartões: miniatura arredondada, contorno de destaque no hover/foco, título + legenda, selos | `ui/gallery_page.py`, `ui/wallpaper_card.py`, `ui/style.css` | `gui/components.py` (`Card`, `CardGrid`), `gui/style.css` |
| Detalhe: prévia grande + grupos em `Adw.Clamp`, ação principal na barra de título | `ui/detail_page.py`, `ui/detail_widgets.py` | galeria de temas, displays |
| Status no rodapé da sidebar | `ui/window.py` | estado do serviço |
| Regras: nunca bloquear o loop, custo segue a tela, nada inventado, testes isolados (`dbus-run-session`, GSettings em memória, XDG próprio) | `AGENTS.md` | aplicadas |

Nenhum código do AshyWall foi copiado; os padrões foram reimplementados.
O repositório AshyWall não foi alterado.
