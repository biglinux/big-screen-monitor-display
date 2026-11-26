# FSP — Foston Screen Protocol v1

Fonte da verdade: `device-clients/wince/src/fsp.h` (C) e
`usr/share/big-screen-monitor-display/bsmd/displays/foston/protocol.py` (Python).
`tests/test_foston.py` compila o núcleo C com o compilador do PC e o alimenta com
fluxos gerados pelo Python (comparação byte a byte do framebuffer).

## Cabeçalho (16 bytes, little endian)

| Offset | Tipo | Campo |
|---|---|---|
| 0 | 2×u8 | `F` `S` |
| 2 | u8 | versão (1) |
| 3 | u8 | tipo |
| 4 | u16 | sequência |
| 6 | u16 | flags (0) |
| 8 | u32 | tamanho do payload (≤ 1 MiB) |
| 12 | u16 | CRC-16/CCITT-FALSE do payload |
| 14 | u16 | CRC-16/CCITT-FALSE dos bytes 0–13 |

O CRC do cabeçalho permite ressincronizar após lixo procurando o próximo `FS` válido.

## Mensagens

| Tipo | Sentido | Payload |
|---|---|---|
| `0x01 HELLO` | PC→ | u16 versão, u16 flags, nome do host UTF-8 |
| `0x02 PING` | PC→ | u32 token |
| `0x10 RECT` | PC→ | u16 x,y,w,h; u8 codificação; u8 0; u16 0; u16 0; dados |
| `0x11 FILL` | PC→ | u16 x,y,w,h; u16 cor RGB565 |
| `0x12 PRESENT` | PC→ | u32 id do quadro |
| `0x20 BRIGHTNESS` | PC→ | u8 % (só se HELLO_ACK indicar suporte) |
| `0x21 CALIBRATE` | PC→ | — (abre `TouchCalibrate()` do WinCE) |
| `0x22 BYE` | ambos | u8: 0 aguardar, 1 encerrar o cliente |
| `0x23 TOUCHCFG` | PC→ | u8 ativo, u8 intervalo de movimento (ms) |
| `0x81 HELLO_ACK` | →PC | u16 versão, u16 largura, u16 altura, u16 bpp, u32×3 versão do WinCE, u32 RAM total/livre (KB), u8 brilho, u8 nível, u8 toque, u8 flags (bit0 USB trocado, bit1 créditos); strings NUL: cliente, plataforma, OEM, porta, cliente USB anterior |
| `0x82 PRESENTED` | →PC | u32 id, u32 ms de decodificação, u32 ms de blit |
| `0x83 PONG` | →PC | u32 token, u32 tick |
| `0x84 NAK` | →PC | u16 sequência, u8 motivo (1 crc, 2 grande, 3 retângulo, 4 decodificação, 5 desconhecido, 6 ressincronização) |
| `0x85 CREDIT` | →PC | u32 bytes de mensagens inteiras tratadas desde o HELLO |
| `0x90 TOUCH` | →PC | u8 tipo (1 down, 2 move, 3 up), u8 0, u16 x, u16 y, u16 0, u32 tick |
| `0x91 KEY` | →PC | u16 tecla virtual, u8 pressionada |
| `0xA0 LOG` | →PC | texto UTF-8 |

Codificações de `RECT`: 0 bruto RGB565 LE; 1 RLE (`u16 n`: bit 15 = repetição de
`(n & 0x7fff)+1` pixels, senão `n+1` literais); 2 zlib (RFC 1950) do bruto.
O PC escolhe: área uniforme → `FILL`; zlib nível 1 se economizar ≥ 10 %; senão bruto.
Retângulos são fatiados em mensagens de até 16 KiB brutos.

## Fluxo

1. PC: `HELLO` → aparelho: `HELLO_ACK` (o PC recusa clientes sem créditos).
2. Por quadro: `FILL`/`RECT`… + `PRESENT`; o aparelho exibe e responde `PRESENTED`.
   Só um quadro em trânsito; o runtime descarta quadros obsoletos (mailbox de 1 posição).
3. O aparelho envia `CREDIT` a cada 8 KiB tratados e em cada `PRESENT`; o PC
   mantém no máximo 64 KiB sem crédito.
4. `TOUCH` chega a qualquer momento, numa thread de leitura separada.
5. `PING` a cada 15 s de inatividade (probe do runtime).
