# 11 — Desempenho

## Medições reais (lado do computador)

`tools/android-bench.py`: runtime, hub e TLS reais; o cliente de referência faz o papel do celular
em loopback (decodifica tudo e responde `PRESENTED`). AMD Ryzen 7 5700G (16 threads), Python 3.14. CPU em % de
um núcleo, do processo inteiro (inclui telemetria e o cliente). 22/11/2026.

**Celular 2400×1080, perfil Automático → desenho 1280×576** (padrão), qualidade automática:

| Tema | fps | kB/quadro | kB/s | ms/transferência | CPU % | RSS MB |
|---|---|---|---|---|---|---|
| Padrão | 1,2 | 7,0 | 8 | 9,1 | 4,8 | 99 |
| GKrellM | 2,0 | 8,9 | 18 | 7,7 | 6,0 | 102 |
| Planet | 1,0 | 44,8 | 45 | 8,8 | 6,7 | 130 |
| Computador Antigo | 1,0 | 7,1 | 7 | 7,6 | 4,2 | 132 |
| Brother Away (animado) | 7,5 | 4,4 | 33 | 6,2 | 9,3 | 133 |
| Kojiro | 1,0 | 23,4 | 23 | 8,6 | 3,2 | 151 |
| Big Media Player (sem player) | 1,2 | 0,5 | 0,6 | 6,3 | 2,3 | 158 |

**Perfil Fluido**, tela 1600×720 → desenho 1600×720: Brother Away **13,3 fps**, 82 kB/s, 24,7 % CPU;
temas estáticos 1,5–3 fps (limitados pelo conteúdo, de propósito), 1–76 kB/s.

**Perfil Fluido, 2400×1080 → 1920×864, qualidade Equilibrada**: Brother Away 14,5 fps, 133 kB/s,
33 % CPU; Kojiro com papel de parede passou a usar JPEG em 10 de 93 retângulos; pico de RSS 255 MB.

Leituras:

* O tráfego é de dezenas de kB/s: Wi-Fi de qualquer celular sobra. Retângulos sujos levam a maioria
  dos quadros a poucos kB.
* O custo dominante é **desenhar o tema** em resolução alta, não o transporte (codificação + TLS
  ≈ 6–9 ms por quadro a 1280×576).
* Memória: só renderizar os 7 temas, sem Android, já leva o processo de 39 MB a 143 MB em 1920×864
  (81 MB em 480×320) — caches dos temas crescem com a área (Planet +40 MB, Kojiro +30 MB). Por isso o
  padrão do Android é 1280 px e a unidade systemd passou a `MemoryHigh=256M`/`MemoryMax=384M`.

## Metas

| Meta | Alvo | Situação |
|---|---|---|
| Latência de toque (PC recebe → overlay redesenhado) | < 150 ms | medida no PC: `touch_latency_ms` no status; ⏳ ponta a ponta no aparelho |
| Conexão (abrir app → primeiro quadro, rede local) | < 2 s | ⏳ aparelho; no loopback < 0,5 s |
| Troca de tema | < 1 s | loopback: próximo quadro em ~1 ciclo de render (< 0,3 s); ⏳ aparelho |
| FPS animado | ≥ 8 (Automático), ≥ 13 (Fluido) | ✅ medido no PC (7,5 com 1280 px Automático: limitado pelo perfil de 8 fps) |
| CPU do serviço por celular (estático) | < 10 % de um núcleo | ✅ 2–7 % |
| Tráfego (estático) | < 100 kB/s | ✅ 0,6–45 kB/s |
| Reconexão após queda de rede | < 5 s após a rede voltar | app reconecta ao `onAvailable`; ⏳ aparelho |
| Sessão longa | 24 h sem vazamento | ⏳ não executado |
| Bateria | display na tomada; sem wake lock | ⏳ não medido |

## Otimizações feitas

* Um quadro em trânsito com pipeline (o N+1 é codificado enquanto o celular decodifica o N).
* Retângulos apertados (`TIGHT_RECTS`), preenchimentos como 3 bytes, zlib nível 1, JPEG só onde ganha.
* Tamanho do desenho limitado por perfil e escalonamento no celular com filtragem.
* App: buffers reutilizados, cópia só da área alterada para o buffer exibido, decodificação fora da
  thread de UI, movimentos de toque limitados a 60/s e descartáveis sob fila cheia.
