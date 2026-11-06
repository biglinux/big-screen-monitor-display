# 04 — Testes e benchmarks

## Testes

`python3 -m pytest -q tests` → **1237 passando** (linha de base: 1229; +8
novos). Executado nesta máquina (Manjaro/BigCommunity, Python 3.14,
GTK 4 + libadwaita 1.9, sessão gráfica real).

| Arquivo | O que verifica |
| --- | --- |
| `tests/test_gui.py::test_window_flows` | janela real (via `tests/gui_driver.py`): as 9 seções constroem; sem foco a prévia mostra quadro estático e não anima; prévia visível anima e prévias fora da tela param; barra de pendências aparece/some; **Aplicar grava** o arquivo; **Descartar** volta ao salvo; controles da mesma chave sincronizados; **Restaurar padrões** carrega os padrões sem gravar; galeria com 7 miniaturas reais, abre as 7 páginas, "Usar este tema", busca; 14 histórias com miniatura e uma tocada na prévia; 15 skins e seleção; subpágina de opções do player; 2 displays simulados com cartão e página própria, sobrescrita por display; seletor de display no Início; Kojiro ativo só na própria seção; cartões de perfil; ao fechar, renderizadores parados e timers removidos |
| `test_service_stopped_states` | serviço parado: cartão de estado no Início e no Diagnóstico, rodapé "Serviço parado" |
| `test_narrow_window_collapses` | janela de 400 px: sidebar recolhida, layouts empilhados, cabe na largura |
| `test_polkit_cancel_is_reported` | `pkexec` retornando 126 → "Authorization was cancelled or denied." |
| `test_helper_errors_and_success` | resposta JSON do helper, helper ausente |
| `test_save_settings_validates_invalid_values` | valores inválidos corrigidos, arquivo 0644 |
| `test_gui_preferences_are_per_user` | `gui.json` por usuário, arquivo corrompido ignorado |
| `test_theme_signature_follows_only_relevant_keys` | miniaturas só re-renderizam quando a opção do próprio tema muda |

Isolamento (regra do AshyWall): cada sessão de janela roda em
`dbus-run-session`, com `BSM_CONFIG`/`BSM_STATUS` temporários,
`GSETTINGS_BACKEND=memory` e `XDG_*` próprios. Os testes de janela são pulados
sem sessão gráfica (CI mínimo); os demais rodam em qualquer lugar.

Também validado: `ruff` (E, F, W, B) limpo no código novo/alterado;
`msgfmt -c` em todos os catálogos.

### O que não foi validado

- Hardware: um AX206 800×480 real está conectado e aparece em todas as
  telas (Início, Meus Displays, Diagnóstico); os fluxos com **dois** displays
  e com display desconectado/sem resposta foram testados com status
  simulado. Turing, WeAct e outros não estavam disponíveis.
- KDE Plasma/GNOME em Wayland e X11, escala fracionária e HiDPI: só a sessão
  desta máquina (escala 1). Leitor de tela (Orca): rótulos acessíveis
  definidos, sem teste com Orca.
- Polkit real (diálogo de senha): coberto por `pkexec` simulado.

## Benchmarks

Ferramenta: `tools/ui_benchmark.py` (mesmo procedimento para as duas
versões; a 4.4 rodou de uma cópia de `a4152aa`). Janela em sessão D-Bus
isolada, tema configurado Brother Away (animado: pior caso), status real do
serviço (AX206 800×480), mediana de 3 rodadas. "Em regime" = soma por thread
num intervalo de 5 s depois de estabilizar.

| Métrica | 4.4 | 5.0 |
| --- | --- | --- |
| Janela desenhada | 1,17 s | **0,53 s** |
| Interface utilizável | 1,31 s | **0,58 s** |
| RAM ao abrir | 278 MB | **163 MB** |
| CPU com prévia animada visível (em regime) | 10,4 % | **10,2 %** |
| CPU em repouso no Início — Brother Away / Padrão | 3,8 % / 4,0 % | 4,9–5,1 % / 4,8 % |
| Troca de seção já visitada | 20–30 ms | 17–31 ms |
| Primeira visita: Kojiro / Media Player / Brother Away | 0 (construídos ao abrir) | 300 / 125 / 75 ms |
| RAM depois de visitar todas as seções | 288 MB | 347 MB |
| RAM depois de mais 16 ciclos pelas 9 seções | 288 MB | 348 MB (estável) |
| Threads | 35 | 26 |

### Leitura

- **Abertura 2,2× mais rápida e 41 % menos memória** porque as seções só são
  construídas quando visitadas.
- **Repouso no Início (+1 ponto)**: a tela inicial agora tem uma prévia ao
  vivo (a 4.4 abria numa lista sem prévia). Limitada a 1 q/s em temas
  estáticos e 2 q/s nos animados; com a janela fora de foco ou minimizada ela
  vira um quadro estático e não consome nada.
- **Prévia animada igual** à 4.4, apesar de maior e mais nítida (1:1), porque
  os quadros chegam no formato nativo do Cairo: antes do ajuste a GTK
  convertia cada quadro em ~16 threads do pool (+4,8 %).
- **Memória máxima maior** ao visitar tudo: miniaturas das galerias (7 temas,
  14 histórias, 15 skins), o núcleo MPRIS do Media Player e as prévias das
  seções extras que a 4.4 não tinha. Limitada (LRU de 64 miniaturas) e
  estável em navegação longa.
- **Primeira visita ao Kojiro em 300 ms**: o custo que antes entrava na
  abertura de toda janela agora só ocorre ao abrir o estúdio.

Correções feitas a partir das medições: prévia inativa dormindo sem
timeout; quadros em BGRA; `SCALE_DOWN` em vez de ampliar; prévia do Início
limitada; quadro estático fora de foco (corrigiu um spinner que girava sem
parar e consumia ~40 %); varredura USB e `systemctl` fora da thread da GTK.
