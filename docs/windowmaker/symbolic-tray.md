# Bandeja das telas USB: ícone symbolic, ponto de estado e escolha do display

**Branch:** `feat/tray-symbolic-wm-icon` · **Data:** 22/11/2026

## Antes

* Ícone colorido (monitor azul) desenhado em Qt; o ponto só aparecia em estados
  ruins e usava laranja/vermelho/cinza.
* Serviço parado (`status.json` velho) aparecia **vermelho**, igual a um display
  desconectado.
* A escolha do display existia só na janela (combo "Aplicar a"), não no menu;
  não era guardada; se o display saía, a bandeja voltava **em silêncio** para
  "Todos os displays".

## Ícone

`traykit/icons.py` desenha um **monitor de traço simples monocromático** (tela,
pescoço e pé numa grade de 16 px, traço de 1 px em 16 px e 2 px em 22–32 px) na
**cor do texto do painel**, com o ponto de estado no canto superior direito,
dentro de um recorte transparente (nunca se funde ao contorno; o pé fica
inteiro, então continua lendo como monitor em 16 px).

Por que desenhado e não só um SVG `-symbolic` do tema: o ponto muda de cor, e
StatusNotifierItem/XEmbed recebem uma imagem; o painel não recolore imagens.
A cor do traço vem de `panel_foreground()`:

1. GNOME Shell → claro (a barra superior é escura nos dois estilos);
2. Qt 6.5+: esquema de cores do desktop (`styleHints().colorScheme()`), e o
   ícone é redesenhado quando ele muda (`colorSchemeChanged`/`paletteChanged`);
3. senão, luminosidade do texto da paleta.

Também é instalado `usr/share/icons/hicolor/symbolic/apps/big-screen-monitor-tray-symbolic.svg`
(mesma forma, `#2e3436`, recolorido pelo tema) para temas e terceiros. O ícone
colorido oficial continua na janela, no lançador e no menu do desktop.

Prévia gerada (16/22/24/32 px, fundos claro e escuro): legível nos quatro
tamanhos; o cinza também atenua o monitor (não depende só da cor).

## Cores e regras (`screentray/states.py`)

| Cor | Display | Ícone (agregado) |
|---|---|---|
| Verde | conectado e funcionando | todos os displays-alvo funcionando |
| Amarelo | conexão instável (`degraded`), iniciando, reconectando | algum alvo com problema/reconectando |
| Vermelho | luz de fundo apagada (brilho 0 num display que tem brilho), desligado na configuração, desconectado, sem resposta (`failed`), "reconecte o cabo" (`attention=replug`), **indisponível** (escolhido e ausente) | algum alvo vermelho, ou serviço rodando sem nenhum display |
| Cinza | — | **serviço parado** (`status.json` ausente ou velho) |

* Serviço parado tem precedência: o ponto fica cinza e cada display lê "Serviço
  parado", nunca "desconectado".
* "Alvo" = o display escolhido, ou todos com "Todos os displays".
* Com vários alvos vence o mais grave: vermelho > amarelo > verde.

## Menu

```
● Serviço funcionando
Display: AX206 DPF            ▸  ○ Todos os displays
                                 ─────────
                                 ● AX206 DPF — Conectado        ✓
                                 ● FOSTON … — Desconectado
Tema ▸ / Brilho ▸ / Orientação ▸ / Galeria… / Configuração… / Serviço / Iniciar com a sessão / Sair
```

* Lista exclusiva com marca de seleção e ponto da cor de cada display; a dica
  traz a descrição curta do problema.
* Com um único display, uma linha informativa substitui o submenu.
* A escolha é salva em `~/.config/big-screen-monitor-display/screen-tray.json`
  (`target`, `target_name`) e vale também para o combo da janela.
* **Display escolhido que sumiu:** continua escolhido e aparece como
  "Indisponível"; o ponto fica vermelho; Brilho e Orientação ficam desativados
  e não são aplicados em outro display; o tema ainda pode ser escolhido (fica
  salvo para quando ele voltar). O usuário escolhe outro no menu.
* **Todos os displays:** se algum display tem ajuste próprio diferente para a
  mesma chave, a bandeja pergunta antes (o ajuste individual seria substituído
  para sempre). Brilho só vai para displays com `capabilities.brightness`
  (sem luz de fundo ajustável, nada é escrito para eles).
* Displays sem `capabilities` no status (ex.: Android ainda conectando) não
  quebram o menu.

## Arquivos

`screentray/states.py` (novo), `screentray/app.py`, `traykit/icons.py`,
`traykit/window.py` (cores da pílula iguais às do ponto),
`usr/share/icons/hicolor/symbolic/apps/big-screen-monitor-tray-symbolic.svg`,
`uninstall-system.sh`, `locale/pt.po`, `tests/test_tray_status.py`,
`tests/test_trays.py`.

## Evidências

* **Big WindowMaker Wayland (wlmaker + `big-wm-tray`), testado de verdade:** a
  bandeja instalada foi fechada, a do worktree rodou com o status real do
  serviço (AX206 conectado, FOSTON BigFoston desconectado, alvo "Todos") e a
  captura de tela mostrou o monitor monocromático escuro sobre o fundo claro do
  dockapp com o **ponto vermelho**; depois a bandeja instalada foi reiniciada.
  O menu não foi aberto nessa sessão (verificado pelos testes offscreen).
* Testes: `tests/test_tray_status.py` (regras das cores, ícone monocromático com
  um só ponto colorido em 16/22/24/32 px nos dois fundos, SVG monocromático,
  seleção pelo menu e persistência, display ausente sem redirecionamento,
  confirmação em "Todos os displays", brilho só para quem tem, display sem
  capabilities, serviço parado cinza).

## Limitações

* A cor do painel é inferida (não há API para perguntar ao painel): num painel
  escuro com tema de aplicativos claro (ou o contrário), fora do GNOME, o traço
  pode ficar com pouco contraste.
* KDE Plasma, GNOME (AppIndicator), Cinnamon e XFCE não foram testados nesta
  sessão; o menu DBusMenu com submenu/radio é o mesmo mecanismo já usado.
* "Desligado" pela configuração só aparece se o serviço ainda listar o display;
  um display desabilitado sai do status e, se era o escolhido, aparece como
  "Indisponível".
