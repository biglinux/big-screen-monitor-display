# 03 — Protocolos

Todos os pacotes são produzidos por funções puras em
`bsmd/displays/deepcool/protocols.py` e verificados byte a byte em
`tests/test_deepcool.py`. Fabricante USB: `0x3633`.

## Tabela de PIDs

| PID | Modelos | Família aqui | Estado nos projetos de referência |
| --- | --- | --- | --- |
| 0001 | AK400 DIGITAL (SE) | `deepcool_ak` | suportado |
| 0002 | AK620 DIGITAL (SE) | `deepcool_ak` | suportado |
| 0003 | AK500 DIGITAL | `deepcool_ak` | suportado |
| 0004 | AK500S DIGITAL (SE) | `deepcool_ak` | suportado |
| 0006 | LS520 SE / LS720 SE DIGITAL | `deepcool_ls` | suportado |
| 0008 | AG300/400/500/620 DIGITAL | `deepcool_ag` | suportado |
| 0009 | MYSTIQUE 240/360 | `deepcool_mystique` | confirmado em hardware (modo informações) |
| 000A | LD240 / LD360 | `deepcool_ld` | suportado |
| 0010 | AK400 DIGITAL PRO | `deepcool_ak400_pro` | suportado |
| 0011 / 0012 | AK500 / AK620 DIGITAL PRO | `deepcool_ak_pro` | suportado |
| 0005, 0007, 000C, 000D, 000F, 0013, 0015, 0016, 001B, 001F, 0029–002C | CH*, MORPHEUS, LP, LQ, ASSASSIN IV VC, AK* G2 NYX | — | identificados; **nada é enviado** |

## AK / LS / AG — relatório HID 16 (64 bytes)

| Byte | AK / LS | AG |
| --- | --- | --- |
| 0 | report id `16` | report id `16` |
| 1 | modo: `19` °C, `35` °F, `76` segundo campo (uso no AK, potência no LS) | modo (`19` ou `76`) |
| 2 | barra de uso 1–10 (nunca 0) | — |
| 3–5 | três dígitos BCD | 3–4: dois dígitos (máx. 99) |
| 6 | alarme (0/1) | 5: alarme |

* Inicialização (AK, LS): `[16, 170, 0…]` — animação da barra.
* Variantes SE (produto "A400", "A620"…): mesmos bytes **sem** o report id.

Exemplo — AK620, 54 °C, 23 % de uso, sem alarme:
`10 13 02 00 05 04 00 …`

## AK PRO / AK400 PRO / LD — protocolo estruturado

```
[16] + cabeçalho(7) + potência u16 BE + unidade(0 °C / 1 °F) + temperatura f32 BE
     + uso u8 + [frequência u16 BE, só AK PRO] + checksum + 22
```

| Família | Cabeçalho |
| --- | --- |
| AK500/AK620 PRO | `104 1 4 13 1 2 8` |
| AK400 PRO | `104 1 2 11 1 2 5` |
| LD240/LD360 | `104 1 1 11 1 2 5` |

Checksum = soma dos bytes 1…fim dos dados, módulo 256; terminador `22`.

Exemplo verificado no teste — AK PRO, 65 W, 54 °C, 30 %, 4500 MHz:
`16 104 1 4 13 1 2 8 0 65 0 66 92 0 0 30 17 148 39 22`.

Inicialização do LD (dois pacotes): `16 104 1 1 2 3 1 112 22` e o segundo
com o formato de zeros à esquerda (`…2 2 1 111 22` com zeros,
`…2 2 0 110 22` sem).

Esses modelos **não têm valor "em branco"**: um campo indisponível é
enviado como 0, e isso é registrado em `status.metrics.missing` e mostrado
na interface ("Enviado como 0 porque o cooler não tem valor em branco").

## MYSTIQUE 240/360 — USB vendor bulk

* Interface de classe `0xFF` com endpoints `0x01/0x81` (init) e
  `0x02/0x82` (dados).
* Moldura de 48 bytes: `AA 2E <cmd> <payload até 39 bytes> … "HIDC" <checksum LE>`;
  checksum = soma de 16 bits dos bytes 0–45. Respostas começam com `55 2E`.
* Init (13 passos, 10 ms entre eles): `0x12`, `0x02`, `0x03`, `0x04`,
  `0x07`, `0x08`, `0x05`, `0x0B`, `0x06`, `0x15`, `0x16`, `0x17` e
  `0x0A EA 07 02 02 02 27 21 00` (Machine Info).
* Rotação: comando `0x02` com `0x00/01/02/03` para 0/90/180/270°.
* Atualização: `0x10` (status) seguido de `0x01` com temperatura e uso da
  CPU, uso da RAM, temperatura da GPU e clock (GHz inteiro, centésimos e duas
  cópias u16 LE).

O checksum foi conferido contra uma captura real publicada pelo projeto de
referência (`55 2E … 48 49 44 43 9B 01` → `0x019B`).

### O que não é implementado, de propósito

Os comandos de imagem (`0x0F`, `0x14`, molduras "DCLd") gravam na memória
permanente do cooler. O relato em hardware real é que, depois deles, o
MYSTIQUE não volta ao modo de informações. Como não há prova de que o
hardware aceite transferência contínua, **não existe código de upload**, e um
teste garante que nenhum desses comandos aparece no módulo.

## Abertura segura do hidraw

1. `open(O_RDWR | O_NONBLOCK | O_CLOEXEC)`;
2. `ioctl(HIDIOCGRAWINFO)` → `(bustype, vendor, product)`; se não for
   `3633:<PID esperado>`, fecha e falha como `NOT_FOUND`;
3. `flock(LOCK_EX | LOCK_NB)`; se outro programa já tem o nó, `BUSY`;
4. escritas com `select` em `EAGAIN` e verificação de escrita curta.

Erros mapeados para o runtime: `ENOENT`→`NOT_FOUND`, `EACCES/EPERM`→
`PERMISSION`, `EBUSY`→`BUSY`, `ENODEV/ESHUTDOWN/EPIPE`→`DISCONNECTED`, demais →
`IO`.
