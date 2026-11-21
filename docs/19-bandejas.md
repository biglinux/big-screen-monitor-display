# 19 — Bandejas do sistema: telas USB e coolers DeepCool

Dois aplicativos de bandeja (Qt) acompanham o serviço:

| Aplicativo | Comando | Para quê |
| --- | --- | --- |
| Big Screen Monitor Tray | `big-screen-monitor-tray` | Galeria de temas, brilho, desligar/religar e orientação das telas USB (Turing/UsbPCMonitor 3,5", AX206, WeAct, Kipye, XuanFang, SmartMonitor...) |
| DeepCool Digital | `big-screen-monitor-deepcool` | Temperatura e uso da CPU no ícone; o que o cooler mostra, unidade, alarme e cor dos LEDs (OpenRGB) dos coolers AK, AG, LS, AK PRO, LD e MYSTIQUE |

Os dois nasceram no PR #11 (Marcos Queiroz Gomes, openSUSE/Regata OS) e foram
reconstruídos sobre a arquitetura do projeto (doc 22 explica por quê).

## Arquitetura

```
 serviço (systemd, DynamicUser)          bandejas (sessão do usuário, Qt)
 ───────────────────────────────         ─────────────────────────────────────
 udev/hotplug → drivers → painéis        traykit.base   instância única, host de bandeja,
 status.json (1 s) ───────────────────►                 poll barato (stat a cada 2 s),
 settings.json ◄── bsm-helper (pkexec) ◄─ bsmd.control  gravação validada e serializada
                                         screentray/    telas: galeria, brilho, orientação
                                         deepcooltray/  coolers: dc_*, alarme, OpenRGB
```

* **As bandejas nunca abrem um dispositivo.** Telas, estados e conexão/desconexão
  vêm do `status.json` que o serviço reescreve a cada segundo; o serviço é quem
  acompanha o udev e reconecta. Assim não há disputa pela porta serial ou pelo
  hidraw e uma tela desconectada aparece em até 2 s, sem laço de erros.
* **Gravação igual à da janela de configuração** (`bsmd/control.py`, usado pelos
  dois lados): validação de `bsmd.settings`, escrita atômica com `.bak`, sempre
  por `pkexec bsm-helper apply-settings` fora do modo de desenvolvimento. Uma
  gravação por vez; mudanças feitas durante uma gravação entram na próxima (a mais
  nova sempre por último). Se falhar (autorização negada, `pkexec` ausente), a
  janela volta a mostrar o valor realmente salvo e explica o erro.
* **Global ou por display, como a janela**: "Todas as telas" grava o valor global
  e remove os overrides daquela chave (o tema escolhido chega a todas); escolher
  uma tela grava só nela. As chaves `dc_*` são sempre do cooler escolhido.
* **Leve**: `bsmd.control`/`bsmd.statusfile` não importam Pillow, numpy nem os
  temas (≈30 ms). As miniaturas da galeria são desenhadas pelo mesmo
  `themes.render_for_panel` do serviço num subprocesso de baixa prioridade, no
  tamanho da tela escolhida, e guardadas em `~/.cache/big-screen-monitor-display/tray-thumbnails/`.

## Host de bandeja em cada ambiente

As bandejas usam StatusNotifierItem (via `QSystemTrayIcon`). Quando não há host:

| Situação | Comportamento |
| --- | --- |
| Aberto pelo menu, sem host | Abre a janela com todos os controles e uma nota explicando como obter o ícone (texto específico para GNOME e Window Maker) |
| Autostart, sem host | Espera até 45 s (o painel pode estar subindo); se não aparecer, sai em silêncio — nunca fica rodando inacessível nem abre janela a cada login |
| Aberto de novo com uma instância rodando | Não cria outro processo: a instância existente mostra a janela |

No GNOME o ícone exige a extensão "AppIndicator and KStatusNotifierItem Support"
(pacote `gnome-shell-extension-appindicator`); nada é instalado ou ativado
sozinho. No Big WindowMaker o host é o `big-wm-tray`; num Window Maker sem ele a
janela é o acesso. Detalhes por ambiente e resultados: doc 20.

Janelas: são janelas comuns (barra de título, foco, Esc fecha). No Wayland o
compositor não deixa um cliente se posicionar ao lado do ícone, então a posição
só é pedida no X11. Cores vêm da paleta do sistema (temas claro e escuro),
cartões e chips quebram de linha conforme a largura (testado em 360, 500 e
800 px), tudo navegável por teclado e com nomes acessíveis.

## Bandeja das telas

* **Galeria**: os sete temas com miniaturas reais e o selecionado marcado; as
  variantes de cor do Standard (8 esquemas), Planet (5 acentos) e Old Computer
  (4 esquemas) aplicam a variante clicada. Kojiro, Big Media Player e Brother
  Away mantêm seus editores na janela de configuração — a bandeja nunca troca o
  layout do Kojiro (descartaria os widgets do usuário).
* **Brilho** de 10 a 100 % (slider com espera de 450 ms antes de gravar) e
  atalhos 25/50/75/100 %; **Desligar/Religar** zera o brilho e restaura o valor
  anterior. Só ativos quando o aparelho declara brilho (`capabilities.brightness`
  no status); senão, ficam desativados com a explicação.
* **Orientação**: as quatro do serviço (paisagem/retrato, normais e invertidas).
* **Várias telas**: o seletor "Aplicar a" aparece com mais de uma tela.
* **Serviço**: reiniciar (ou iniciar, se parado) pelo `bsm-helper`.

## Bandeja DeepCool

* **Ícone**: temperatura da CPU (°C ou °F) num selo verde/âmbar/vermelho — o
  vermelho segue o limite de alarme configurado. Lida como o serviço lê: um
  arquivo `hwmon` (k10temp/coretemp/zenpower) e, se faltar, `psutil`. **Sem
  sensor aparece "—", nunca um número inventado.**
* **Janela**: CPU agora, e "No cooler" com os valores exatamente como enviados
  (vindos do status do serviço, com o motivo de cada valor ausente).
* **Opções por família** (`bsmd/displays/deepcool/models.py`):

| Família | O cooler mostra | Unidade | Alarme |
| --- | --- | --- | --- |
| AK (AK400/500/500S/620 DIGITAL) | Seguir o tema · Temperatura · Uso · Alternar | °C/°F | limite configurável |
| LS (LS520/720 SE) | Seguir o tema · Temperatura · Potência · Alternar | °C/°F | limite configurável |
| AG (AG300/400/500/620) | Seguir o tema · Temperatura · Uso · Alternar | só °C | limite configurável |
| AK PRO, AK400 PRO, LD, MYSTIQUE | campos fixos do firmware (explicado) | °C/°F (exceto MYSTIQUE) | do firmware, informado |

  IDs USB reais (VID 3633): 0x0001 AK400, 0x0002 AK620, 0x0003 AK500,
  0x0004 AK500S, 0x0008 AG — a primeira versão trocava AK400/AK620 e chamava o
  gabinete CH560 (0x0005) de AK400.
* **Aviso de alarme** na área de trabalho quando a lâmpada do cooler acende
  (decisão do serviço), uma vez por ocorrência.
* **LEDs (OpenRGB, opcional)**: a fita ARGB desses coolers vai a um conector da
  placa-mãe, então a cor é do OpenRGB. Nada acontece até o usuário escolher um
  dispositivo; só ele é alterado (`--device`, conferido pelo nome antes de cada
  mudança), zonas nunca são redimensionadas, o modo vem da lista do próprio
  dispositivo, e o servidor OpenRGB, se estiver rodando, faz o trabalho. A cor
  fica no arquivo da bandeja — nunca em `led_color`, que é das LEDs traseiras
  das telas XuanFang. A cor escolhida é reaplicada ao iniciar (as fitas a
  esquecem ao desligar).

## Arquivos

| Caminho | Conteúdo |
| --- | --- |
| `/usr/share/big-screen-monitor-display/{traykit,screentray,deepcooltray}/` | código |
| `/usr/bin/big-screen-monitor-tray`, `/usr/bin/big-screen-monitor-deepcool` | lançadores |
| `~/.config/autostart/big-screen-monitor-{tray,deepcool}.desktop` | "Iniciar com a sessão" (criado pela própria bandeja) |
| `~/.config/big-screen-monitor-display/screen-tray.json` | brilho a restaurar após "Desligar" |
| `~/.config/big-screen-monitor-display/deepcool-tray.json` | dispositivo e cor OpenRGB, aviso de alarme |
| `~/.local/state/big-screen-monitor-display/*.log` | registro (256 KB, com rotação) |

As entradas de autostart da primeira versão (`deepcool-digital.desktop`,
`screen-monitor-tray.desktop`) são trocadas pelas novas uma vez, e só quando
apontam para os lançadores daquela versão.

## Desenvolvimento

```bash
./run-local.sh tray        # bandeja das telas a partir do código
./run-local.sh deepcool    # bandeja DeepCool
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_trays.py
```

Sem PyQt6/PyQt5 o lançador mostra uma janela (GTK) com o pacote certo para a
distribuição (`bsmd/distro.py`), em vez de falhar em silêncio.
