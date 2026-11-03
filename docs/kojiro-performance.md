# Kojiro — desempenho

Máquina: Ryzen 7 5700G, Python 3.14, Pillow; display real AX206 800×480 (USB 2.0).
"% CPU" = porcentagem de **um** núcleo.

## Medições

| Cenário | Resultado |
| --- | --- |
| AX206 real, Cyberpunk, animações ligadas (ventoinha girando, transições) | 8 fps, renderização média 6,3 ms, transferência média 5,6 ms (só retângulos alterados), **7,5% de CPU**, RSS 97 MB |
| AX206 real, Cyberpunk, animações desligadas | 1 quadro/s (relógio), renderização 6,3 ms, **1,5% de CPU** |
| Simulador 800×480, perfil Fluido (15 fps), 4 min / 3.600 quadros | RSS estável 92–94 MB (sem crescimento), 12–15% de CPU, 0 erros |
| Simulador 800×480 + 480×800 (dois displays, Vidro com foto importada) | 8,6 ms médios por quadro em cada sessão, telemetria coletada uma vez |
| `--benchmark`, quadros com valores iguais (só composição) | 160×80: 0,2 ms · 480×320: 1,1 ms · 800×480: 1,8 ms · 1280×720: 4,1 ms · 1920×480: 2,5 ms |
| Primeiro quadro (gera papel de parede e preenche caches) | 10 ms (160×80) a 180 ms (1280×720), uma única vez |

Comparação no mesmo benchmark: o tema Padrão leva 5,6–8,8 ms por quadro;
o Kojiro, com papel de parede e efeitos neon, fica abaixo disso nos quadros
estáveis graças às camadas em cache.

## Por que é leve

1. **Base em cache** — papel de parede, ajustes, efeito de fundo, vidro fosco e
   decisão dos painéis de legibilidade são calculados uma vez por tamanho/
   configuração.
2. **Camadas por elemento em cache** (LRU de 192) — um elemento só é
   redesenhado quando o texto visível, o valor arredondado ou a fase da
   animação mudam. A ventoinha usa 60 poses (passos de 6°) reaproveitadas.
3. **Intervalo por elemento** — CPU/GPU/rede 1 s, RAM 2 s, disco/swap 5 s,
   textos estáticos 1 h; configurável.
4. **Taxa adaptativa** — sem animação, o tema acorda só no próximo segundo
   (relógio exato); com animação, segue o perfil de desempenho (8 fps no
   automático, menos na bateria ou em links lentos).
5. **Retângulos alterados** — o driver envia só o que mudou; o papel de
   parede nunca é reenviado inteiro sem necessidade.
6. **Coleta sob demanda** — ventoinhas, discos extras, processos, IPs e
   sensores específicos só são lidos se um elemento visível os usa.
7. **Supersampling só onde importa** — elementos ≤ 220 mil px são desenhados
   em 2× e reduzidos (anéis suaves sem Cairo no serviço); maiores, em 1×.

## Limites de memória

Caches com tamanho fixo: base (1 imagem por display), camadas (192), papéis de
parede processados (4), arte gerada (6), imagens importadas decodificadas (3),
fontes (256 tamanhos), logotipos (16). O teste prolongado confirma memória estável.
