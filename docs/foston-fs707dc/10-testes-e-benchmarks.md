# Testes e medições

## Testes físicos (FOSTON real, 18/11/2026)

Logs brutos: `foston-monitor/bench-2026-11-18-*.jsonl`, `foston-monitor/lab/run1.log`.

| Teste | Resultado |
|---|---|
| Detecção (`main.py --list-displays`) | `usb-5-1.4.1 045e:00ce probable FOSTON FS-707DC Touch Display port=/dev/ttyUSB0` ✅ |
| Troca USB armazenamento → serial pelo cliente | ✅ (`Mass_Storage_Class -> Serial_Class`, COM6) |
| Handshake | ✅ 10–204 ms |
| Barras de cor, gradiente, grade, texto de 10 a 56 px | ✅ exibidos (bancada `fsp_bench.py`) |
| Toque: toque, arraste, cantos | ✅ 21 down / 369 move / 20 up; x 1–789, y 1–478 |
| Runtime completo, 3 min, troca de tema pelo toque (até Big Media Player, passando por Brother Away) | ✅ link saudável; 2 quadros danificados reparados sozinhos |
| Saída do cliente (Sair) devolve armazenamento | ✅ |
| Desconectar/reconectar o cabo com o serviço rodando (3 ciclos) | ✅ cada ciclo: erro de leitura → `disconnected` → aparelho volta **já como serial** → novo HELLO → `healthy` (log `lab/run3-replug.log`) |
| Reparo de quadro com NAK atrasado durante o re-HELLO | ✅ corrigido após ser visto no aparelho (`lab/run2-replug.log`) |
| Reiniciar o PC, suspensão | ⏳ não executado |
| FOSTON + AX206 simultâneos no mesmo runtime | ⏳ não executado (o AX206 estava com o serviço do sistema) |
| KDE Plasma, WindowMaker Wayland | ⏳ não testado (sessão usada: WindowMaker X11; o toque não depende do ambiente gráfico) |

## Medições (cliente 1.1.0, driver com janela de 64 KiB)

| Métrica | Valor medido |
|---|---|
| Quadro completo 800×480 (pior caso) | **7,1–7,3 fps**, mediana 130–144 ms, ~197–201 KiB/s |
| Atualização pequena (região de relógio) | **130–132 fps**, mediana 7,5–7,7 ms, p95 9,4–10,2 ms |
| PING ida e volta | mediana 2,0 ms, máximo 3,2 ms |
| Decodificação no aparelho (quadro completo zlib) | 54–76 ms; blit 12–14 ms |
| Vazão bruta só de escrita (padding) | 1,1 MiB em 3,31 s ≈ 332 KiB/s |
| Repasse de toque no PC (leitura → callback) | < 0,05 ms |
| Estresse 30 s quadros completos | 208 quadros, nenhum erro na sessão |
| Perdas no link sob carga (runtime 3 min) | 2 quadros reparados automaticamente |
| RAM livre no aparelho com cliente | ~97–100 MB de 118 MB |
| Tamanho do cliente | 32 KB |

Não medidos: latência ponta a ponta toque → quadro na tela (exige câmera),
consumo de energia, CPU do aparelho.

### Evolução (medida)

| Versão | Problema observado | Correção |
|---|---|---|
| 1.0.0 | mensagens > ~1 KB perdidas; respostas 200 ms | — |
| 1.0.1 | não abre | `_vsnwprintf` ausente no coredll |
| 1.0.3 | diagnóstico invisível | `DT_END_ELLIPSIS` não suportado |
| 1.1.0 | quadros completos estáveis, 5→7 fps após corrigir a leitura do PC (`read(1)` + `in_waiting`) | thread leitora, anel 2 MiB, créditos, ressincronização |

## Testes automatizados

`python -m pytest tests/test_foston.py` — 37 testes (emulador + núcleo C real):
protocolo e CRC, ressincronização, as 4 codificações, entrada hostil no C,
handshake, cliente antigo recusado, janela de créditos, reparo de quadro,
desconexão, gestos, rotação inversa nas 4 orientações (contra transposições reais
do PIL), barra/menu/teste, persistência e prioridade da janela, runtime ponta a
ponta com toque, isolamento de outro painel durante a falha do FOSTON, instalador.
Suíte completa: 1363 testes passando.

**Testes simulados não substituem a validação física**; as linhas ⏳ acima
continuam pendentes.
