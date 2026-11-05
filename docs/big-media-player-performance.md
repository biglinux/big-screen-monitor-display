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
