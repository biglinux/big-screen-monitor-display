# 03 — Monitor de saúde, watchdog e recuperação

## Arquitetura

```
telemetry thread ──► SYSTEM_STATS ──► render thread ──► FrameMailbox ──► transport thread ──► driver
      │                                    │            (1 slot,               │
      └──────── Heartbeat ─────────────────┴──────────── latest-wins) ────────┘
                                   │
                         supervisor (thread principal)
                         ├─ recarrega settings (stat a cada 1 s)
                         ├─ verifica heartbeats e operações em andamento
                         ├─ WATCHDOG=1 somente se tudo progride
                         └─ /run/big-screen-monitor-display/status.json a cada 2 s
```

Só a thread de transporte toca o dispositivo, então nunca há acesso USB/serial
concorrente. Código: `bsmd/runtime.py`, `bsmd/health.py`, `bsmd/sdnotify.py`.

## Regra fundamental: progresso, não pixels

Um tema estático legitimamente não envia nada. Cada subsistema registra
**progresso** (uma iteração concluída, mesmo que o diff diga "nada mudou") e
**operações em andamento** (`begin("present")` … `end()`). O supervisor
detecta:

- operação presa: `present` em andamento há mais de 30 s;
- ausência de progresso: nenhuma iteração há mais de 30 s;
- thread morta.

Nesses casos o supervisor **para de enviar `WATCHDOG=1`** e registra um
incidente crítico; o systemd mata e reinicia o processo após `WatchdogSec=30`.
O supervisor roda na thread principal, separado das threads monitoradas, então
uma thread congelada não consegue "sinalizar saúde" por conta própria.

Em ociosidade (tema estático) o transporte faz uma sonda barata a cada 15 s
(AX206: leitura SCSI das dimensões; Turing: `TIOCMGET` e existência da porta),
para que um dispositivo desaparecido seja notado mesmo sem quadros novos.

**Limitação de hardware:** nenhum dos painéis informa o que exibe. Uma
transferência concluída significa que o dispositivo aceitou os dados (AX206:
CSW com status 0; Turing: bytes escritos), não que a tela esteja fisicamente
acesa. A interface e o diagnóstico deixam isso explícito.

## Máquina de estados do enlace

```
STARTING ─► RECOVERING ─► HEALTHY ◄─► DEGRADED
               │   ▲          │           │
               │   │          └───────────┴──► RECOVERING
               ▼   │
        DISCONNECTED ─► RETRYING ─► FAILED ─► (processo sai com código 3)
```

Transições inválidas levantam `InvalidTransition` (testado). Regras:

| Situação | Ação |
| --- | --- |
| 1 erro transitório (`timeout`, `io`, `protocol`) | `DEGRADED`, invalida o diff; próximo sucesso → `HEALTHY` |
| 2 erros seguidos ou erro fatal (`disconnected`, `not_found`, `permission`, `busy`) | `RECOVERING`: fecha o driver, descarta quadros pendentes |
| Reabertura | redetecta o dispositivo, reaplica brilho, envia quadro completo |
| Dispositivo ausente | `RETRYING` com sonda a cada 2 s, indefinidamente, sem contar como falha |
| Presente mas sem responder | backoff exponencial (1 → 30 s, jitter 20%); na 4ª tentativa, reset USB **somente** do dispositivo validado por VID/PID |
| 8 falhas com dispositivo presente | `FAILED`; no serviço, sai com código 3 para o systemd reiniciar o processo (contexto libusb novo) |
| `permission`/`busy` | nunca escalam para `FAILED` (reiniciar não resolve); tentativas a cada ≥ 10 s com mensagem acionável |

Nenhuma etapa reseta controladores, hubs ou portas inteiras.

## Integração com o systemd

```ini
Type=notify            # READY=1 após iniciar as threads
NotifyAccess=main
WatchdogSec=30         # pings a cada 1 s enquanto tudo progride
Restart=on-failure     # inclui morte por watchdog e saída 3
RestartSec=5
RestartSteps=6         # atraso cresce até…
RestartMaxDelaySec=300 # …5 min: nunca há laço apertado
StartLimitIntervalSec=0
TimeoutStopSec=15
```

`STATUS=` mostra o estado em linguagem simples, por exemplo
`healthy: AX206 DPF 800x480, theme brother_away, 8.0 fps`.

Sinais: `SIGTERM` encerra limpo (mostra "Monitoramento parado" no display em
vez de deixar a última imagem congelada); `SIGUSR1` força reconexão e redesenho
(usado por "Recuperar o display agora"); `SIGHUP` recarrega as configurações.

## Histórico de incidentes

Cada incidente tem data/hora, tipo, gravidade, operação, modelo, tentativas,
duração e estratégia. Vai para o journald (com prioridade syslog `<N>`), para
`status.json` (últimos 30) e para `/var/lib/big-screen-monitor-display/incidents.jsonl`
(rotacionado em 500 linhas). Exemplo real:

```
transport: incident kind=transport_disconnected disconnected: AX206 transfer failed ([Errno 19] No such device) operation=present model=AX206 DPF attempts=1 duration_ms=2.4
transport: link state healthy -> recovering (present: disconnected)
transport: incident kind=recovered display communication restored model=AX206 DPF attempts=1 recovery_s=2.05
```

## Diagnóstico acessível

- **Interface → Diagnóstico → "Diagnosticar meu display"**: serviço ativo e
  habilitado, display no USB, permissões do nó, regra udev, helper, unit
  sobrescrita em `/etc`, arquivo de configurações, frescor do relatório,
  estado do enlace, pipeline, erros recentes. Itens com problema oferecem
  correção segura (reiniciar, recuperar, ativar, importar configurações antigas).
- **Exportar diagnóstico**: relatório + `status.json` + últimas 300 linhas do journal.
- **Terminal**: `python3 /usr/share/big-screen-monitor-display/main.py --diagnose`
  ou `--status`.
