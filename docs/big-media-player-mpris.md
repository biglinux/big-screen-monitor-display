# Big Media Player — MPRIS e seleção do player

## Cliente MPRIS (`bsmd/media/mpris.py`)

- **Descoberta**: `ListNames` uma vez; depois apenas `NameOwnerChanged`. Um
  aplicativo é suportado se possui um nome `org.mpris.MediaPlayer2.*` — o nome
  do aplicativo nunca é garantia. `playerctld` é ignorado (ele espelha os
  outros players e os duplicaria).
- **Estado**: `GetAll` nas duas interfaces quando o player aparece; depois só
  `PropertiesChanged` e `Seeked`. Propriedades invalidadas (Chromium) são
  relidas.
- **Posição**: o MPRIS não sinaliza `Position`. Ela é lida ao mudar o estado ou a
  faixa, após `Seeked`/comandos e a cada 5 s apenas para players tocando. O
  tema interpola com `CLOCK_MONOTONIC` × `Rate`; pausado, a barra para.
- **Tempos** em microssegundos (`mpris:length`, `Position`); 0, negativo ou
  absurdo = desconhecido. Sem duração → "AO VIVO"/`--:--`, nunca um total fictício.
- **Comandos**: `PlayPause`, `Play`, `Pause`, `Next`, `Previous`, `Stop`,
  `Seek`, `SetPosition` e as propriedades `Shuffle`, `LoopStatus`, `Volume`.
  Recusados localmente se o player não anunciar a capacidade (`CanGoNext`
  etc.); erros do player são relatados, sucesso só após a resposta.
- Todas as chamadas são assíncronas com timeout de 2,5 s: um player travado não
  bloqueia nada.

### Metadados usados

`xesam:title`, `xesam:artist` (ou `xesam:albumArtist`), `xesam:album`,
`xesam:comment` (como descrição, quando existe), `xesam:url`,
`mpris:artUrl`, `mpris:length`, `mpris:trackid`.

Linha secundária: descrição → artista → álbum → aplicativo de origem.

### Vídeo e navegadores

YouTube e outros sites aparecem quando o navegador publica a sessão de mídia
(Firefox: `media.hardwaremediakeys.enabled`, padrão ligado; Chrome/Chromium:
padrão ligado). A miniatura só aparece se o site fornecer artwork
(`mpris:artUrl`); caso contrário fica a arte de substituição. Nenhum site é
consultado por scraping. Miniaturas não quadradas são mostradas inteiras
(com faixas), não cortadas.

## Capas (`bsmd/media/artwork.py`)

| Origem | Regras |
| --- | --- |
| `file://` | arquivo regular, ≤ 6 MiB (lido como o usuário, no agente) |
| `data:image/...;base64` | ≤ 6 MiB |
| `http(s)://` | timeout 6 s, ≤ 6 MiB, até 3 redirecionamentos, cada salto só http(s) e só para endereços públicos (bloqueia loopback, privados, link-local, multicast, reservados), sem credenciais na URL |

Decodificação com Pillow, apenas JPEG/PNG/WebP/GIF/BMP, ≤ 40 Mpx, reduzida a
240 px. Cache em `~/.cache/big-screen-monitor-display/art` (300 arquivos /
40 MB, LRU) + 24 em memória. Downloads em threads (2 simultâneos), nunca no
loop principal nem no render.

## ActivePlayerManager (`bsmd/media/selection.py`)

Função pura de (lista de players, escolha anterior, agora). Cada player traz
os instantes em que começou a tocar e em que esteve ativo pela última vez,
medidos pelo agente — agente e displays chegam ao mesmo resultado.

| Modo | Regra |
| --- | --- |
| Automático (padrão) | mantém o player atual enquanto toca; outro só assume se o atual estiver pausado/parado/ausente **e** o novo tocar há ≥ 2 s; clipes < 8 s nunca assumem (sons de notificação, prévias ao passar o mouse) |
| Último utilizado | o player com atividade mais recente assume na hora |
| Fixo | o player cujo nome/identidade contém o padrão (ex.: `spotify`); automático enquanto ele não existir |
| Troca automática desligada | mantém o atual enquanto existir |
| Ignorados | lista separada por vírgulas; nunca escolhidos |
| Seleção manual | na janela: "Player" → um player detectado (vale até ele fechar ou voltar a "Automático") |

Quando um player candidato está esperando os 2 s, o agente agenda a reavaliação
exatamente para esse instante (não espera o heartbeat de 5 s).

## Aplicativos

A compatibilidade depende da interface MPRIS, não do nome. Verificado neste
desenvolvimento: **Google Chrome** e **Mozilla Firefox** reais (sessões de vídeo
detectadas, título, duração, posição e capacidades lidos) e players de teste
D-Bus. Spotify, VLC, Rhythmbox, Elisa, Clementine, Strawberry, Audacious,
Amarok, Lollypop e mpv (com `mpv-mpris`) seguem a mesma especificação, mas
**não estavam instalados** no ambiente e não foram testados diretamente.

## Comandos de linha (atalhos de teclado)

```
big-screen-monitor-display.sh --media play_pause
big-screen-monitor-display.sh --media next | previous | stop | shuffle | loop
big-screen-monitor-display.sh --media volume_up | volume_down | mute
big-screen-monitor-display.sh --media volume_set --value 35
big-screen-monitor-display.sh --media seek_by --value 10000000     # +10 s
```

Vão para o agente (o mesmo player do display); sem agente, um núcleo de curta
duração é usado. Associe-os a teclas nas configurações de atalhos do KDE/GNOME.
