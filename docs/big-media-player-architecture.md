# Big Media Player — arquitetura

```text
Sessão gráfica do usuário (uid do usuário)
│
├── Spotify / Firefox / VLC / Rhythmbox ──── MPRIS2 (D-Bus de sessão)
├── PipeWire / PulseAudio ─────────────────── pactl subscribe (eventos)
│
├── Agente de mídia  (main.py --media-agent, autostart XDG)
│     bsmd/media/agent.py     MediaCore: junta tudo, gera instantâneos, executa comandos
│     bsmd/media/mpris.py     descoberta, metadados, posição, comandos (Gio, assíncrono)
│     bsmd/media/selection.py ActivePlayerManager (política pura, determinística)
│     bsmd/media/volume.py    volume real da saída padrão (pulse → wpctl → alsa)
│     bsmd/media/artwork.py   capas: limites, SSRF, cache, RGB cru
│     bsmd/media/spectrum.py  espectro FFT opcional (parec, só por escolha)
│     interface D-Bus br.com.biglinux.BigScreenMonitor.Media (janela, atalhos)
│                │
│                │  socket Unix, quadros JSON com tamanho prefixado, só agente → serviço
│                ▼
Serviço do display (systemd, DynamicUser, sandbox)
      bsmd/media/ipc.py       Server: SO_PEERCRED + usuário ativo do seat0, limites
      bsmd/media/hub.py       MediaHub: último instantâneo por uid, capas, espectro, "agente ausente"
      bsmd/bigmedia/          tema: layout responsivo, 7 skins, telemetria, telas de espera
      runtime / drivers       pipeline existente (render → transporte → USB/serial)
```

## Por que um agente de sessão

O serviço roda com `DynamicUser=yes`, `ProtectHome=read-only` e só
`AF_UNIX`/`AF_NETLINK`; ele não deve (nem pode) abrir o D-Bus de sessão de um
usuário. O agente roda **como o usuário**, dentro da sessão, e faz tudo que
depende dela: MPRIS, volume, download de capas. O serviço só recebe dados já
reduzidos e validados. Nenhuma operação usa `sudo`/`pkexec`.

O conceito reaproveita o agente de som opcional já existente (`--sound-agent`),
mas com IPC próprio porque o fluxo é inverso (sessão → serviço).

## IPC

- Socket: `/run/big-screen-monitor-display/media.sock` (no `RuntimeDirectory`
  do serviço; `$XDG_RUNTIME_DIR/big-screen-monitor-display/media.sock` em
  execuções manuais). Modo `0666` para que o agente consiga conectar; **quem**
  conecta é decidido pelo kernel.
- Autenticação: `SO_PEERCRED` informa o uid do par. Só é usado o uid do usuário
  ativo no `seat0` (`/run/systemd/seats/seat0`, `ACTIVE_UID`). Em troca rápida
  de usuário, os dados do usuário inativo deixam de ser exibidos. Sem logind,
  aceita o próprio uid do serviço e usuários regulares (uid ≥ 1000).
- Formato: 4 bytes big-endian + JSON UTF-8; máximo 2 MiB por quadro, 8
  conexões, 60 quadros/s por conexão. Quadro inválido → conexão encerrada.
- Mensagens (`bsmd/media/model.py`): `snapshot` (players, ativo, volume,
  estado do agente), `art` (pixels **RGB crus** até 320×320 — o serviço nunca
  decodifica um formato de imagem vindo da sessão) e `spectrum` (níveis 0..1).
- Tudo passa por `clean_*`: textos truncados, números limitados, chaves
  desconhecidas descartadas.
- Unidirecional: o serviço nunca envia comandos para a sessão.

## Ciclo de vida

| Evento | Comportamento |
| --- | --- |
| Login | `/etc/xdg/autostart/big-screen-monitor-media.desktop` inicia o agente; se nenhum display usa o tema, ele sai na hora |
| Tema aplicado na janela | a janela inicia o agente |
| Tema deixa de ser usado | o agente sai depois de 60 s |
| Segunda instância | o nome D-Bus é único; a segunda sai com código 0 |
| Logout | o barramento de sessão fecha → o agente sai; o serviço marca o agente como ausente após 20 s sem heartbeat |
| Serviço reinicia | o publicador reconecta (1, 2, 5, 10 s) e reenvia instantâneo e capas |
| PipeWire/PulseAudio reinicia | `pactl subscribe` termina → relançado com recuo (1…30 s) |
| Player encerra / reinicia | `NameOwnerChanged` remove/adiciona; nova escolha conforme a política |
| Suspensão | a posição é ressincronizada a cada 5 s enquanto toca |

O hub de mídia roda numa thread própria (`media-ipc`), **fora** do watchdog do
pipeline: uma falha de mídia nunca reinicia o serviço; o tema apenas mostra a
tela de espera ("Agente de mídia não está rodando").

## Vários displays

Todos os displays leem o **mesmo** `MediaHub` (uma conexão por agente, nenhuma
conexão D-Bus por display ou por quadro). Cada display escolhe o player com as
suas próprias opções (`bmp_player_mode`, `bmp_player_fixed`,
`bmp_player_ignore` podem ser sobrescritas por display); dois displays
acompanhando a mesma música usam o mesmo instantâneo e ficam sincronizados.

## Janela de configuração

A aba *Big Media Player* embute o mesmo `MediaCore` no loop GLib da GTK para a
prévia (com a música real) e envia os comandos ao agente pela interface D-Bus
quando ele está rodando — janela e display controlam o mesmo player.
