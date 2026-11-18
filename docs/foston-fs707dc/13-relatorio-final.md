# FOSTON FS-707DC Touch Display — relatório final

**Data:** 18/11/2026 · **Branch:** `feat/foston-fs707dc`

## Resultado

Um navegador GPS FOSTON FS-707DC (Windows CE 5.0, MediaTek MT3351, 800×480,
toque resistivo) mostra os temas do Big Screen Monitor Display em tempo real e
**responde ao toque**, com o firmware original intacto.

| Nível | Critério | Situação |
|---|---|---|
| 1 | Hardware identificado e comunicação comprovada | ✅ |
| 2 | Exibição funcional de dados reais | ✅ painel Padrão com telemetria real |
| 3 | Temas e integração ao Big Screen Monitor | ✅ detecção automática, runtime, temas (Padrão … Big Media Player, Brother Away), GUI |
| 4 | Touchscreen funcional e calibrado | ✅ toque, arraste, troca de tema pelo painel; calibração nativa do WinCE |
| 5 | Integração completa, recuperação automática, testes reais aprovados | 🟡 quase: reparo de quadro e **3 ciclos de desconectar/reconectar o cabo validados no aparelho**; reiniciar o PC, suspensão e outros ambientes gráficos **não testados** |

Classe no registro: **A** (vídeo, toque e reconexão comprovados no aparelho).

## O que foi construído

| Parte | Onde |
|---|---|
| Cliente Windows CE `bsmd-ce` 1.1.1 (C, 32 KB) | `device-clients/wince/` (fonte), binário em `usr/share/big-screen-monitor-display/device-clients/wince/` |
| Protocolo FSP (C + Python) | `device-clients/wince/src/fsp.[ch]`, `bsmd/displays/foston/protocol.py` |
| Driver `foston_fs707dc` | `bsmd/displays/foston/driver.py` (+ `emulator.py`, `install.py`) |
| Camada de toque genérica | `bsmd/touch.py`; integração em `bsmd/runtime.py` |
| GUI (Meus Displays) | `displays_page.py`: toque, teste, calibração, instalador do cliente |
| Regra udev restrita | `usr/lib/udev/rules.d/70-big-screen-monitor-display.rules` |
| Testes | `tests/test_foston.py` (37) |
| Laboratório | `foston-monitor/` (backup, toolchain, bancadas, logs) |

## Decisões principais

1. **Alternativa A** (cliente no firmware original) em vez de AV-IN, troca de
   controladora ou firmware novo: único caminho com vídeo **e** toque sem risco
   ao aparelho ([04](04-alternativas-e-arquitetura.md)).
2. **Troca de função USB pelo cliente** (`IOCTL_UFN_CHANGE_CURRENT_CLIENT`), revertida ao sair.
3. **Thread leitora + créditos + reparo por re-HELLO**, porque o driver serial do
   aparelho perde dados (medido) — [06](06-protocolo-fsp.md).
4. **Toque tratado dentro do serviço**, nunca injetado no desktop
   ([07](07-touchscreen-e-interface.md)).

## Números medidos no aparelho

Quadro completo 7,1–7,3 fps · atualização pequena ~130 fps (7,5 ms) · PING 2 ms ·
toque cobrindo 1–789 × 1–478 · runtime de 3 min com 2 reparos automáticos e
nenhuma queda ([10](10-testes-e-benchmarks.md)).

## Pendências

* Testes físicos: reiniciar o PC, suspensão,
  FOSTON + AX206 no mesmo runtime, KDE Plasma e WindowMaker Wayland.
* Subir a prioridade da thread leitora do cliente para reduzir os reparos sob carga.
* Controle do Big Media Player pelo toque (exige decisão sobre comandos
  serviço → sessão).
* Imagem bruta do volume (`sudo dd`) para o arquivo de backup.
* Traduções das novas strings (`locale/*.po`).
