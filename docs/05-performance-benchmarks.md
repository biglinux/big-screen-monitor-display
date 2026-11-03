# 05 — Desempenho: medições antes × depois

Máquina: AMD Ryzen 7 5700G (16 threads), Python 3.14, Pillow 12.3, NumPy 2.5.
Display real: AX206 800×480 (USB 2.0). "% CPU" = porcentagem de **um** núcleo,
medida por `psutil.Process.cpu_times()` no processo do serviço (inclui filhos).

## Consumo do serviço no hardware real (mesmo tema Dark, 60 s)

| Versão | CPU próprio | CPU em filhos | Total | RSS |
| --- | --- | --- | --- | --- |
| 3.1.0 (git HEAD, sem patches) | 33,8% | 15,8% (`powerprofilesctl`) | **49,6%** | 60 MB |
| 3.1.0 instalado com patches locais (journal, 26 h) | — | — | 27,6% | 84 MB pico |
| **4.0.0** | — | — | **3,2–3,5%** (17 min) | 58 MB |
| **4.0.0, Brother Away animado (8 fps, unit endurecida)** | — | — | **5,1%** | 72 MB |

## Onde estava o custo

| Etapa | 3.1.0 | 4.0.0 |
| --- | --- | --- |
| RGB565 AX206 800×480 | 110 ms (laço Python) | ~2 ms (NumPy, conversão + diff) |
| Transferência AX206 | quadro completo sempre (768 KB, 115 ms) | só retângulos alterados; canto de 128×48 em ~4 ms |
| Coleta por ciclo | 131 ms a cada 0,4 s (`powerprofilesctl` 89 ms + processos 36 ms + sensores 6 ms) | 2,9 ms a cada 1 s (sensor da CPU lido direto; processos a cada 5 s e só se o tema mostra processos; perfil de energia lido de arquivo) |
| Fontes TrueType | recarregadas a cada quadro | cache LRU |
| Comandos externos (GKrellM) | síncronos, a cada quadro | cache assíncrono, TTL 5–10 s |

## Pipeline e ritmo

- **Separação coleta × render × transporte** em threads; a coleta lenta nunca atrasa animação.
- **Backpressure + coalescência**: caixa de correio de 1 posição; o render não
  produz mais de um quadro à frente do transporte, e um quadro não consumido é
  substituído pelo mais novo (`frames_dropped` no status).
- **Cadências distintas**: temas de dados renderizam alinhados a cada 0,5 s
  (o relógio nunca atrasa); no Brother Away o personagem anima a 8 desenhos/s,
  as ondas e a cintilação das estrelas a 1 Hz, as folhas a 4 Hz, nuvens só se
  movem por pixels inteiros, o céu é recalculado por minuto.
- **Tempo monotônico** para deadlines, backoff e animação; o relógio de parede
  só para exibir a hora e o ciclo dia/noite.
- **Quadro completo periódico** (5 min) para curar corrupção do lado do painel.

## Dirty rectangles

`bsmd/frames.py`: grade de tiles com divisão por teto (bordas de resoluções
não múltiplas incluídas), fusão horizontal de tiles vizinhos e vertical de
corridas idênticas; acima do limite de retângulos, uma caixa envolvente; acima
de 60% da área, quadro completo. AX206: tiles 32×16, até 24 retângulos
(~0,3 ms de overhead SCSI cada). Turing: tiles 48×20, até 48 retângulos,
envio embaralhado preservado.

Efeito medido no Brother Away 800×480 (60 quadros a 8 fps):

| Momento | Quadros completos | Área alterada (mediana) |
| --- | --- | --- |
| Antes de quantizar estrelas/folhas (noite) | ~94% | — |
| Depois (noite) | 12% (1 por segundo, passo das ondas) | 3,3% |
| Depois (dia) | 2% | 1,5% |

No hardware: USB caiu de ~5,6 MB/s para **0,9 MB/s**, transferência média de
114 ms para 13–18 ms.

## FPS adaptativo

| Perfil | Teto (temas animados) |
| --- | --- |
| Econômico | 4 fps |
| Equilibrado | 8 fps |
| Fluido | 15 fps |
| **Automático (padrão)** | 8 fps, reduzido para manter o pipeline ≤ 60% ocupado (`0,6 / (render + transferência)`), e 4 fps na bateria |

O automático foi observado adaptando-se no hardware: com quadros completos de
114 ms ele limitou a 5,1 fps; com o diff otimizado subiu ao teto. As poses
são desenhadas "em dois" (8/s), por isso o teto automático é 8: renderizar a
12 fps só duplicava poses e elevava a CPU de 5,1% para 8,1% (medido).

## Custo de render (sem transporte)

| Tema | 320×240 | 480×320 | 800×480 |
| --- | --- | --- | --- |
| Padrão (processos) | 10,5 ms | 10,7 ms | 14,9 ms |
| Padrão (gráficos) | 7,8 ms | 8,1 ms | 12,7 ms |
| GKrellM | 5,2 ms | 3,7 ms | 13,6 ms |
| Planet | 18,5 ms | 15,9 ms | 25,2 ms |
| Planet com cor de destaque | 27,1 ms | 24,0 ms | 43,6 ms |
| Computador Antigo | 14,1 ms | 14,3 ms | 11,0 ms |
| Brother Away (cena + HUD + upscale) | — | 2,6 ms | 3,0 ms |

Medido com o sistema a ~95% de CPU por outros processos (buscas do KDE); em
repouso os valores caem pela metade. No Padrão, metade do tempo é desenho de
texto (cerca de 48 textos por quadro).

Os temas de dados são renderizados ~2×/s: mesmo o pior caso (Planet com
destaque, 44 ms) representa ~9% de um núcleo durante o render, e o diff só
envia o que mudou.

## Memória

Caches limitados: fontes (LRU 96), ícones/logos (com cache negativo), céu (1
entrada), lua (por fase arredondada), incidentes (100 em memória, 500 linhas em
disco), histórico de diálogos (12), atores/flutuantes do Brother Away
(verificado < 60/< 30 num dia simulado). RSS observado estável em 72,5 MB
durante o teste prolongado (veja 09).
