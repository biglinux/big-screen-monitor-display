# 10 — Relatório final (4.0.0)

## Diagnóstico

| Problema real | Causa | Como foi reproduzido |
| --- | --- | --- |
| Display congela com serviço "saudável" | AX206 re-enumera (resets do dispositivo, erros `-71`) e o driver engolia os erros do handle obsoleto | Kernel log (00:30:44 e 03:14:43) + desautorização controlada do dispositivo |
| Risco de congelamento na Turing | `write()` serial sem timeout com RTS/CTS | Análise de código; teste com serial falso |
| Risco de congelamento no GKrellM | `docker ps`/`playerctl`/`amixer` síncronos a cada quadro | Análise de código |
| CPU alta (49,6% de um núcleo) | RGB565 em Python (110 ms/quadro) + `powerprofilesctl` a cada 0,4 s | Medição no hardware |
| Configuração inconsistente | Serviço root lia o primeiro `/home/*` | Análise de código |
| Bordas sem atualização (Turing 5"/8,8") | Grade de tiles truncada | Teste unitário |

## Correções

- Drivers reescritos com erros classificados, timeouts em toda E/S, reabertura,
  blit parcial na AX206, bordas corrigidas e conversão vetorizada (`bsmd/drivers.py`).
- Pipeline em três threads com caixa de correio *latest-wins*, backpressure,
  cadências por tema e FPS adaptativo (`bsmd/runtime.py`, `bsmd/frames.py`).
- Monitor de saúde por progresso, máquina de estados explícita, backoff,
  histórico de incidentes, `Type=notify` + `WatchdogSec=30` (`bsmd/health.py`).
- Serviço sem root (`DynamicUser`), udev `0660`, Polkit + helper no lugar do
  sudoers, configurações em `/etc` com validação e gravação atômica.
- Temas legados preservados; registro de temas com fallback.
- Interface GTK4/libadwaita nova com prévia ao vivo, diagnóstico e desempenho.
- Traduções funcionando (`.pot` com 328 strings, `pt.po` completo, compilação no PKGBUILD).

## Desempenho (medido)

| Métrica | Antes | Depois |
| --- | --- | --- |
| CPU, tema Dark, AX206 800×480 | 49,6% | 3,2–3,5% |
| CPU, Brother Away 8 fps | — | 5,1% (sistema ocioso) |
| RGB565 + diff 800×480 | 110 ms | ~2 ms |
| Coleta de telemetria | 131 ms / 0,4 s | 2,9 ms / 1 s |
| Transferência típica | 768 KB / 115 ms | retângulos alterados; 13–18 ms em média (Brother Away) |
| USB no Brother Away | — | 0,9 MB/s |
| Recuperação após desconexão | nunca (manual) | 1,1–2,1 s |
| RSS | 60 MB | 58 MB (Dark) / 72 MB (Brother Away) |

## Confiabilidade

Recuperação comprovada no hardware em desconexão injetada, em um reset
espontâneo real, com dispositivo ocupado e com o processo congelado (watchdog
do systemd). Sem ciclos de reinício apertados: atrasos de 5 s a 5 min.

## Brother Away

- 36 clipes de animação, 15 expressões, dreads com física, 14 histórias
  (5 principais + 9 extras) e 12 atividades ociosas, 80 falas originais em 44
  contextos, ciclo de 24 h, lua com fase real, 6 estados de clima, persistência
  da jangada e das recordações, HUD estilo MangoHud, 5 reações à telemetria,
  som retrô opcional.
- Arte 100% gerada por código (sem recursos de terceiros); funciona em
  qualquer resolução por escala inteira.
- Funcionando no display real (unit endurecida, 8 fps).

## Validação

- Executados e aprovados: 97 testes automatizados; testes de hardware listados em 09; `makepkg` + `namcap`; `udevadm verify`; `systemd-sysusers --dry-run`; `xmllint`; `desktop-file-validate`; `msgfmt -c`; `ruff`.
- Não executados: 24/48/72 h; Turing real; Orca; instalação do pacote no sistema.

## Entrega

**Arquivos novos:** `bsmd/` (13 módulos + `brother_away/` com 9), `usr/lib/big-screen-monitor-display/bsm-helper`,
política e regra Polkit, `sysusers.d`, `tests/` (10 arquivos), `docs/`, `tools/make_screenshots.sh`,
`.github/workflows/tests.yml`.
**Alterados:** `main.py` (agora ponto de entrada), `config_gui.py` (reescrito), unit systemd, regras udev,
PKGBUILD, `pkgbuild.install`, lançadores, `.desktop`, `locale/`, README.
**Removido:** `etc/sudoers.d/big-screen-monitor-display`.
**Dependências declaradas agora:** `polkit`, `python-gobject`, `glib2`, `gtk4`, `libadwaita`,
`hicolor-icon-theme`, `pciutils` (`lspci`), `libusb` e `systemd` — já eram usadas, mas não estavam
declaradas. `lm_sensors` e `python-pystray` passaram a opcionais; som: `pipewire-audio`/`libpulse`/`alsa-utils`.
declaradas). `lm_sensors` e `python-pystray` passaram a opcionais.

### Instalação

```bash
cd pkgbuild && makepkg -si
```

### Ativar o Brother Away

Janela → **Temas** → *Brother Away — O Náufrago Perplecto!* → **Aplicar**
(ou página **Brother Away** → "Usar este tema"). Não reinicia o serviço.

### Diagnóstico

Janela → **Diagnóstico** → *Diagnosticar meu display*; ou
`python3 /usr/share/big-screen-monitor-display/main.py --diagnose`.

### Reverter

Reinstale a versão anterior do pacote (`sudo pacman -U` com o pacote 3.x do
cache em `/var/cache/pacman/pkg/`). As configurações novas ficam em
`/etc/big-screen-monitor-display/` e o estado em
`/var/lib/private/big-screen-monitor-display/`; ambos podem ser apagados com
segurança. A versão 3.x volta a usar `~/.config/big-screen-monitor/settings.json`,
que a migração não apaga.

## Revisão dos temas (4.0, segunda etapa)

- Escuro, Claro, Neon e Cyberpunk unificados no tema **Padrão** (`bsmd/dashboard.py`)
  com 8 esquemas e 25 opções; layout medido, sem sobreposição em nenhuma resolução.
- **GKrellM** reconstruído em módulos (`bsmd/gkrellm.py`), com dados reais no lugar
  dos módulos que inventavam valores.
- **Planet** e **Computador Antigo** corrigidos (sobreposições, quebra em 240×320,
  textos fictícios) e com opções novas.
- Abas de configuração por tema na janela, visíveis só para o tema aplicado.
- Migração automática das configurações antigas; 191 testes; ~1.200 linhas de
  código morto removidas; detalhes em `06-arquitetura-temas.md`.

