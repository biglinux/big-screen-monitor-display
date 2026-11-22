# 03 — BSDP v1 (Big Screen Display Protocol)

Fontes da verdade: `bsmd/displays/android/protocol.py` e `android/.../Bsdp.kt`.
`tests/data/bsdp-vectors.json` (gerado pelos testes Python, conferido pelo JUnit no CI) mantém os
dois iguais byte a byte.

## Enquadramento

`"BS"` · u8 versão (1) · u8 tipo · u32 tamanho do payload (big endian) · payload.
Fluxos confiáveis (TCP, USB bulk): cabeçalho inválido encerra a conexão (sem ressincronização).
Limites: 64 KiB por mensagem vinda do app, 8 MiB vinda do PC, JSON ≤ 64 KiB, tipos aceitos por sentido.

## Mensagens

| Tipo | Sentido | Payload |
|---|---|---|
| `0x01 HELLO` | app→PC | JSON: proto, device_id, name, model, manufacturer, android, sdk, app_version, screen{w,h}, view{w,h}, density, formats[], touch, brightness, transport, nonce |
| `0x02 AUTH` | app→PC | JSON: proof = HMAC(token, "bsmd-auth-v1", nonce_pc, nonce_app, device_id) |
| `0x03 PAIR` | app→PC | JSON: `{"method":"ticket","ticket","proof"}` (HMAC com o segredo do QR) ou `{"method":"confirm"}` |
| `0x04 VIEW` | app→PC | JSON {w,h}: a área mudou (rotação, janela) |
| `0x05 PRESENTED` | app→PC | u32 quadro, u16 ms de decodificação, u16 fila |
| `0x06 TOUCH` | app→PC | u8 tipo (1 down, 2 move, 3 up, 4 cancel), u8 ponteiro, u16 x, u16 y, u16 0, u32 ms — em coordenadas do quadro |
| `0x07 COMMAND` | app→PC | JSON `cmd` ∈ {menu, theme_next, theme_prev, close_overlay, set, media}; `set` só com chaves da lista `DEVICE_SETTABLE` |
| `0x08 STATS` | app→PC | JSON: fps, decode_ms, uptime_s… |
| `0x09/0x0A PING/PONG` | ambos | u32 token |
| `0x0B BYE` | ambos | JSON {reason} |
| `0x41 CHALLENGE` | PC→app | JSON: server_id, name, nonce, need ("auth"/"pair"), pairing, fp |
| `0x42 PAIR_WAIT` | PC→app | JSON: code (6 dígitos), timeout |
| `0x43 WELCOME` | PC→app | JSON: display_id, server_id, name; token e fp só ao parear |
| `0x44 REJECT` | PC→app | JSON: reason (version, unknown_device, auth_failed, denied, expired, busy, rate_limited, revoked, disabled, replaced) |
| `0x45 CONFIG` | PC→app | JSON: orientation (landscape/portrait/reverse_*/auto), keep_screen_on, burn_in, touch, touch_media, theme, quality, profile, resolution, canvas |
| `0x50 RECT` | PC→app | u16 x,y,w,h, u16 largura/altura do quadro, u8 formato (0 fill RGB, 1 RGB+zlib, 2 JPEG, 3 PNG, 4 WebP), u8 0, dados |
| `0x51 PRESENT` | PC→app | u32 quadro, u16 largura, u16 altura |
| `0x52 BRIGHTNESS` | PC→app | u8 % (o app aplica só na própria janela) |

## Sessão

1. `HELLO` → `CHALLENGE` (aparelho conhecido: `need=auth`).
2. `AUTH`, ou `PAIR` (ticket do QR, ou confirmação: `PAIR_WAIT` com o código; o app confere o
   código calculado com o certificado que **ele** viu e aborta se não bater).
3. `WELCOME` (token só no pareamento) ou `REJECT`.
4. `CONFIG`, depois `RECT…` + `PRESENT` por quadro; o app compõe num buffer e só mostra no `PRESENT`.
5. PING a cada 5 s de silêncio (app) e 15 s sem quadro (PC); 20 s sem nada → reconexão.

Mensagens desconhecidas de versões novas são ignoradas pelo app; versão de protocolo diferente → `REJECT version`.
