# 22 — Integração do PR #11 (openSUSE/Regata OS e bandejas)

PR: <https://github.com/ruscher/big-screen-monitor-display/pull/11>, de Marcos
Queiroz Gomes (`marquimRcc`), branch `main` do fork — 3 commits, 43 arquivos:
instalador/desinstalador para openSUSE, bandeja DeepCool (`tray/`), bandeja da
tela 3,5" (`screentray/`), lançadores, ícones e uma correção na galeria de temas.

Os commits do PR foram mesclados como estão (autoria preservada) na branch
`integracao/pr11`, e as correções vieram por cima, em commits separados.

## Os sete achados da revisão automática

| # | Achado | Correção |
| --- | --- | --- |
| P1 | `psutil` ausente na lista do `zypper` | lista por família com a versão do Python (`python313-psutil`); validado instalando de verdade no Tumbleweed |
| P2 | PyQt não declarado | `python-pyqt6` no PKGBUILD, PyQt6 nas listas de todas as famílias; sem PyQt o lançador explica qual pacote instalar |
| P2 | galeria lia `schemes` mas os cartões tinham `scheme` (Dark/Neon aplicavam o esquema errado) | catálogo novo com as variantes reais (8 do Standard, 5 do Planet, 4 do Old Computer), conferido por teste contra `bsmd.dashboard` e o esquema de configurações |
| P2 | tema global da bandeja encoberto por override por display | `bsmd.control.set_global` remove os overrides da chave, como a galeria da janela; escolher uma tela grava só nela |
| P2 | conexão da tela só reavaliada quando o `settings.json` mudava | estado vem do `status.json` do serviço (que acompanha o udev), verificado a cada 2 s com um `stat()` |
| P2 | cor OpenRGB gravada em `led_color` (apagava as LEDs da XuanFang) | cor só no arquivo da bandeja; `led_color` nunca é tocado |
| P2 | desinstalação deixava lançadores, `.desktop` e ícones das bandejas | manifesto de instalação; desinstalação remove exatamente o que foi instalado, inclusive os nomes antigos |

## Outros problemas encontrados na auditoria

| Problema no PR | Risco | Correção |
| --- | --- | --- |
| Tabela de modelos própria: 0x0001 = "AK620", 0x0005 = "AK400" | nome errado (0x0001 é o AK400; 0x0005 é o gabinete CH560) | modelos e famílias de `bsmd/displays/deepcool/models.py` |
| Sem sensor, temperatura 35 °C | número falso mostrado como real | "—" e "sem sensor"; teste garante |
| `led_color`, `dc_*` gravados direto no `/etc` quando gravável, sem validação | configuração inválida/parcial | sempre `bsmd.settings.save` (validado, atômico, `.bak`) ou o helper |
| OpenRGB: escolhia "a primeira placa-mãe" ou o 1º dispositivo e redimensionava zonas (`-sz 30`) ao iniciar | alterava LEDs e zonas de equipamentos não escolhidos | só o dispositivo escolhido, conferido pelo nome, sem `--size`; delega ao servidor OpenRGB |
| Instalador: `TARGET_USER=${SUDO_USER:-marcos}`, `usermod -aG dialout` | usuário fixo; acesso a todas as portas seriais | removidos; o udev já dá acesso pelo `uaccess` |
| Instalador copiava `settings.json` do repositório por cima do `/etc` | apagava as configurações do usuário | `settings.json` nunca é tocado; cópia verificada antes do upgrade |
| `cp -r usr/* /usr/` sobre um pacote instalado | arquivos do pacman sobrescritos | recusa quando o pacote está instalado |
| Bandejas: `systemctl`/`pkexec` síncronos na thread da interface | interface congelada | tudo em segundo plano, com indicador de progresso |
| "Reiniciar": `systemctl --user restart` + `pkexec systemctl` | pedia senha e chamava systemctl com root genérico | `bsm-helper service restart` (verbo fixo do Polkit) |
| Menus com cores fixas (`#1c2128`) | contraste ruim no tema claro | menus nativos; janelas pela paleta do sistema |
| Janela da galeria sem moldura posicionada pelo cursor | não funciona no Wayland | janela comum; posição só no X11 |
| Brilho 0 como "apagar" sem guardar o anterior | perdia o valor | "Religar" restaura o brilho anterior |
| Preset do Kojiro gravado como nome | rótulo mudava, layout não | a bandeja não troca layouts do Kojiro |
| `i18n` próprio com dicionários | sem as 28 línguas do projeto | `bsmd.i18n` (gettext; a CI traduz) |
| Nomes `deepcool-digital`, `screen-monitor-tray` | colisão com outros projetos | `big-screen-monitor-deepcool`, `big-screen-monitor-tray` |

## Problemas que só os testes reais mostraram

* `pkexec` não vem com o `polkit` no openSUSE (e no Debian): adicionado e verificado pelo instalador.
* Três gravações rápidas em threads paralelas podiam terminar fora de ordem: gravações serializadas.
* Com serviço e execução manual ativos, a bandeja alternava entre os dois `status.json`: vale o que tem displays.
* Cartões e notas cortados na borda direita (GNOME, openSUSE, wlmaker): colunas pela largura da viewport e chips em layout de fluxo.
* `apt-get update` falhava no Mint live (fonte `cdrom://`).

## Desempenho (sessão real, host `big-wm-tray`, 10 s de aquecimento + 60 s em repouso)

| Bandeja | CPU em repouso | RAM (RSS) | Threads |
| --- | --- | --- | --- |
| Telas — PR original | 0,00 % | 89,8 MB | 4 |
| Telas — integrada | 0,12 % | 78,6 MB | 4 |
| DeepCool — PR original | 0,15 % | 56,4 MB | 4 |
| DeepCool — integrada | 0,17 % | 72,4 MB | 9 |

O custo de repouso ficou equivalente. A bandeja das telas usa menos memória e
consulta o status a cada 2 s (o original não percebia conexões). A DeepCool
usa ~16 MB a mais (telemetria do projeto para ler o sensor do mesmo jeito que o
serviço) e 5 threads ociosas do pool do Qt. Miniaturas reais: subprocesso de
~0,5 s para os 7 temas (pico de 91 MB, termina em seguida), com cache.
Importar `bsmd.control` custa ~30 ms (antes, ler o status pela `bsmd.runtime`
custava ~106 ms e carregava Pillow e numpy).

## Segurança

Nada novo roda como root: as bandejas usam só os verbos fixos do `bsm-helper`
(`apply-settings`, `service`, `recover`, `display-command`) pelo Polkit
existente — `apply-settings` e `display-command` sem senha na sessão ativa,
`service` com autenticação de administrador. Nenhuma regra udev, Polkit ou unit
systemd foi alterada. Os arquivos que as bandejas escrevem ficam no
`~/.config`/`~/.local/state` do usuário (escrita atômica).
