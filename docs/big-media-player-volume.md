# Big Media Player — volume do sistema

A barra de volume mostra, por padrão, o **volume real da saída padrão do
computador** — o mesmo do applet do KDE Plasma/GNOME e das teclas de volume —
e não o volume interno do player.

## Backends (`bsmd/media/volume.py`)

O primeiro que funciona é usado; se ele não consegue falar com o servidor de
áudio, o próximo é tentado.

| Backend | Leitura | Mudanças | Escrita |
| --- | --- | --- | --- |
| `pulse` (PipeWire via pipewire-pulse, ou PulseAudio) | `pactl --format=json list sinks` + `get-default-sink` | **eventos** de `pactl subscribe` (sink/server/card), debounce 60 ms | `pactl set-sink-volume/-mute` |
| `wpctl` (WirePlumber sem pactl) | `wpctl get-volume @DEFAULT_AUDIO_SINK@` | leitura a cada 2 s (wpctl não tem fluxo de eventos) | `wpctl set-volume/-mute` |
| `alsa` | `amixer -M get Master` | leitura a cada 2 s | `amixer set Master` |

Todos os processos são assíncronos (`Gio.Subprocess`), nunca na thread de
renderização. Se `pactl subscribe` termina (PipeWire/PulseAudio reiniciou), é
relançado com recuo 1, 2, 5, 10, 30 s.

### Detalhe encontrado durante o desenvolvimento

Em algumas versões, `pactl --format=json` imprime `"(null)"` como descrição de
saídas com caracteres não ASCII ("Estéreo analógico"). O agente nunca mostra
`(null)`: busca as descrições em `LC_ALL=C pactl list sinks` (UTF-8 correto)
uma vez por saída nova.

## Medido nesta máquina (PipeWire 1.x, pipewire-pulse)

| Ação externa | Refletido no agente |
| --- | --- |
| `wpctl set-volume … 0.22` (equivalente a tecla/applet) | 19 % → 22 % em ~90 ms |
| mute / unmute | detectados em ~90 ms |
| `set_percent(19)` pelo próprio agente | aplicado e confirmado pelo evento |
| nome da saída | "CM106 Like Sound Device Estéreo analógico" |

## Regras

- Valores acima de 100 % (amplificação) são **mostrados como são**; a escala da
  barra se estende até o maior entre 100 %, o máximo seguro e o valor atual.
- Os controles (janela, `--media volume_up`) respeitam o **máximo seguro**
  (`bmp_volume_max`, 100–150 %, padrão 100). Se o volume já estiver acima, o
  botão "+" não o aumenta.
- Passo configurável (`bmp_volume_step`, 1–20 %).
- **Saída acompanhada**: padrão (segue a troca para fone/headset
  automaticamente) ou uma saída escolhida na janela (`bmp_volume_sink`).
- **Volume do aplicativo** (`bmp_volume_source = player`): mostra o `Volume`
  MPRIS do player, rotulado `APP`; sem esse recurso no player, a barra volta ao
  volume do sistema. Os botões da janela sempre indicam qual volume controlam
  ("Volume do sistema"); nunca dois volumes ao mesmo tempo.
- Sem nenhum backend: a barra fica vazia com "--" e a janela mostra
  "Não foi possível acessar o volume do sistema."
