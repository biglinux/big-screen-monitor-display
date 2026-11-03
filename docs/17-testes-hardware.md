# 17 — Testes em hardware real

Só testes físicos promovem uma família para a classe A. Um mock bem-sucedido
prova que os bytes estão certos em relação à referência, não que o painel
mostra a imagem.

## Executado nesta versão

| Família | Hardware | Resultado |
| --- | --- | --- |
| AX206 | porta-retratos AX206 800×480, USB 2.0, porta `usb-5-1.4.4` | **Aprovado**: detecção confirmada, Brother Away a 6–8 fps, padrão de teste via spool, reconexão após desautorização controlada do USB (só deste dispositivo), status por display. |
| Turing rev. A, XuanFang rev. B, Turing rev. C, Kipye rev. D, WeAct A/B, Turing USB | não disponíveis | **Pendente** (classe B): bytes conferidos com a referência (71 testes) e comportamento com transporte simulado. |

## Roteiro para quem tem o painel

Antes: anote modelo, revisão, firmware (se a etiqueta mostrar) e a saída de

```
python3 /usr/share/big-screen-monitor-display/main.py --list-displays --json
```

1. **Detecção** — o painel aparece em *Meus Displays* com o nível de
   confiança esperado (tabela do doc 11). Nenhum comando é enviado antes de
   o serviço iniciá-lo.
2. **Primeiro quadro** — o tema aparece sem cores trocadas (vermelho é
   vermelho: use o padrão "Barras de cores"); a ordem das barras deve ser
   branco, amarelo, ciano, verde, magenta, vermelho, azul, preto.
3. **Geometria** — padrão "Grade de geometria": cantos amarelos visíveis
   nos quatro cantos, diagonais chegando aos cantos, círculo redondo.
4. **Orientações** — as quatro orientações em *Meus Displays*; padrão
   "Orientação": a seta aponta para cima e os números 1–4 seguem os cantos.
5. **Brilho** — 0%, 50% e 100%; em painéis com só liga/desliga, conferir
   que 0% apaga e qualquer outro valor acende.
6. **Atualização parcial** — tema Padrão por 10 min: nenhuma "sujeira" nas
   bordas, relógio sempre certo.
7. **Desconexão** — tirar o cabo com o tema ativo; reconectar após 10 s; o
   display deve voltar em poucos segundos sem reiniciar o serviço
   (`journalctl -u big-screen-monitor-display`).
8. **Rev. C** — conectar dormindo: o painel acorda, re-enumera e passa a
   funcionar; o id em *Meus Displays* não muda.
9. **WeAct 3,5"** — temperatura/umidade aparecem em "Sensores do ambiente".
10. **XuanFang flagship** — LEDs mudam de cor; em A01/A02 a opção não tem
    efeito e não gera erro.
11. **Turing USB** — brilho, quadros PNG e, com um tema animado, JPEG
    quando o PNG passa de 1 MB.
12. **Vários displays** — dois painéis com temas diferentes; desconectar um
    não afeta o outro.
13. **Longa duração** — 24 h com Brother Away; anexar o diagnóstico
    exportado.

## Como relatar

Abra uma issue com: saída do passo "Antes", resultado de cada passo
(aprovado / falhou + foto), diagnóstico exportado pela interface e trechos
do journal. Com os 13 passos aprovados (os que se aplicam à família), a
família passa para a classe A em `registry.py` e no doc 11.
