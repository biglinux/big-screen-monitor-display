# 08 — Relatório final (DeepCool Digital)

## Entregue

* Saída de **telemetria** no contrato de drivers, ao lado da saída raster,
  reaproveitando máquina de estados, recuperação, watchdog e isolamento
  multi-display do runtime.
* Drivers para **AK, AG, LS, AK PRO, AK400 PRO, LD** (hidraw) e
  **MYSTIQUE 240/360** (USB vendor, modo de informações + rotação).
* Detecção segura por VID/PID, identidade conferida por ioctl antes do
  primeiro byte, trava exclusiva por `flock`, nenhuma sondagem às cegas.
* Telemetria de CPU completa: temperatura com sensor preferencial e idade,
  uso, **potência** (RAPL/zenergy/amd_energy, sem 0 W falso) e frequência
  (núcleo mais rápido ou média).
* Seis presets nativos + "Seguir o tema" com adaptador de temas e matriz de
  compatibilidade.
* Interface AshyWall: cartões, página de detalhe com prévia fiel ao layout
  (DEMO sem hardware), grupos CPU, Exibição, Alertas, Desempenho,
  Diagnóstico e Avançado; painel inicial; dispositivos não suportados
  listados sem envio de dados.
* Permissões restritas (udev por VID/PID, grupo do serviço, sandbox systemd
  só com `char-hidraw`), RAPL legível só pelo grupo do serviço.
* 44 testes novos de unidade/integração + 1 cenário GTK; suíte completa com
  1289 testes passando; tradução pt completa.

## Decisões de segurança

| Exigência | Como foi atendida |
| --- | --- |
| Sem `MODE="0666"` | Regras `0660` + grupo + `uaccess`; teste impede regressão |
| Sem liberar todo `hidraw` | Regra só para `3633` e os PIDs suportados |
| Sem comandos desconhecidos/destrutivos | Só os pacotes documentados de cada família; nada para PIDs não suportados |
| Firmware intocado | Nenhum comando de firmware, alarmes internos preservados e mostrados como informação |
| Sem upload repetido no MYSTIQUE | Upload não implementado; somente modo de informações |
| Sem permissões globais de energia | `energy_uj` 0440 só para o grupo do serviço |
| Não parar serviços de terceiros | Conflitos apenas listados, com sugestão de comando |
| Nunca 0 W por falha | Valor ausente + motivo; layouts fixos registram o 0 obrigatório como ausente |
| Sem alterar o repositório principal | Desenvolvimento na branch `feat/deepcool-digital` do checkout local |

## Limitações conhecidas

* **Nenhuma validação física** (classe B). Ver a lista de testes pendentes em
  [07-testes](07-testes.md).
* AK PRO, AK400 PRO e LD não têm valor em branco: um campo sem dado mostra 0
  no cooler (sinalizado na interface e no status).
* A potência depende do RAPL/zenergy: sem esses contadores (algumas VMs, CPUs
  antigas), os campos de potência ficam indisponíveis.
* MYSTIQUE: sem imagens, GIFs ou temas próprios — por segurança do
  dispositivo.
* CH (gabinetes), LP, LQ, ASSASSIN IV VC VISION, MORPHEUS e linha G2 NYX são
  apenas identificados.

## Próximos passos sugeridos

1. Executar os testes físicos de [07-testes](07-testes.md) com usuários que
   tenham cada família e promover para a classe A.
2. Avaliar os protocolos CH/LP/LQ a partir de capturas reais antes de
   qualquer implementação.
3. Para o MYSTIQUE, só considerar imagens se houver captura do software
   oficial provando um modo de transferência volátil (sem gravação
   persistente).
