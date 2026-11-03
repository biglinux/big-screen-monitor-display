# 09 — Testes e validação

## Suíte automatizada

`python3 -m pytest -q tests` → **191 testes, todos passando** (~20 s). Não
exigem hardware nem GTK. CI: `.github/workflows/tests.yml` (pytest + `msgfmt -c`).

| Arquivo | Testes | Cobre |
| --- | --- | --- |
| `test_settings.py` | 7 | padrões, validação, valores legados, arquivo corrompido, gravação atômica, migração (mais recente vence, nunca sobrescreve), detecção de mudança |
| `test_frames.py` | 9 | RGB565 idêntico ao laço 3.x, little/big-endian, cores conhecidas, **bordas não múltiplas**, fusão de retângulos, caixa envolvente, caixa de correio (coalescência e backpressure), rotação |
| `test_drivers.py` | 18 | AX206 e Turing com USB/serial falsos: resolução, ausente, blit completo→parcial, **desconexão relatada (não engolida)**, timeout, E/S, CSW inválido, ocupado, brilho, `write_timeout`/`exclusive`, codificação idêntica ao 3.x, regressão do conflito de nomes `present()` |
| `test_health.py` | 6 | transições válidas/inválidas, backoff com teto, operação presa vs. ausência de progresso, **imagem estática não é travamento**, histórico limitado em disco |
| `test_runtime.py` | 10 | pipeline completo com painel simulado: entrega de quadros, **recuperação de desconexão no meio da transferência**, timeout transitório sem reabrir, desconectar/reconectar, ausente na partida, **transferência travada suspende o watchdog e retoma**, falha persistente sai com código 3, mudanças ao vivo sem reconectar, tema quebrado cai para Dark, `status.json` |
| `test_helper.py` | 11 | só verbos fixos, JSON validado, entrada grande, somente esta unit, SIGUSR1 |
| `test_brother_away.py` | 32 | 5 resoluções/orientações, escala inteira, **cada uma das 14 histórias até o fim passando pelas 4 fases**, interrupção restaura o mundo, baixa repetição, **um dia simulado** sem erros e com memória limitada, modo estático, persistência atômica e tolerante a lixo, prévia não grava, histerese das reações, humor/bordões, overlay sem dados, posições do overlay |
| `test_sound.py` | 4 | WAVs válidos, mapeamento de eventos, eventos limitados, autostart |
| `test_themes.py` | 93 | Padrão, GKrellM, Planet e Computador Antigo em 7 resoluções (incluindo 240×320 e 1024×600), os 8 esquemas, todas as combinações de painel lateral/valores/barras, tudo desligado, `fit()` nunca excede a largura, ids antigos, colunas do GKrellM, ausência de dados inventados, cores de destaque preservando a Terra, paletas e cartões do Computador Antigo, regressão da recoloração de ícones |

## Simulação de falhas (painel simulado)

`SimulatedDisplay` injeta: ausente, desconectado, falha ao abrir N vezes,
timeout, E/S, protocolo, travamento por N segundos e reconexão. Os cenários do
item 20.2 do pedido estão cobertos em `test_runtime.py`/`test_drivers.py`,
exceto "dados corrompidos" (coberto como CSW inválido na AX206) e "erro de
permissão" (classificação coberta; o fluxo é idêntico ao de `busy`).

## Hardware real (AX206 800×480)

| Teste | Resultado |
| --- | --- |
| Abertura e resolução | 800×480 informado pelo próprio dispositivo, 70 ms |
| Quadro completo / parcial | 115 ms / ~4 ms (CSW status 0) |
| Desconexão injetada (`authorized` 0→1 só em 5-1.4.4) | recuperado em 1,14 s |
| Reset espontâneo (03:14:43, `error -71`) | recuperado em 2,05 s sem intervenção |
| Dispositivo ocupado por outro processo | `busy`, novas tentativas, sem travamento |
| Unit endurecida real (`DynamicUser`, `DevicePolicy=closed`, filtro de syscalls) | `Type=notify` → READY, `STATUS=` atualizado, `status.json` 0644 |
| SIGSTOP no processo | `Watchdog timeout (limit 30s)` → SIGABRT → reinício em 5 s → `healthy` |
| Consumo 60 s, tema Dark | 3,2–3,5% CPU (original: 49,6%) |
| Consumo Brother Away 8 fps | 5,1% CPU com o sistema ocioso; 8,6% com o sistema a ~90% de CPU por outros processos e a reação de calor ativa |

A unit de teste usou o mesmo arquivo do pacote, mudando apenas o caminho do
código (cópia em `/run`) e o grupo suplementar (o grupo do sysusers não existe
antes da instalação; o nó já tinha a regra antiga `0666`).

## Testes prolongados

| Execução | Duração | Recuperações | CPU | RSS |
| --- | --- | --- | --- | --- |
| Dark, processo de usuário | 17 min | 0 necessárias | 3,1–3,5% | 57,5 → 58,6 MB (estabilizou) |
| Brother Away, unit endurecida | 03:13 → 03:28 (15 min) | 1 (reset espontâneo real, recuperado) | 5,2–9,4% | 72,5 MB constante |
| Brother Away, versão final | 03:30 → 03:37 | 0 (3098 quadros, 0 descartados) | 8,6–8,8%* | 72,6 MB constante |

\* Durante a última execução o sistema estava a ~90% de CPU por processos de
busca do KDE; o mesmo render, medido isolado, levou 6,6 ms contra 3,0 ms com o
sistema ocioso — a diferença é contenção, não regressão.

Simulação acelerada: um dia completo do Brother Away (2880 passos) sem
exceções e com atores/flutuantes/históricos limitados.

**Não executados:** testes de 24, 48 e 72 h — o ambiente desta sessão não
permitiu. Recomenda-se deixar o serviço rodando e acompanhar
`journalctl -u big-screen-monitor-display` e `main.py --status`
(`recoveries`, `rss_mb`, `cpu_percent`).

## Testes visuais

Capturas geradas pelos próprios renderizadores (`tools/make_screenshots.sh`)
em `docs/images/`: todos os temas legados, Brother Away de manhã, meio-dia,
pôr do sol, noite, retrato, chuva, 800×480 e as cenas principais. Verificados
manualmente: sobreposição HUD × copa do coqueiro (corrigida espelhando o
layout), personagem flutuando no horizonte ao nadar (corrigido), dreads sob a
ilha quando deitado (corrigido), balões dentro da tela e fora do HUD.
Interface: capturas de todas as páginas em inglês e português.

## Pendências de validação

- **Turing Smart Screen:** sem hardware nesta máquina; validado apenas com
  serial falso (timeouts, bordas, codificação idêntica ao 3.x). Precisa de teste
  real de temporização e estabilidade.
- **Confirmação visual na AX206:** as transferências foram aceitas pelo
  dispositivo, mas não houve inspeção humana da tela durante a sessão.
- **Instalação do pacote no sistema:** o pacote foi construído e inspecionado
  (`makepkg`, `namcap`), mas não instalado nesta máquina (Polkit/sysusers/udev
  reais dependem da instalação).
- **Leitor de tela (Orca):** rótulos acessíveis definidos; navegação com Orca
  não foi testada.
