# 07 — Toque

O app envia o toque de **um dedo** em coordenadas do quadro (já descontando escala, centralização e
deslocamento de burn-in). Quem entende os gestos é a camada de toque do serviço (`bsmd/touch.py`, a
mesma da FOSTON): uma implementação para todos os displays com toque, nada injetado no desktop
(sem uinput/XTest — mouse, teclado e foco do computador nunca são afetados, em X11 e Wayland).

| Gesto | Ação |
|---|---|
| Toque | barra inferior (tema anterior/próximo, brilho, menu, fechar) |
| Deslizar ← / → | próximo / anterior tema (só deste display) |
| Segurar 0,7 s, deslizar ↑ ou botão de grade | menu com páginas (Temas com miniaturas reais, Aparência do tema atual, Orientação, Teste de toque) |
| Deslizar ↓ | fecha o que estiver aberto |
| Dois dedos (app) | menu do próprio app (não vai ao computador) |

* **Calibrar** só aparece em displays que têm calibração (FOSTON); no Android, não.
* **Orientação** no Android ganha "Automático" (seguir o sensor); escolher uma fixa trava o aparelho.
* Configuração do display: "Tela sensível ao toque" desliga gestos (o menu do app continua).
* Prioridade: com uma página aberta, o toque vai aos botões dela antes de qualquer gesto. Nenhum tema
  tem hoje controles próprios dentro do quadro (os do Big Media Player são da própria barra); quando
  um tiver, a prioridade sobre os gestos globais deve ser acrescentada no `TouchUI`.

## Troca de tema pelo celular

Deslizar → `TOUCH` → `TouchUI` → preferência por display (`touch-<id>.json` no estado do serviço)
→ `invalidate` → o render recria o tema → retângulos → o app mostra. Sem reiniciar nada. A janela
mostra o tema efetivo; se a janela mudar a mesma opção, a escolha do toque é descartada (a janela
sempre prevalece). Teste: `test_touch_swipe_changes_only_this_phones_theme`.

## Big Media Player pelo toque

Com o tema Big Media Player, a barra troca para: anterior, reproduzir/pausar, próxima, título e
artista, volume −/+, mudo, menu, fechar — **só os botões que o player e o controle de volume
oferecem** (`can.previous`, `can.next`, `can.pause/play`, `volume.available`).

Caminho: toque → `MediaHub.command` → resposta na mesma conexão do agente da sessão ativa
(`media.sock`) → o agente confere a lista `REMOTE_ACTIONS` de novo e executa o mesmo comando MPRIS
dos botões da janela. Não há reprodutor paralelo. Limite de 10 comandos/s.
Lista fechada: `play_pause, next, previous, volume_up, volume_down, mute` — nada abre, lança ou lê.

## Kojiro

O Kojiro é desenhado inteiro (fundos, widgets, layouts) e suas aparências prontas podem ser trocadas
pelo menu do toque. **Edição de widgets pelo toque não foi implementada**: o editor (Kojiro Design
Studio, GTK) já é a fonte única do modelo; arrastar/redimensionar no celular exigiria levar o editor
inteiro para o protocolo, e uma versão parcial criaria o segundo editor incompatível que o pedido
proíbe. Fica como próximo passo (ver relatório).
