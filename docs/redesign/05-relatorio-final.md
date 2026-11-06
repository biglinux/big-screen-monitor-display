# 05 — Relatório final do redesign (5.0.0)

## Implementado

- Janela nova (`config_gui.py`): `Adw.NavigationSplitView` com sidebar em
  grupos (Visão geral · Personalizar · Sistema), contadores e status do
  serviço no rodapé; `Adw.NavigationView` por seção; seções sob demanda;
  breakpoints 1100sp (empilhar) e 640sp (recolher); barra global de
  alterações pendentes; atalhos Ctrl+S, Ctrl+F, Ctrl+1…9, Alt+←, Ctrl+Q.
- Design system (`gui/style.css`, `gui/components.py`): cartões e grades no
  padrão AshyWall, moldura de display, selos semânticos, cartões de estado,
  workers de miniaturas e de tarefas bloqueantes.
- Início (`gui/dashboard.py`), Galeria de Temas (`gui/theme_gallery.py`),
  Brother Away (`gui/brother_away_page.py`), Preferências
  (`gui/preferences_page.py`).
- Meus Displays reescrito (`displays_page.py`): galeria + página por display,
  separação clara entre padrões e ajustes do display, varredura em worker.
- Big Media Player (`media_player_page.py`): Tocando agora com capa real,
  galeria de skins com filtro e subpágina de opções.
- Kojiro (`kojiro_page.py`): barra compacta (menu Exibir), barra rolável,
  painel que vira vertical em janelas estreitas.
- Traduções: `locale/pt.po` completo (1303 mensagens), `.pot` regenerado.
- Versão 5.0.0. Ferramentas: `tools/ui_benchmark.py`,
  `tools/ui_screenshots.py`.

Arquivos de configuração, helper Polkit, serviço, drivers e temas do
display: **sem alteração**. O AshyWall não foi tocado.

## Critérios de aceitação

| # | Critério | Evidência |
| --- | --- | --- |
| 1 | Linguagem visual do AshyWall | capturas em `images/`; padrões listados em `01-auditoria.md` |
| 2 | Navegação reorganizada | 9 seções em sidebar; `test_window_flows` |
| 3 | Recursos anteriores acessíveis | todas as opções 4.4 presentes (mesmas chaves, mesmos controles); Brother Away ganhou as 6 histórias que faltavam |
| 4 | Ações ligadas às funções reais | aplicar/descartar/restaurar, helper, comandos de display, MPRIS — testes |
| 5 | Prévias com o renderizador correto | `themes.render_for_panel`, o mesmo do serviço |
| 6–7 | Drivers e múltiplos displays | serviço inalterado; AX206 real funcionando durante todo o trabalho; 2 displays simulados nos testes |
| 8 | Kojiro editável | seção abre o editor completo; ativo só na seção |
| 9 | Media Player no MPRIS | núcleo MPRIS e volume reais na seção; testes D-Bus existentes passam |
| 10 | Brother Away | 14 histórias com miniatura e reprodução na prévia; motor intacto |
| 11 | Configuração segura | mesmo `save_settings` → `bsm-helper`; testes de cancelamento e validação |
| 12 | Sem travamentos/regressões relevantes | `04-testes-benchmarks.md` (abertura −55 %, RAM −41 %, animação igual; repouso +1 ponto pela prévia ao vivo, explicado) |
| 13 | Testes passam | 1237 passando |
| 14 | Benchmarks e limitações | `04-testes-benchmarks.md` |
| 15 | Empacotável | `gui/` fica em `usr/share/...`, copiado pelo PKGBUILD sem mudanças; requisitos mantidos (libadwaita ≥ 1.6) |

## Capturas

Escuro: `images/*-dark-1280.png` (todas as seções e as páginas de tema, de
display e de opções do player). Claro: `images/*-light-1280.png`. Estreito:
`images/*-dark-400.png`.

## Limitações e pendências reais

- Primeira visita ao Kojiro leva ~300 ms (construção do estúdio).
- Os outros 27 idiomas recebem os textos novos pelo fluxo de tradução do CI.
- Não testado: Orca, Wayland/X11 de outros desktops, HiDPI fracionário,
  displays além do AX206.
- `kojiro_page.py` mantém 4 linhas acima de 120 colunas (anteriores ao
  redesign).
