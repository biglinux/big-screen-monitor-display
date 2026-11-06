# 03 — Arquitetura da interface

## Navegação

```
Big Screen Monitor (sidebar)              conteúdo (Adw.NavigationView por seção)
Visão geral   Início                      Dashboard
              Meus Displays  [n]          galeria de displays → página do display
Personalizar  Galeria de Temas            galeria → página do tema (prévia + opções)
              Kojiro Design Studio        editor (canvas + inspetor)
              Big Media Player            Tocando agora + skins → Personalizar o player
              Brother Away                prévia + 14 histórias + opções
Sistema       Desempenho                  perfis + medições do serviço
              Diagnóstico [!]             estado, diagnóstico, ferramentas, eventos
              Preferências                inicialização, aparência, idioma, atalhos, redefinir, sobre
rodapé: ● estado do serviço (abre o Diagnóstico)
barra inferior global: alterações pendentes · Descartar · Aplicar
```

- Opções de cada tema ficam **no contexto do tema** (página de detalhe ou a
  seção dedicada), não na sidebar. Kojiro, Media Player e Brother Away ficam
  sempre visíveis; quando não estão em uso, um banner oferece "Usar".
- Abaixo de 640sp a sidebar recolhe (botão voltar); abaixo de 1100sp as
  divisões lado a lado empilham. Um único mecanismo
  (`components.Adaptive.attach`) cria os dois breakpoints — a libadwaita
  aplica só o último breakpoint que bate, então eles não podem ser
  independentes.

## Módulos

| Módulo | Responsabilidade |
| --- | --- |
| `config_gui.py` | janela, sidebar, seções sob demanda, modelo de edição, persistência (`save_settings`/`run_helper`), prévias ao vivo, desempenho, diagnóstico |
| `gui/components.py` | componentes e workers |
| `gui/dashboard.py` | Início |
| `gui/theme_gallery.py` | Galeria de Temas + páginas de tema |
| `gui/brother_away_page.py` | Brother Away |
| `gui/preferences_page.py` | Preferências (estilo da janela em `$XDG_CONFIG_HOME/big-screen-monitor-display/gui.json`) |
| `displays_page.py` | Meus Displays (galeria, página do display, comandos) |
| `media_player_page.py` | Big Media Player (Tocando agora, galeria, subpágina de opções) |
| `kojiro_page.py` | Kojiro (barra compacta, painel adaptável) |

Contratos preservados com as páginas: `values`, `saved`, `status`, `_set`,
`_combo`, `_switch`, `_scale`, `_group`, `toast`, `_error`, `_apply`,
`apply_button`, `_refresh_dirty`, `_device_size`, `_reload_widgets`. Novo:
`_register` (vários controles por chave, sincronizados), `show_section`,
`live_preview`, `theme_option_groups`.

## Ciclo de vida e custo

| Regra | Implementação |
| --- | --- |
| Seções construídas na primeira visita | `show_section` → `_build_section` |
| Nada bloqueante na GTK | varredura USB, `systemctl`, diagnóstico e exportação em `SerialWorker`/threads; resultado por `GLib.idle_add` |
| Prévia só renderiza na tela | `DisplayPreview` emite `visible-changed` em `map`/`unmap`; renderizador dorme sem timeout |
| Janela sem foco/minimizada | prévias mostram um quadro estático e dormem (`notify::is-active`, `notify::suspended`) |
| Início | prévia limitada a 4 q/s (visão geral) |
| Quadros | textura no formato nativo do Cairo (BGRA pré-multiplicado) criada no worker; exibida 1:1 quando cabe |
| Miniaturas | uma thread, LRU 64, chave = tema + tamanho + assinatura das opções relevantes |
| Fechar | timers removidos, renderizadores e miniaturas parados, Kojiro/media fechados |

## Segurança

Sem mudanças no modelo: a janela roda como usuário; gravações em
`/etc/big-screen-monitor-display` só via `pkexec bsm-helper apply-settings`
(JSON validado pelo helper); comandos por display via spool validado
(`settings.validate_command`); dispositivos desconhecidos só recebem algo
depois que o usuário escolhe o modelo e aplica. A preferência de estilo da
janela é por usuário, sem senha.
