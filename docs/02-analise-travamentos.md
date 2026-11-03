# 02 — Análise dos travamentos

**Sintoma relatado:** o display continua mostrando a última imagem e deixa de
atualizar, enquanto o systemd considera o serviço saudável.

## Causa raiz confirmada (AX206): handle USB obsoleto após re-enumeração

A AX206 desta máquina sofre resets espontâneos. O kernel registra o
dispositivo desconectando e voltando com outro número:

```
nov 02 23:41:10 … 23:41:41  usb 5-1.4.4: USB disconnect, device number 5 … 11   (rajada)
nov 03 00:30:44            usb 5-1.4.4: USB disconnect, device number 12 → 13
nov 03 03:14:43            usb 5-1.4.4: USB disconnect, device number 13 → 16
                           usb 5-1.4.4: device not accepting address 15, error -71
```

Na versão 3.1.0, `AX206_DPF.scsi_wrap()` envolvia cada transferência em
`try/except Exception: return -1`. Depois do reset de 00:30:44, todas as
escritas no handle antigo falhavam com `ENODEV`, o erro era descartado e o
laço continuava "funcionando". O journal mostra o serviço ativo até o
reinício manual às 02:09 — 1h39min de tela congelada.

Os erros `-71` (EPROTO, "device not responding to setup address") indicam
também um problema elétrico (cabo, porta, hub ou alimentação). O software não
corrige isso, mas agora se recupera sozinho (veja abaixo).

**Reprodução:** desautorizar/reautorizar somente o dispositivo validado
(`/sys/bus/usb/devices/5-1.4.4`, VID/PID conferidos) provoca a mesma
desconexão real.

## Causas plausíveis corrigidas preventivamente

| Causa | Situação 3.1.0 | Correção |
| --- | --- | --- |
| Escrita serial sem timeout (Turing) | `rtscts=True` sem `write_timeout`: CTS baixo bloqueia `write()` indefinidamente | `write_timeout=5 s`, escrita em blocos de 32 KiB, erro classificado como `timeout` |
| Comandos externos no laço de render | `docker ps`, `playerctl`, `amixer` sem timeout a cada quadro | `cached_command()`: valor em cache, atualização em thread com timeout de 2 s; o render nunca espera |
| Exceção não tratada no render/transporte | Derrubava o processo (bom) ou era engolida (ruim, AX206) | Erros classificados (`DisplayError`), tratados pela máquina de recuperação; tema com falha cai para *Dark* |
| Dispositivo ausente na partida | `sys.exit(1)` e reinício a cada 5 s | Processo continua, estado `RETRYING`, sonda barata a cada 2 s |
| Thread morta | Invisível | Thread que morre registra incidente crítico e suspende o watchdog |
| Estado do diff após falha | `_prev_frame` atualizado mesmo com envio parcial | Qualquer erro invalida o quadro anterior: o próximo envio é completo |
| Bordas não atualizadas (Turing 5"/8,8") | 32 px à direita nunca comparados | Grade com divisão por teto + preenchimento |
| Corrupção no lado do painel | Nunca reenviava áreas "iguais" | Quadro completo a cada 5 min e após qualquer recuperação |

## Comprovação no hardware real

| Teste | Resultado |
| --- | --- |
| Desconexão injetada (authorized 0→1) | `io` → `DEGRADED` → `RECOVERING` → `RETRYING` → `HEALTHY` em **1,14 s** |
| Reset **espontâneo** às 03:14:43 (sem intervenção) | `disconnected` detectado e display restaurado em **2,05 s** |
| Dispositivo ocupado por outro processo | `busy` classificado, novas tentativas espaçadas, sem travar |
| Processo congelado com SIGSTOP (unit real) | `Watchdog timeout (limit 30s)` → SIGABRT → reinício em 5 s → AX206 reaberta → `healthy` |

Logs completos em `09-testes-validacao.md`.
