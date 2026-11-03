# 15 — Múltiplos displays

## Modelo

```
                  ┌─────────────── Runtime (supervisor) ───────────────┐
 telemetria (1 s) │ descoberta 2 s · settings · watchdog · status · spool│
   compartilhada  └──────┬───────────────────┬───────────────────┬──────┘
                         │                   │                   │
                 DisplaySession      DisplaySession      DisplaySession
                 usb-5-1.4.4         usb-3-2             simulated
                 render ▸ mailbox ▸ transporte  (cada uma com tema, estado,
                 backoff, estatísticas e incidentes próprios)
```

- A telemetria é coletada uma vez e lida por todos os temas.
- Cada sessão tem suas threads de render e transporte; só a sua thread de
  transporte toca o seu dispositivo.
- Uma falha num display não pausa os outros; o reset USB (AX206) atinge só
  o próprio dispositivo; o processo só sai para o systemd reiniciar quando
  todos estão em `failed`.
- O watchdog do systemd só recebe ping se telemetria e todas as sessões
  progridem.
- Sessões de displays desconectados são encerradas após 45 s; ao reconectar
  na mesma porta a sessão volta com as mesmas configurações.

## Configurações por display

```json
{
  "theme": "standard", "brightness": 70,
  "displays": {
    "usb-5-1.4.4": {"name": "Gabinete", "theme": "brother_away", "orientation": "vertical"},
    "usb-3-2":     {"brightness": 40, "profile": "weact_b"},
    "usb-3-3":     {"enabled": false}
  }
}
```

Chaves próprias: `enabled`, `name`, `profile`, `rev_c_size`, `led_color`.
Qualquer chave global que não seja exclusivamente global (tema, orientação,
brilho, perfil de desempenho, opções dos temas) pode ser sobrescrita; o que
não for sobrescrito segue o global. Chaves só globais: `model`, `size`,
`language`, `sound_*`, `ui_sound_feedback`. Máximo de 16 displays; ids
validados por expressão regular.

Orientações: `horizontal`, `vertical`, `horizontal_flipped`,
`vertical_flipped`.

## Comandos por display

A interface envia comandos ao serviço por um *spool* em
`/run/big-screen-monitor-display/commands/` (do usuário do serviço; o
`bsm-helper display-command` grava lá via polkit, recusando links simbólicos
e validando o JSON). Ações: `identify`, `pattern` (barras, grade,
gradiente, orientação, branco, preto; 2–60 s), `clear_pattern`,
`reconnect`. O padrão some sozinho e o tema volta com um quadro completo.

## Status

`status.json` mantém os campos de topo da 4.0 (descrevendo o primeiro
display) e acrescenta `displays` (estado, dispositivo, capacidades,
estatísticas, sensores, incidentes de cada um) e `pending` (detectados que
esperam escolha de modelo).

## Layouts responsivos

- Painéis com lado menor < 128 px ou área < 36 000 px² (WeAct 0,96") usam
  o layout compacto (`bsmd/compact.py`): relógio e 3–4 métricas grandes com
  a paleta do tema. Brother Away mantém a cena e reduz o HUD e os balões.
- Painéis redondos (Turing 2,8" USB): o tema é desenhado no quadrado
  inscrito (70% do diâmetro) e centralizado; nada importante fica fora do
  círculo.
- Testado de 80×160 a 1920×720, nas duas orientações
  (`tests/test_responsive.py`).

## Simulação

```
python3 main.py --simulate 480x320,160x80,480x480:round --snapshot /tmp/frame.png
python3 main.py --simulate 800x480 --simulate-latency 5 --simulate-throughput 1000000
```
