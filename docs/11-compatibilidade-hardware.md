# 11 — Compatibilidade de hardware

Matriz dos displays USB conhecidos pelo Universal Display Engine (4.1).
Os identificadores e regras de detecção vivem em
`bsmd/displays/registry.py`; esta tabela é gerada a partir dele à mão e um
teste garante que toda família registrada tem driver.

## Classes de validação

| Classe | Significado |
| --- | --- |
| **A** | Validado em hardware real neste projeto. |
| **B** | Driver implementado e verificado byte a byte contra o projeto de referência ou mocks; teste físico pendente. |
| **C** | Protocolo conhecido/documentado; implementação planejada, ainda não presente. |
| **D** | Em investigação (protocolo parcial ou não publicado). |
| **E** | Não suportado (exige firmware proprietário ou software fechado). |

> Um teste com mock **nunca** promove uma família para a classe A. Só o
> AX206 foi testado fisicamente nesta versão (é o único display disponível
> no ambiente de desenvolvimento).

## Famílias suportadas

| Família | Modelos | Resolução | Transporte | Identificação | Classe |
| --- | --- | --- | --- | --- | --- |
| AX206 (dpf-ax) | Porta-retratos AX206, "USB-Display", AIDA64 3,5"/5"/7" | informada pelo dispositivo (320×240 … 800×480) | libusb (SCSI sobre bulk) | `1908:0102` — confirmado | **A** |
| Turing rev. A | Turing 3,5", UsbPCMonitor 3,5"/5"/7" | 320×480, 480×800, 600×1024 | serial CDC-ACM, RGB565 LE | `1a86:5722` + serial `USB35INCHIPSV2` — confirmado; sem esse serial — provável | B |
| XuanFang rev. B | XuanFang 3,5" (A01/A02), flagship com LEDs (A11/A12) | 320×480 | serial, RGB565 BE | `1a86:5722` + serial `2017-2-25` — confirmado; sem serial — ambíguo | B |
| Turing rev. C | Turing 2,1", 2,8", 5", 8,8" (serial) | 480×480, 480×800, 480×1920 | serial, BGRA (+ BGR parcial) | serial `CT21INCH`/`CT88INCH`/`USB7INCH` (dormindo) — confirmado; `1a86:ca21` — provável; `0525:a4a7` ou `1d6b:0121/0106` **com** serial `20080411` — provável | B |
| Kipye rev. D | Kipye Qiye Smart Display 3,5" | 320×480 | serial, RGB565 BE | `454d:4e41` — provável (o protocolo não tem handshake) | B |
| WeAct A | WeAct Studio Display FS V1 3,5" (+ sensor de temperatura/umidade) | 320×480 | serial, RGB565 LE | `1a86:fe0c` + serial `AB…` — confirmado; sem serial — provável | B |
| WeAct B | WeAct Studio Display FS V1 0,96" | 80×160 | serial, RGB565 LE | `1a86:fe0c` + serial `AD…` — confirmado; sem serial — provável | B |
| Turing USB | Turing 2,8" redondo, 4,6", 5,2", 8", 8,8" (USB), 9,2", 12,3" | 480×480, 320×960, 720×1280, 800×1280, 480×1920, 462×1920, 720×1920 | libusb bulk, cabeçalho DES + PNG/JPEG | `1cbe` + PID `0028/0046/0050/0080/0088/0092/0123` — provável | B |
| Simulador | qualquer tamanho, retangular ou redondo | livre | memória | `--simulate 480x320,160x80,480x480:round` | — |

Observações:

- `1a86:5722` é compartilhado por Turing rev. A e XuanFang rev. B. Sem o
  número de série conhecido, o aplicativo usa rev. A (como todas as versões
  anteriores faziam) e mostra a ambiguidade em **Meus Displays**, onde o
  modelo pode ser trocado. Nenhum comando é enviado para "descobrir" a família.
- Turing rev. C dorme até a porta ser aberta, e então re-enumera com outra
  identidade no **mesmo** endereço físico USB. O id do display é a porta
  (`usb-5-1.4.4`), então as configurações sobrevivem à troca.
- `1cbe` é um vendor compartilhado (Texas Instruments/Luminary): só os PIDs
  listados são considerados; nada mais desse vendor é tocado.
- Vídeo, armazenamento interno, upload de firmware e outros recursos
  persistentes dos painéis **não** são implementados.

## Famílias pesquisadas e não implementadas

| Família | Situação encontrada | Classe | Próximo passo |
| --- | --- | --- | --- |
| ACEMAGIC S1 (tela de 1,9" 170×320 do mini PC) | HID vendor-defined `04d9:fd01` (Holtek HT32); protocolo decodificado pela comunidade (referência, issue 677; projeto `AceMagic-S1-LED-TFT-Linux`). A fita de LED usa CH340. | D | Exige acesso a hidraw de uma interface HID — só com regra udev restrita ao VID/PID e sem tocar em teclado/mouse. Implementar quando houver hardware para validar. |
| NXElec BeadaPanel 3/4/5/6/7 | Especificações oficiais publicadas: *Panel-Link USB Media Stream Transport* e *Status-Link USB Panel Control*. | C | Protocolo documentado; implementar a partir da especificação e validar com o fabricante/usuários. |
| Fuldho 3,5" | HID com relatórios vendor-specific; a tela desenha seus próprios temas e recebe só valores. Variantes novas usam serial. Engenharia reversa parcial. | D | Aguardar especificação estável; não se encaixa no modelo de quadro (não aceita imagens). |
| GUITION Smart Screen 3,5" | Controlado por software proprietário; a referência declara impossível suportar. | E | — |
| Waveshare USB-Monitor 2,1"/2,8"/5"/7" | Exige o software "Waveshare PC Monitor" / firmware próprio. | E | — (os modelos HDMI funcionam como monitor comum, fora do escopo) |
| LCD de coolers (Thermalright, Lian Li, NZXT Kraken Z) | Protocolos HID/USB distintos por fabricante; parte coberta pelo `liquidctl`. | D | Fora do escopo desta versão; avaliar integração via liquidctl. |

## Testes de hardware necessários

Ver `docs/17-testes-hardware.md`. Para promover uma família para A é preciso
um relatório de teste físico com o roteiro daquele documento.
