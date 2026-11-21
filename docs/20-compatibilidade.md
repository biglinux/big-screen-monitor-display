# 20 — Compatibilidade: distribuições, ambientes gráficos e hardware

Resultados de 21/11/2026, branch `integracao/pr11`. Cada linha diz **como** foi
testada; nada aqui é inferido. Legenda: **PASSOU** (executado e conferido),
**FALHOU**, **BLOQUEADO** (não deu para executar, motivo ao lado),
**NÃO VERIFICADO** (não executado), **N/A** (combinação que não existe).

## Distribuições (instalação, serviço, testes, remoção)

| Distribuição | Como | Instalação | Serviço | Testes na VM | Upgrade (preserva config.) | Remoção |
| --- | --- | --- | --- | --- | --- | --- |
| openSUSE Tumbleweed (20261119, Python 3.13) | VM live KDE, `install-system.sh` (zypper) | PASSOU | PASSOU | PASSOU (124) | PASSOU | PASSOU (0 arquivos restantes) |
| BigLinux (base Manjaro, Python 3.14) | VM live KDE, pacote do PKGBUILD com `pacman -U` | PASSOU (pacman resolveu `python-pyqt6`) | PASSOU | PASSOU (124/125) | — (pacote) | PASSOU (`pacman -R`) |
| BigCommunity (base Manjaro) | VM live GNOME, `pacman -U` | PASSOU | PASSOU | PASSOU (125) | — | NÃO VERIFICADO |
| Arch Linux (ISO 2026, Python 3.14) | VM live sem desktop, `install-system.sh` (pacman) | PASSOU depois de `pacman -Syu`* | PASSOU | PASSOU (128) | PASSOU | PASSOU (0 restantes) |
| Manjaro (edição oficial) | — | NÃO VERIFICADO (coberto indiretamente pelo BigLinux e pelo BigCommunity, que usam os repositórios do Manjaro) | | | | |
| Linux Mint 22.3 (Ubuntu 24.04) | VM live Cinnamon, `install-system.sh` (apt) — extra | PASSOU | PASSOU | PASSOU (128) | PASSOU | NÃO VERIFICADO |
| Regata OS | — | BLOQUEADO: sem ISO disponível; só a detecção por `os-release` é testada (automático) | | | | |

\* A ISO do Arch é de um mês antes; instalar dependências novas sobre ela daria
uma atualização parcial. O instalador parou com a orientação certa
("atualize com `pacman -Syu`") em vez de forçar — comportamento desejado.

Problemas encontrados **só** nesses testes reais e corrigidos: o `pkexec` é um
pacote separado no openSUSE e no Debian (sem ele nada chegava ao `/etc`);
`apt-get update` falhava no Mint live por causa da fonte `cdrom://`; e o
PKGBUILD tinha perdido uma quebra de linha numa edição (só gerar o pacote
mostrou).

Linux Mint 22.3 / Ubuntu 24.04: o serviço e as bandejas funcionaram, mas a
janela de configuração (GTK) exige libadwaita ≥ 1.6 e essas versões trazem a
1.5 — abrir a janela lá não foi testado.

Regata OS: as versões até a 23 eram baseadas no openSUSE Leap 15, onde
`python3` é o 3.6; o instalador agora recusa Python < 3.10 com uma mensagem
clara. Um Regata baseado no Tumbleweed segue o mesmo caminho validado acima.

## Ambientes gráficos (bandejas)

| Ambiente | Sessão | Distribuição / como | Ícone na bandeja | Menu | Janela | Resultado |
| --- | --- | --- | --- | --- | --- | --- |
| KDE Plasma 6 | Wayland | openSUSE TW (VM) | registrado no StatusNotifierWatcher, visível | — | clique num cartão gravou `theme=old_computer` no `/etc` pelo Polkit real | PASSOU |
| KDE Plasma 6 | Wayland | BigLinux, tema escuro (VM) | registrado, visível | — | legível no tema escuro | PASSOU |
| KDE Plasma 6 | X11 | BigLinux, tema claro (VM) | registrado, visível | menu nativo (DBusMenu) com submenus; Standard › Nord gravou `std_scheme=nord` | ok | PASSOU |
| KDE Plasma 6 | X11 | openSUSE TW | — | — | — | NÃO VERIFICADO |
| GNOME | Wayland | BigCommunity com extensão AppIndicator (VM) | registrado, visível na barra superior | — | ok | PASSOU |
| GNOME | Wayland | mesma VM, extensão desativada (= GNOME de fábrica) | sem host | — | aberto pelo menu: janela com a explicação da extensão; autostart: saiu após 46 s sem janela | PASSOU |
| GNOME | X11 | — | — | — | — | NÃO VERIFICADO |
| Cinnamon | X11 | Linux Mint 22.3 (VM) | registrado (host do xapp), visível | — | ok | PASSOU |
| Cinnamon | Wayland | — | — | — | — | NÃO VERIFICADO (sessão experimental no Cinnamon) |
| XFCE 4.20 | X11 | painel aninhado em Xvfb | o painel não subiu no Xvfb | — | a janela com a explicação apareceu (sem host) | NÃO VERIFICADO em sessão real |
| Window Maker (Big WindowMaker, wlmaker) | Wayland | sessão real deste computador | registrado no host `big-wm-tray` (7 → 8 itens) | — | displays reais (AX206 e FOSTON) | PASSOU |
| Window Maker (wmaker puro, sem `big-wm-tray`) | X11 | sessão aninhada em Xvfb | sem host | — | janela com a explicação do Window Maker, decorada pelo wmaker | PASSOU |
| Big WindowMaker (ISO) | X11/Wayland | — | — | — | — | BLOQUEADO: ISOs com permissão 600 do libvirt |

Em todas as sessões testadas: instância única (um segundo lançamento não
criou processo), PyQt6. PyQt5 foi validado pela suíte headless (abaixo), não
numa sessão gráfica.

Limitação observada no GNOME: ao reabrir a bandeja a partir de um terminal, o
Mutter mostra "está pronto" em vez de dar foco (prevenção de roubo de foco
sem token de ativação). Aberto pelo menu de aplicativos isso não acontece.

## Hardware

| Dispositivo | Como | Resultado |
| --- | --- | --- |
| AX206 DPF (1908:0102), físico | bandeja das telas → `pkexec bsm-helper` → serviço; brilho 30 % só no AX206 e restauração de 70 % | PASSOU (status confirmou o valor no aparelho; o override de tema do AX206 foi preservado; `settings.json` ficou idêntico ao de antes) |
| FOSTON FS-707DC, físico | apareceu na bandeja como "desconectado" (estado real do serviço) | apenas observado |
| Tela 3,5" Turing/UsbPCMonitor (1a86:5722) | não disponível | só painel simulado (`--simulate 480x320`) e status falso nos testes |
| DeepCool AK400/AK500/AK500S/AK620/AG400 | não disponível | só status falso nos testes (famílias AK, AG, LS, AK PRO); o protocolo dos coolers é testado no `test_deepcool.py` existente |
| OpenRGB | sem placa ARGB controlável aqui | só testes com a CLI simulada (nenhum dispositivo além do escolhido, sem `--size`, sem `--noautoconnect`) |

## Automático (CI e local)

| Suíte | Resultado |
| --- | --- |
| `pytest tests` local, PyQt6 | 1402 passando; 1 falha que depende do hardware desta máquina (`test_window_flows` faz uma varredura USB real e vê o FOSTON como "não identificado"; falha igual sem as mudanças) |
| `tests/test_trays.py` + `test_install.py`, PyQt6 e PyQt5 headless | todos passando nas duas bindings |
| `shellcheck` (instalador, desinstalador, `run-local.sh`, `pkgbuild.install`) | sem avisos |
| GitHub Actions | matriz PyQt6/PyQt5 em Ubuntu (o runner não reproduz sessões gráficas: os testes de bandeja rodam headless) |
