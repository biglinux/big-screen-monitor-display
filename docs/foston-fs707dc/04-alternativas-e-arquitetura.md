# Alternativas avaliadas e arquitetura escolhida

## Alternativas

| Alternativa | Avaliação | Situação |
|---|---|---|
| **A — cliente próprio no firmware original** | WinCE 5 executa `.exe` ARM escolhido no menu; função USB serial bidirecional disponível; toque já calibrado pelo sistema | **Escolhida e validada no aparelho** |
| B — entrada AV-IN (vídeo composto) | só vídeo (sem retorno de toque), 480i analógico, exige conversor HDMI→CVBS; o AV-IN não foi testado nesta unidade | Não necessária; seria modo "somente display" |
| C — trocar a controladora do LCD | exige desmontar, identificar painel/flat, comprar placa HDMI→RGB e controlador de toque USB | Desnecessária: a solução A já entrega vídeo + toque |
| D — firmware/Linux embarcado | MT3351 sem suporte Linux mantido; risco alto de inutilizar o aparelho | Descartada |

## Arquitetura

```
 Big Screen Monitor Display (Linux)                       FOSTON FS-707DC (WinCE 5.0)
 ┌──────────────────────────────────┐                    ┌──────────────────────────────┐
 │ temas → render 800x480           │                    │ bsmd-ce.exe (C, 32 KB)       │
 │ touch.TouchUI (barra, menu, teste)│                    │  thread leitora → anel 2 MiB │
 │ FostonDisplay (RasterDriver)     │  USB serial        │  parser FSP + CRC            │
 │   retângulos sujos → FILL/zlib/raw├──045e:00ce────────►│  inflate → DIB RGB565 → BitBlt│
 │   janela de créditos 64 KiB      │  /dev/ttyUSB0 ↔ COM6│  PRESENTED / CREDIT          │
 │   reparo automático (re-HELLO)   │◄───────────────────┤  WM_LBUTTON* → TOUCH         │
 └──────────────────────────────────┘                    └──────────────────────────────┘
```

* **Dispositivo** (`bsmd/displays/foston/driver.py`), **transporte**
  (`SerialTransport`), **protocolo** (`foston/protocol.py`), **renderização**
  (temas existentes, sem segunda implementação) e **toque** (`bsmd/touch.py`,
  genérico para qualquer driver com `capabilities.touch`) ficam separados.
* O cliente (`device-clients/wince/`) é genérico para WinCE: lê a resolução e
  a porta do próprio aparelho; nada nele é exclusivo do FS-707DC.

## Por que créditos e leitura dedicada

Medido no aparelho com o cliente 1.0.x (leitura bloqueante de 250 ms):

| Mensagem | Resultado |
|---|---|
| 450 B, 850 B | chegaram |
| 2 KB … 64 KB (com ou sem pausas e fatias) | perdidas |

O driver Serial_Class deste firmware descarta o que não cabe no buffer interno
enquanto o aplicativo não lê. A versão 1.1.0 lê sem bloquear numa thread própria
para um anel de 2 MiB, e o PC nunca deixa mais de 64 KiB sem confirmação
(`FSP_CREDIT`). Perdas residuais (raras, sob carga) são detectadas pelo CRC e
reparadas pelo driver: novo HELLO (zera os contadores dos dois lados) e reenvio
do quadro inteiro, sem derrubar a sessão.
