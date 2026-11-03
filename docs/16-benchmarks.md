# 16 — Benchmarks do Universal Display Engine

Ferramenta: `python3 main.py --benchmark [--bench-sizes 160x80 480x320 …]
[--bench-themes standard …] [--frames N] [--json]`. Mede nesta máquina o
custo de render de cada tema, conversão de pixels (RGB565, BGRA, PNG/JPEG,
cabeçalho DES) e a fração do quadro que muda entre quadros. Os tempos de
link são **estimativas** a partir da vazão nominal (serial ~1 MB/s; AX206
6,7 MB/s, medido na 4.0; Turing USB 8 MB/s) e não incluem a decodificação no
painel — só hardware real confirma.

Máquina: x86_64, Python 3.14.7, 5 quadros por tema, 2026-11-03.

## Render por tema (mediana, ms)

| Tamanho | Padrão | GKrellM | Planet | Comp. Antigo | Brother Away |
| --- | --- | --- | --- | --- | --- |
| 160×80 (layout compacto) | 2,7 | 0,3 | 8,8 | 6,2 | 1,7 |
| 480×320 | 6,2 | 2,1 | 9,5 | 9,9 | 3,1 |
| 480×480 | 5,8 | 3,8 | 10,2 | 10,1 | 2,3 |
| 800×480 | 6,8 | 6,4 | 13,8 | 6,6 | 2,8 |
| 1024×600 | 7,6 | 6,7 | 19,8 | 7,2 | 3,1 |
| 1280×720 | 9,0 | 6,8 | 27,8 | 7,5 | 3,7 |
| 1920×480 | 7,9 | 7,0 | 14,9 | 7,3 | 3,7 |

O primeiro quadro do tema Padrão custa ~60 ms (carregamento do logotipo da
distribuição); depois fica em cache.

## Codificação (ms) e tamanho do quadro inteiro

| Tamanho | RGB565 | BGRA | PNG/JPEG | bytes RGB565 | bytes PNG |
| --- | --- | --- | --- | --- | --- |
| 160×80 | 0,04 | 0,09 | 0,45 | 25 600 | 8 911 |
| 480×320 | 0,34 | 0,92 | 2,6 | 307 200 | 24 680 |
| 800×480 | 0,64 | 2,1 | 4,9 | 768 000 | 33 000 |
| 1280×720 | 2,5 | 5,4 | 10,8 | 1 843 200 | 53 395 |
| 1920×480 | 2,5 | 5,7 | 11,1 | 1 843 200 | 43 049 |

Cabeçalho DES do Turing USB: 0,03 ms com `python-cryptography`; ~10 ms com o
DES em Python puro (fallback).

## Quadro inteiro estimado por link

| Tamanho | Serial RGB565 (rev. A, WeAct, Kipye) | Serial BGRA (rev. C) | AX206 | Turing USB (PNG)* |
| --- | --- | --- | --- | --- |
| 160×80 | 26 ms | 51 ms | 4 ms | 1 ms |
| 480×320 | 307 ms | 614 ms | 46 ms | 3 ms |
| 800×480 | 768 ms | 1,5 s | 115 ms (medido) | 4 ms |
| 1920×480 | 1,8 s | 3,7 s | — | 5 ms |

\* sem o tempo de decodificação do painel, desconhecido sem hardware.

## Consequências aplicadas

- As atualizações parciais são o que viabiliza painéis seriais: com os
  temas estáticos mudando 0–2% do quadro por segundo, um 480×320 serial
  envia alguns KB por quadro em vez de 300 KB.
- O perfil automático limita o teto por família: rev. C 4 fps (cada parcial
  espera status), Turing USB 6 fps, XuanFang 6 fps (pausa de 50 ms por
  bitmap); além disso mantém o pipeline abaixo de ~60% de ocupação medindo
  render + transferência reais.
- O perfil "Fluido" continua disponível para quem quer animação mais suave
  em links rápidos.

## Medição em hardware real (AX206 800×480, versão 4.1 no código-fonte)

| Métrica | Valor |
| --- | --- |
| Estado | healthy, Brother Away |
| FPS entregue | 6,4–8,3 |
| Transferência média | 16 ms |
| CPU do processo | 5,5% de um núcleo |
| RSS | 90 MB (inclui o módulo de descoberta e a cena) |
| Reconexão após desautorizar/reautorizar o USB | ~2 s depois do retorno do dispositivo |
| Padrão de teste via spool | exibido e removido no tempo pedido (10 s) |
