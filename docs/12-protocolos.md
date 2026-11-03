# 12 — Protocolos

Resumo técnico dos protocolos implementados em `bsmd/displays/`. As famílias
Turing/XuanFang/Kipye/WeAct/Turing USB seguem o projeto de referência
[turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python)
(Copyright © 2021 Matthieu Houdebine, GPL-3.0-or-later), reimplementadas
sobre o contrato de drivers deste projeto. O repositório de referência não
foi modificado; os testes comparam os bytes gerados com hashes dos arquivos
de referência (`tests/data/reference_protocol_hashes.json`).

Todas as famílias seriais usam 115200 baud nominal, RTS/CTS, porta aberta em
modo exclusivo, `write_timeout` de 5 s e escrita em blocos de 32 KB
(`bsmd/displays/transport.py`). Erros são classificados (timeout,
desconectado, permissão, ocupado, E/S, protocolo) para a máquina de
recuperação.

## AX206 (dpf-ax) — `ax206.py`

SCSI encapsulado em bulk (CBW `USBC` / CSW `USBS`). Comandos: tamanho do
display, backlight (0–7) e *blit* de retângulo em RGB565 big-endian. Aceita
sub-retângulos: só as áreas alteradas são enviadas (tiles 32×16, até 24
retângulos, quadro inteiro acima de 60% da área). Escalação de recuperação:
reset USB **apenas** deste dispositivo (VID/PID e barramento/endereço
conferidos) após 4 falhas de abertura.

## Turing rev. A — `turing_serial.py`

- Comando de 6 bytes: coordenadas compactadas em bits (`x>>2`, …) e o código
  no último byte. Brilho invertido (`255 - nível`).
- HELLO = seis bytes `0x45`; UsbPCMonitor responde 6 bytes (`01…`, `02…`,
  `03…` → 3,5", 5", 7"); o Turing 3,5" original não responde.
- Orientação: pacote de 16 bytes (`orientação + 100`, largura, altura).
- Bitmap: comando 197 + RGB565 LE em blocos de `largura × 8` bytes.

## XuanFang rev. B — `xuanfang.py`

- Quadros de 10 bytes: `cmd + 8 bytes + cmd`.
- HELLO `"HELLO"` deve voltar ecoado com `0x0A` + sub-revisão; resposta
  inválida é erro de protocolo (o driver não tenta outra família).
- Sub-revisões: A01/A02 (brilho liga/desliga), A11/A12 (flagship: brilho
  0–255 e LEDs RGB traseiros — comando de iluminação só nesses).
- Bitmap RGB565 big-endian; orientações reversas feitas em software; pausa
  de 50 ms após cada bitmap (o painel não confirma).

## Turing rev. C — `turing_serial.py`

- Mensagens preenchidas até múltiplos de 250 bytes.
- HELLO responde `chs_<n>inch…rom…`; o tamanho e a versão de ROM vêm daí.
- Imagem completa em BGRA com `0x00` a cada 249 bytes; atualização parcial
  com cabeçalho `UPDATE_BITMAP` (BGR quando ROM ≤ 88) e leitura de status
  (`QUERY_STATUS`, 1024 bytes) a cada atualização — por isso o limite de 4
  retângulos e o teto automático de 4 fps.
- Dormindo: abrir a porta acorda o painel (nada é escrito); ele re-enumera
  como gadget Linux (`0525:a4a7` ou `1d6b:0121/0106`, serial `20080411`).
- Diferença conhecida em relação à versão atual da referência: o tamanho no
  comando `DISPLAY_BITMAP` e a flag de *flip* do comando de opções mudaram
  entre versões; os testes comparam os *payloads* de imagem, que são idênticos.

## Kipye rev. D — `kipye.py`

Pacotes `0x50` + 63 bytes, sem handshake (identificação só por VID/PID).
`SETORG`/`SET180` para orientação, brilho em degraus de 5 (enviado duas
vezes, como a referência). Paisagem por rotação em software.

## WeAct Studio FS V1 — `weact.py`

- Comandos curtos terminados em `0x0A`: `0x02` orientação, `0x03` brilho
  (nível + tempo de transição LE), `0x04` preenchimento, `0x05` bitmap
  (coordenadas LE16), `0x06` relatório de umidade/temperatura,
  `0x42|0x80` versão.
- RGB565 LE em blocos de `largura × 4`.
- 3,5" (A) envia relatórios `0x86 temp(u16) umid(s16) 0x0A`; o parser varre
  quadros completos (um byte `0x86` dentro de um valor não é confundido com
  início de quadro). O 0,96" (B) não tem sensores.

## Turing USB — `turing_usb.py`

- Interface 0, endpoints bulk OUT/IN. Só o driver do kernel da interface 0
  deste dispositivo é desconectado (normalmente não há nenhum).
- Cabeçalho de 500 bytes: comando, magic `0x1A 0x6D`, milissegundos desde a
  meia-noite local (LE); cifrado em DES-CBC (chave = IV = `slv3tuzx`),
  completado até 512 bytes com `[510]=161, [511]=26`.
- Imagem PNG (comando 102) ou JPEG (101) até 1 MB; o painel recebe quadros
  em retrato (rotação `ROTATE_270` no driver). Brilho: comando 14, escala
  0–102. Sincronismo: comando 10. Resposta OK = byte `0xC8`.
- DES é implementado em Python puro (`des.py`, verificado com vetores
  padrão); `python-cryptography`, se instalado, é usado como acelerador.
- Não implementado de propósito: reprodução de vídeo, armazenamento,
  reinício remoto.

## Simulador — `simulated.py`

Painel em memória com injeção de falhas (`faults`), latência e vazão
configuráveis e forma (`rect`/`round`). Usado nos testes e por
`main.py --simulate`.
