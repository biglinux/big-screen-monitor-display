# 01 — Auditoria técnica (versão 3.1.0)

Inventário feito sobre o commit `a911021` antes de qualquer alteração, com o
hardware real conectado (AX206 `1908:0102`, 800×480, USB 5-1.4.4) e o pacote
`26.03.28-1921` instalado.

## Estrutura encontrada

| Arquivo | Linhas | Papel |
| --- | --- | --- |
| `usr/share/big-screen-monitor-display/main.py` | 3547 | coleta, drivers, 7 temas, laço principal, ícone de bandeja |
| `usr/share/big-screen-monitor-display/config_gui.py` | 539 | janela GTK4/libadwaita |
| `usr/lib/systemd/system/big-screen-monitor-display.service` | 26 | `Type=simple`, `User=root`, `Restart=always` |
| `usr/lib/udev/rules.d/99-big-screen-monitor-display.rules` | 6 | `MODE="0666"` nos dois dispositivos |
| `etc/sudoers.d/big-screen-monitor-display` | 6 | `%wheel NOPASSWD` para restart/enable/disable |
| `locale/*.pot` | 0 | catálogo vazio: nenhuma string marcada para tradução |

Na máquina de teste também existiam uma cópia da unit em
`/etc/systemd/system/` e um drop-in `10-anti-travamento.conf` criados
manualmente, e o `main.py` instalado tinha *sleeps* alterados à mão — sinais de
tentativas anteriores de contornar travamentos.

## Achados com evidência

| # | Severidade | Achado | Evidência |
| --- | --- | --- | --- |
| 1 | Crítica | AX206: `scsi_wrap()` captura toda exceção e devolve `-1`; o handle USB nunca é reaberto | Kernel: `00:30:44 usb 5-1.4.4: USB disconnect, device number 12` → `13`; o serviço seguiu "ativo" até reinício manual às 02:09 |
| 2 | Crítica | Turing: `serial.Serial(..., rtscts=True)` sem `write_timeout` → `write()` pode bloquear para sempre | Código (`main.py:749`); comportamento documentado do pyserial |
| 3 | Alta | GKrellM roda `docker ps`, `playerctl` (2×) e `amixer` **a cada quadro**, sem timeout e com `shell=True` | Código; um daemon Docker travado congela o laço único de renderização |
| 4 | Alta | Laço único sem watchdog: qualquer bloqueio congela a tela com o serviço "saudável" | `Type=simple`, nenhum `sd_notify` |
| 5 | Alta | CPU: conversão RGB565 da AX206 em Python puro | 110 ms por quadro 800×480 (medido) |
| 6 | Alta | Coletor a cada 0,4 s executa `powerprofilesctl` (programa Python) e varre todos os processos | 89 ms de CPU em processo filho + 36 ms por ciclo (medido) |
| 7 | Alta | Consumo total | Original sem patches: **49,6%** de um núcleo (medido); journal da versão com patches: 7h13min de CPU em 26h11min |
| 8 | Média | Turing 5"/8,8": tiles 48×20 com divisão inteira ignoram 32 px à direita em 800×480 | Código + teste `test_edge_pixels_are_detected_for_non_multiple_sizes` |
| 9 | Média | Serviço root lê o `settings.json` do **primeiro** `/home/*` encontrado; GUI grava no usuário atual | `get_settings()` |
| 10 | Média | Serviço como root e udev `0666` (qualquer processo local escreve no display) | unit e regras udev |
| 11 | Média | Ausente na inicialização → `sys.exit(1)` → reinício a cada 5 s para sempre (`StartLimitBurst=0`) | `AX206_DPF.__init__` |
| 12 | Baixa | `lspci` com `shell=True`; `except:` nus; fontes TrueType carregadas a cada quadro | Código |
| 13 | Baixa | Traduções inexistentes (`.pot` vazio), PKGBUILD copiava `.po` sem compilar | `locale/` e PKGBUILD |
| 14 | Baixa | `post_upgrade` reativava o serviço mesmo que o usuário o tivesse desativado | `pkgbuild.install` |

## O que foi preservado

Os sete temas (Dark, Light, Neon, Cyberpunk, GKrellM, Planet, Old Computer)
foram movidos **sem reescrita** para `bsmd/legacy_themes.py`; as mudanças nesse
arquivo se limitam a cache de fontes, comandos externos assíncronos e
`except Exception`. A sobreposição de textos do GKrellM em 480×320 já existia
no original (comparação lado a lado feita na auditoria) e não foi alterada.

Pendências e decisões de cada achado estão nos documentos 02 a 05.
