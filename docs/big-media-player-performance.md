# Big Media Player — desempenho

Ambiente: Manjaro/BigCommunity, Python 3.14, PipeWire, x86_64. Números
medidos com as ferramentas do projeto; tempos de link são estimativas de
`--benchmark` (validar em hardware real).

## Renderização (`main.py --benchmark`, 8 quadros, prévia tocando)

| Resolução | standard | gkrellm | kojiro | **big_media_player** | pixels alterados/quadro (BMP) |
| --- | --- | --- | --- | --- | --- |
| 160×80 | 2,69 ms | 0,47 ms | 0,24 ms | **0,39 ms** | 0 % |
| 480×320 | 5,78 ms | 5,0 ms | 0,95 ms | **1,61 ms** | 1 % |
| 800×480 | 7,05 ms | 6,56 ms | 1,91 ms | **2,11 ms** | 1 % |
| 1920×480 | 7,97 ms | 7,0 ms | 2,64 ms | **2,63 ms** | 1 % |

O primeiro quadro (cache vazio: chrome, máscaras de texto, logo) custa 16–76 ms.

## Serviço + agente em execução (20 s, 480×320, link simulado de 1 MB/s)

| Cenário | CPU serviço | CPU agente | Quadros/s | Dados |
| --- | --- | --- | --- | --- |
| Tocando, visualizador decorativo, título curto | 2,9 % | 0,0 % | 8,0 (teto do perfil) | 2,34 MB/20 s (~117 KB/s, inclui quadros completos iniciais) |
| Tocando, visualizador desligado | 1,0 % | 0,1 % | 2,2 | 1,02 MB/20 s (majoritariamente o 1º quadro completo) |

Memória: serviço ~90 MB RSS (igual aos outros temas); agente **41 MB** RSS
(56 MB antes de evitar carregar o pipeline de display e o NumPy no agente).

## Por que é leve

- **Chrome estático em cache** (corpo, molduras, poços de LCD, título, logo);
  cada quadro é uma cópia + camadas pequenas.
- **Máscaras de texto em cache**: o marquee é um recorte e uma colagem.
- **Capas** processadas uma vez por tamanho/forma (LRU), cor dominante e
  fundo desfocado também.
- **Progresso interpolado** com relógio monotônico: o D-Bus não é consultado
  para animar o contador (ressincronização a cada 5 s só para quem toca).
- **Eventos** D-Bus (`PropertiesChanged`, `Seeked`, `NameOwnerChanged`) e de
  áudio (`pactl subscribe`) em vez de polling.
- **Intervalo de quadro adaptativo**: com algo se movendo (rolagem,
  visualizador, vinil, transição) ≤ 10 fps limitado pelo perfil e pelo link
  do painel; parado, um quadro por segundo alinhado ao relógio. `low_power` e o
  perfil Economia desligam animação.
- **Atualização parcial**: os drivers enviam só retângulos alterados
  (~1 % do quadro tocando).
- Nada de D-Bus, rede ou decodificação de imagem na thread de renderização; o
  serviço só recebe pixels RGB já reduzidos.
- Uma mudança significativa (faixa, estado, volume) acorda o render na hora;
  heartbeats não.

## No SmartMonitor 3,5" HID

O painel não recebe imagens: ele mostra uma versão gravada do tema e só recebe
números. Medido num Ryzen 5 5500 (skin Big Wave, espectro real) em 20/11/2026:

| | Antes | Agora |
| --- | --- | --- |
| Adaptar o tema com música e espectro | 41–43 s | 9,8 s (12,8 s com perfil) |
| Atualizações dos valores com música tocando | 1/s | ~5/s (Automático), 10/s (Fluido), 4/s (Equilibrado), 1/s (Econômico) |
| Relatórios por atualização | relógio + todos os valores | todos os valores; relógio 1×/s |

* **Captura**: antes de cada desenho, a captura limpa os caches dos temas (um
  texto vindo do cache não seria visto pelo gravador). Isso também apagava os
  caches de recursos (arquivo e objeto de fonte, ícones SVG rasterizados,
  logos), e cada desenho rodava `fc-match` e `rsvg-convert` de novo: ~2500
  processos, 25 dos 43 s. Esses caches agora são mantidos
  (`capture.KEEP_CACHES`), com imagem e valores idênticos (bytes do `img.dat`
  comparados em Big Media Player, Kojiro, Padrão e GKrellM).
* **Valores ao vivo**: cada relatório leva ~1 ms no painel. Todos os valores vão em toda atualização: enviar só os que mudaram foi testado e deixou o painel com os valores congelados depois de uma gravação. Com uma música
  tocando, tempo, progresso e espectro (que o agente envia 12×/s) vão ao painel
  várias vezes por segundo, conforme o perfil de desempenho.
* **Música nova**: com "capa e título de cada música" ligado, cada música nova é
  gravada no painel de novo (~10 s de captura + ~12 s de gravação, com o painel
  reiniciando). Com o YouTube, que troca de título com frequência, desligar a
  opção deixa o painel sem reinícios: tempo, progresso, volume, play/pausa e
  espectro continuam ao vivo.

### Troca de tema no SmartMonitor

Medido no aparelho (tema de ~390 KB, 384 blocos):

| Etapa | Tempo | Pode diminuir? |
| --- | --- | --- |
| Adaptar o tema | 2–10 s | **Sim, feito**: com 45 s sem mudanças, o serviço adapta os outros temas em segundo plano; na troca o tema já está pronto (0 s) |
| Enviar os blocos (6537 relatórios de 64 bytes) | 6,5 s | Não: o painel é USB full-speed com 1 relatório por milissegundo |
| Confirmação de cada bloco (gravação na memória do painel) | 4,1 s | Não: enviar o bloco seguinte antes da confirmação foi testado e o firmware recusa (e apaga o tema antigo) |
| Reinício do painel para ler o tema | 3,5–5 s | Não: é o firmware |

Do clique até o painel voltar com o tema novo: **17–18 s** (antes, 19–28 s, ou ~60 s no Big Media Player). Uma placa de vídeo não ajuda: a adaptação é desenho 2D (Pillow) e o resto é limitado pelo USB e pelo firmware do painel.

Uma troca isolada começa na hora. Mudanças seguidas (editar um tema) esperam 4 s sem mudanças antes de gravar.

Durante a gravação, o painel some do USB por ~4 s. No KDE Plasma, isso gera o aviso e o som de "Dispositivo conectado/desconectado". O Plasma só avisa sobre dispositivos que o kernel marca como removíveis, e um painel ligado num hub USB aparece como `unknown`, então não gera aviso. Também é possível desligar esses dois eventos em *Configurações do sistema → Notificações → Notificações do sistema* (`~/.config/plasma_workspace.notifyrc`, `Action=` em `Event/deviceAdded` e `Event/deviceRemoved`).

### Quais valores ficam ao vivo

O painel aceita no máximo 28 números e 26 canais. Quando um tema mostra mais que isso, a captura escolhe nesta ordem:

1. Valores que ainda não aparecem em nenhum lugar da tela, por prioridade (relógio, CPU, RAM, GPU, disco, rede…).
2. Repetições de valores já ao vivo em outro ponto, as mais baratas primeiro: três números de um widget cada valem mais que um segundo relógio de cinco.
3. Casas decimais de valores grandes (≥ 100), se sobrar espaço: "200M" em vez de "200.0M". Valores pequenos mantêm as suas ("0.3 Mb/s" nunca vira "0 Mb/s").

No tema Planet isso trouxe CPU Freq, GPU Clock, Disk e Net de volta. Também foram corrigidos: o clock, a potência e o encoder da GPU ativa, que eram tratados como "não ao vivo"; e o Planet, que lia a frequência da CPU por fora da telemetria.
