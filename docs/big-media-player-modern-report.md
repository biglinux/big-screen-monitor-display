# Big Media Player 4.4 — Modern Collection: desempenho, testes e relatório final

## Desempenho medido

Máquina: AMD Ryzen 7 5700G, Python 3.14.7, Pillow 12.3, NumPy 2.5. Música
tocando com título longo (marquee ativo), capa real de 300×300, visualizador
decorativo, telemetria visível, configurações padrão. 60 quadros por skin
após o primeiro, avançando o relógio pelo intervalo que o próprio tema pede.
"Pixels alterados" é a fração da tela que muda entre quadros consecutivos — é o
que o transporte por retângulos sujos envia aos displays seriais.

**480×320, animações automáticas (10 q/s enquanto algo se move)**

| Skin | ms/quadro (mediana · p95) | pixels alterados/quadro | 1º quadro (cromo + caches) |
| --- | --- | --- | --- |
| Bigamp · Bigmatch · Bigative · Bigalplayer | 1,6 · 2,6 · 1,8 · 1,9 | 0,9–1,4 % | 43–63 ms |
| Big Media Player · BigXMMS2 · BIGX | 1,3 · 1,3 · 1,6 | 1,2–1,3 % | 4–44 ms |
| **Big Vinyl** (disco girando) | 1,7 · 2,7 | 0,8 % | 84 ms |
| **Big Pure** | 1,1 · 1,7 | 1,1 % | 48 ms |
| **Big Ember** | 1,4 · 2,6 | 1,1 % | 70 ms |
| **Big Groove** | 1,6 · 2,5 | 1,2 % | 79 ms |
| **Big Lounge** | 1,4 · 2,1 | 0,5 % | 58 ms |
| **Big Wave** (waveform) | 1,1 · 1,7 | 1,3 % | 72 ms |
| **Big Flow** | 1,1 · 1,4 | 1,1 % | 59 ms |
| **Big Stage** | 1,1 · 1,6 | 1,1 % | 45 ms |

Em 800×480 as modernas ficam em 1,7–2,6 ms (clássicas 1,5–3,3 ms); em 320×480
com animações *Econômicas* (4 q/s), 0,9–1,6 ms. Memória máxima do processo de
medição, com as 15 skins renderizadas: 84 MB (480×320) e 107 MB (800×480).

Conclusão: o visual moderno custa o mesmo que o retrô por quadro. O custo extra
fica no primeiro quadro de cada skin/tamanho (cromo, sombras e texturas), que vai
para cache.

### Como o custo fica baixo

- **Cromo estático em cache** (fundo, cartão, sombras do cartão, texturas,
  fundo ambiente da capa): reconstruído só ao mudar tamanho, skin, paleta,
  estilo ou — no Lounge — a capa.
- **Máscaras anti-aliased supersampled em LRU** (`modern/base.py`, 160 entradas):
  círculos, anéis, cápsulas, sombras, degradês, ícones, rótulo do disco por passo
  de ângulo. Por quadro só há colagens.
- Cores da capa: uma vez por capa (16 em cache); paletas resolvidas: 16; formas
  do waveform: 8 faixas.
- Nenhuma conexão MPRIS, nenhum download, nenhuma decodificação de imagem na
  renderização: tudo continua vindo do snapshot do agente.
- O giro do disco usa passos de 12° (equilibrado) ou 6° (fluido) e só altera a
  área do rótulo; a taxa nunca passa do alvo do display.

Um teste (`test_caches_stay_bounded`) passa 40 capas × 8 skins × 40 tamanhos e
confere que nenhum cache cresce além do limite.

## Testes

`tests/test_bigmedia_modern.py` — 329 casos novos; suíte completa: **1229
passando** (eram 820 na 4.3.0; os testes parametrizados por `SKIN_IDS` em
`test_bigmedia.py` passaram a cobrir as 15 skins automaticamente).

| Área | O que é verificado |
| --- | --- |
| Registro | 7 + 8 = 15, listas de `skins` e `settings` iguais, coleções, nomes únicos; as 8 modernas têm composições diferentes (não são variações de cor) |
| Estados | tocando, pausado, parado, sem player, sem agente, sem capa, título/álbum enormes, cirílico/japonês/árabe/grego, stream sem duração, player somente leitura, mudo, volume 150 %, aleatório/repetir, navegador sem artista/álbum |
| Tamanhos | 480×320, 320×480, 320×240, 800×480, 480×800, 160×80, 80×160, 1920×480, 480×480, 1280×400 |
| Geometria | dentro da tela, sem sobreposição (8 skins × 10 tamanhos × 5 variantes × 3 posições de telemetria), fonte ≥ 10 px, progresso sempre presente, capa sem deformação, logo sem cobrir texto |
| Telemetria | oculta/sempre/topo/overlay, GPU sem sensores, coletor sem dados |
| Personalização | 31 combinações de opções em paisagem e retrato; 4 tons do Pure; telas de espera |
| Paletas | contraste 7 : 1 / 4,5 : 1 em 5 modos × 4 capas × 8 skins; capa analisada uma vez |
| Paridade funcional | capacidades, tempos restantes, aleatório/repetir e saída iguais em todas; nada inventado (saída desconhecida não aparece; toggles só quando informados) |
| Animação | níveis → intervalo de quadro; disco parado na pausa; `auto` mantém a 4.3 |
| Overlays | volume ampliado aparece após mudança e não por padrão nas clássicas |
| Desempenho | < 250 ms/quadro em CI (medido ~1–3 ms) |

**Regressão das clássicas**: além dos testes, as 7 skins clássicas foram
renderizadas com o código da 4.3.0 e com o atual em 65 combinações, com relógio
congelado e dados MPRIS idênticos: **hashes idênticos**. A comparação revelou um
bug já existente na 4.3.0 — *modo vinil* com caixa de capa não quadrada
(`ValueError: images do not match` em 5 combinações, p. ex. Bigx 480×320); foi
corrigido só nesse caminho.

**Não testado**: não houve teste em display USB físico nem com players reais
nesta etapa; a integração MPRIS/volume é a mesma da 4.3 (coberta por
`test_media.py` e `test_media_dbus.py` num barramento D-Bus privado). As capturas
da janela GTK foram feitas pelo próprio app (`--screenshot`).

## Critérios de aceitação

| # | Critério | Situação |
| --- | --- | --- |
| 1–4 | Player funcionando, 7 clássicas preservadas, 8 modernas, 15 integradas | ✅ (pixel a pixel nas clássicas) |
| 5 | Galeria com miniaturas | ✅ filtro Todas/Clássicas/Modernas, miniaturas ao vivo |
| 6 | Aparência original e distinta | ✅ teste de composições distintas |
| 7–11 | Capa, metadados, progresso, tempos, capacidades | ✅ mesmo `Frame` das clássicas |
| 12 | Volume real | ✅ `volume.py` inalterado; chip/ícone com a saída real |
| 13 | Logo da distribuição | ✅ canto, aba do Groove, linha de origem do Flow |
| 14 | Telemetria configurável | ✅ 8 modos × 3 posições, estilo por skin |
| 15–16 | Personalização GTK4 e persistência | ✅ grupo *Coleção Moderna*, esquema validado |
| 17 | Resoluções | ✅ 10 tamanhos testados |
| 18 | Animações desativáveis | ✅ `bmp_animations=off` |
| 19 | Desempenho medido | ✅ tabela acima |
| 20 | Regressão | ✅ 1229 testes |
| 21 | Capturas do renderizador real | ✅ `tools/make_screenshots.sh`, `tools/make_bmp_gallery.py` |
| 22 | Documentação | ✅ este arquivo, `big-media-player-modern*.md`, README |

## Limitações e próximos passos

- Textos novos estão em inglês no código; as traduções saem no pipeline de
  tradução do CI, como nas versões anteriores.
- Fontes: Lato/Noto Sans/Roboto/Montserrat são usadas se instaladas
  (fontconfig); sem elas, a sans-serif padrão do sistema assume.
- Displays redondos usam o layout do tamanho correspondente; não há uma
  composição circular dedicada.
- "Favoritas" na galeria não foi implementado (opcional no pedido).
