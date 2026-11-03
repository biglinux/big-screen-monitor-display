# 18 — Relatório final: Universal Display Engine (4.1.0)

## Resumo

A 4.1 troca o par fixo AX206/Turing 3,5" por um motor de displays com
famílias de protocolo, detecção universal somente leitura, várias telas
simultâneas e layouts responsivos. Toda a base da 4.0 (watchdog, sandbox,
temas, Brother Away, interface) foi preservada.

| Item | Situação |
| --- | --- |
| Famílias implementadas | 8: AX206, Turing rev. A (+ UsbPCMonitor), XuanFang rev. B (sub-revisões, LEDs no flagship), Turing rev. C (2,1"/2,8"/5"/8,8", com despertar), Kipye rev. D, WeAct 3,5" (+ sensores) e 0,96", Turing USB (2,8" redondo … 12,3") |
| Validadas em hardware real (classe A) | AX206 |
| Verificadas contra a referência (classe B) | as outras 7 — testes byte a byte com hashes dos *goldens* do turing-smart-screen-python |
| Pesquisadas | BeadaPanel (C), ACEMAGIC S1 e Fuldho (D), GUITION e Waveshare USB-Monitor (E), LCD de coolers (D) |
| Testes | 424 (eram 191 na 4.0), sem hardware; lint limpo |
| Repositório de referência | inalterado (`git status` limpo) |

## O que foi feito

- **Drivers por família** (`bsmd/displays/`): contrato único, erros
  classificados, transporte serial com timeouts e porta exclusiva,
  `RasterDriver` com diff em RGB888 e grades por família, DES em Python
  puro para o Turing USB (acelerado por `python-cryptography` se presente).
  `bsmd/drivers.py` virou camada de compatibilidade.
- **Registro e descoberta**: regras por VID/PID/serial com níveis
  confirmado/provável/ambíguo/desconhecido; id estável por porta USB;
  nenhum comando para "descobrir" dispositivos; gadgets e vendors
  compartilhados restritos ao serial/PIDs dos painéis; dispositivos USB
  desautorizados ignorados.
- **Multi-display**: `DisplaySession` por display (threads, máquina de
  estados, backoff, tema, estatísticas, incidentes marcados), telemetria
  compartilhada, hot-plug a cada 2 s, remoção após 45 s ausente, saída para o
  systemd só quando todos falham, watchdog sobre todas as sessões.
- **Configurações por display** (`displays.<id>`): nome, ativo, modelo
  manual, tamanho rev. C, LEDs e qualquer opção não exclusivamente global;
  validação de ids e limite de 16. Orientações invertidas.
- **Comandos por display**: spool validado (identificar, padrões de teste,
  limpar, reconectar), escrito pelo `bsm-helper display-command` via polkit
  para o serviço do sistema; padrões somem sozinhos e o tema volta com
  quadro completo.
- **Layouts**: compacto para telas minúsculas, área segura para telas
  redondas, HUD e balões do Brother Away que cabem em 80 px.
- **Interface**: página **Meus Displays** (detectar de novo, nome, modelo,
  confiança, tema/orientação/brilho/desempenho próprios, firmware,
  capacidades, sensores, padrões, identificar, reconectar, assistente para
  dispositivos seriais desconhecidos); prévia usa o mesmo renderizador
  adaptado ao painel.
- **Ferramentas**: `--list-displays`, `--benchmark`, simulador com vários
  painéis, forma redonda, latência e vazão.
- **Segurança**: udev só para IDs/seriais conhecidos, grupo
  `big-screen-monitor` também nas portas seriais, serviço fora do `uucp`,
  `DeviceAllow` com `char-ttyUSB`, helper sem gravar bytecode como root.
- **Diagnóstico**: detecção pela descoberta universal, estado por display e
  displays aguardando escolha de modelo.
- **Correções encontradas no caminho**: execução manual não encerrava por
  causa da thread do ícone de bandeja; telas quadradas não giravam em
  retrato; reconexão de dispositivo "desconectado" usava backoff
  exponencial em vez da sondagem de 2 s.

## Validação em hardware (AX206 800×480)

| Teste | Resultado |
| --- | --- |
| Detecção | `usb-5-1.4.4`, confirmado |
| Tema animado | 6,4–8,3 fps, 16 ms por transferência, 5,5% de CPU |
| Serviço empacotado (sandbox, sem `uucp`) | healthy, 2,5% de CPU, 65 MB (tema Padrão) |
| Padrão de teste via spool e via `bsm-helper` | exibido e removido no tempo pedido; comando inválido recusado |
| Desautorização/reautorização USB só do display | recuperado ~2 s após o retorno |
| Pacote: atualização 4.0 → 4.1 | ok; serviço parado continua parado (`try-restart`) |
| Pacote: remoção | serviço desativado, unit, udev, helper e app removidos; `/etc/…/settings.json` mantido |
| Pacote: instalação limpa | grupo criado, serviço habilitado e ativo, configurações preservadas |

## Pendências honestas

- Turing rev. A/C, XuanFang, Kipye, WeAct e Turing USB não foram testados
  fisicamente (não há esses painéis no ambiente). Ficam na classe B até
  alguém executar o roteiro do doc 17.
- Rev. C: a versão atual da referência mudou o tamanho em `DISPLAY_BITMAP`
  e a flag de *flip*; adotamos os valores do código de referência
  analisado. Confirmar em hardware.
- Turing USB: tempo de decodificação PNG/JPEG no painel desconhecido; o
  teto automático de 6 fps é conservador.
- BeadaPanel (especificação publicada) é o próximo candidato natural;
  ACEMAGIC S1 exige acesso hidraw com regra udev específica.
- Displays atribuídos manualmente fora da tabela udev precisam de regra
  local de permissão (documentado).
- Em `/usr/share/big-screen-monitor-display/` desta máquina existe um
  `venv/` de fevereiro de 2026 que não pertence ao pacote (sobra de uma
  instalação manual antiga); não foi tocado.
