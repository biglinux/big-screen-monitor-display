# SmartMonitor 3,5" HID: travamento depois de um reset de USB

Painel `0483:0065` (llhmi.com / llTechCo, serial `2022100600`), firmware de 2022,
medido numa ASRock A520M-HVS (controlador USB do chipset AMD A520) em 20/11/2026.

## Sintoma

Depois de reiniciar o PC, o painel continuava listado no USB (`lsusb`, `hidraw`),
mas toda escrita no `hidraw` terminava em `ETIMEDOUT` depois de 5 s. O serviço
desistia a cada ~2 min (`recovery_failed`, código de saída 3) e o systemd o
reiniciava sem fim: 39 reinícios numa manhã, por ~17 h, até alguém desconectar o cabo.

## Causa (medida no aparelho)

| Teste | Resultado |
| --- | --- |
| Painel funcionando → `USBDEVFS_RESET` | trava (escritas com timeout) |
| Painel funcionando → desconfigurar → reset → configurar | trava |
| Painel funcionando → desautorizar → autorizar (sem reset) | continua funcionando |
| Painel recém-reiniciado e **não configurado** → reset → configurar | **continua funcionando** |
| Painel travado → reset, desligar a porta (`disable`), suspender/retomar (runtime PM), `SET_REPORT` pelo canal de controle (saída ou *feature*) | continua travado |
| Painel travado → tirar a energia (desconectar o cabo) | volta |

Depois que o host configura o painel, **qualquer reset do barramento** o deixa sem
aceitar dados no endpoint OUT até perder a energia. O canal de controle (EP0)
continua respondendo, mas o firmware ignora o que chega por ele. A BIOS reseta o
USB em todo reinício a quente, e a placa mantém energia nas portas USB mesmo com
o PC desligado. Por isso o painel travava a cada reinício. No boot a frio ele
funciona porque a BIOS não o configura antes do reset do kernel.

Também medido: o painel só reinicia (some do USB por ~3,5 s) quando uma sessão de
gravação YMODEM é encerrada (bloco 0 vazio), mesmo que nenhum arquivo tenha sido
enviado. O tema gravado é preservado. Não existe comando para carregar um tema
novo sem esse reinício: é assim que o firmware lê o `img.dat`.

## Correção

* **Suspensão — `bsm-usb-guard` + `big-screen-monitor-display-sleep.service`**
  (em `sleep.target`): antes de suspender ou hibernar, o serviço é parado e o
  painel é *estacionado*: `reset` → `ymodem` → `EOT` → bloco 0 vazio. O painel
  reinicia sozinho em ~1 s, e enquanto ele volta o barramento fica com
  `authorized_default=0` (restaurado logo em seguida), então ele fica sem ser
  configurado. Na volta, o reset do kernel encontra um firmware recém-iniciado e
  não configurado; o painel é autorizado de novo e o serviço é iniciado. Sem um
  SmartMonitor conectado, não faz nada.
* **Reinício do PC — sem prevenção possível nesta placa.** O mesmo estacionamento
  feito no desligamento foi testado (o painel ficou não configurado), mas a BIOS
  configura o painel durante o POST e o kernel o reseta em seguida. Deixar o
  painel dentro do modo de gravação também não o protege de um reset. Por isso
  essa etapa não foi mantida.
* **Driver**: ao abrir, um relatório de relógio verifica se o painel aceita dados.
  `ETIMEDOUT` vira o erro `needs_replug`. O serviço não reinicia mais (um processo
  novo não resolve), registra o incidente uma vez, a janela pede para desconectar
  e conectar o cabo, e as novas tentativas não fazem E/S até o painel aparecer com
  outro endereço USB (reconectado) ou passar 1 min.

## Outras correções do mesmo diagnóstico

* **Gravação dupla ao iniciar**: o primeiro quadro era montado antes da primeira
  leitura da telemetria (snapshot vazio: sem GPU, CPU, RAM), e esse tema
  "provisório" era gravado e trocado segundos depois. Isso dava dois reinícios do
  painel a cada partida. Agora o quadro espera a telemetria válida.
* **Edição de temas**: uma imagem nova só é capturada e gravada depois de 4 s sem
  mudanças nas opções (`FLASH_SETTLE`). Antes, editar o Kojiro gravava o painel a
  cada ajuste (~30 gravações e reinícios numa sessão de edição).
* **Ventoinha**: os widgets do Kojiro num display de telemetria não pediam ao
  coletor os dados opcionais (ventoinhas, discos, processos, IP), porque essas
  sessões não têm objeto de tema. Agora pedem, e as ventoinhas viraram valores ao
  vivo do painel (RPM e PWM por ventoinha, `fan_rpm:<id>` / `fan_pct:<id>`). No
  modo automático a ventoinha da CPU/placa-mãe tem prioridade sobre a da GPU.
* **Orientação**: o painel só desenha deitado; a página do display oferece apenas
  as orientações horizontais para ele.

## Validação no aparelho (20/11/2026)

| Cenário | Resultado |
| --- | --- |
| Reinício do PC com o painel estacionado no desligamento | painel travado (BIOS configura no POST) — estacionamento removido |
| Painel travado depois do boot | `needs_replug` registrado uma vez, sem reinícios do serviço; janela pede reconexão |
| Cabo retirado e recolocado | comunicação restabelecida sozinha em ~2 s (`recovered`) |
| Suspensão de 35 s (`deep`) | painel estacionado, resetado na volta, reautorizado e saudável em 0,3 s, sem reconectar |
| Partida do serviço | nenhuma gravação desnecessária (antes: duas, com dois reinícios do painel) |
| Kojiro com ventoinha | `fan_pct`/`fan_rpm` da `nct6793/fan2` ao vivo no painel (confirmado olhando o display) |
