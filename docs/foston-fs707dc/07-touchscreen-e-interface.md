# Touchscreen e interface 800 × 480

## Caminho do toque

```
digitalizador resistivo → driver de toque do WinCE (já calibrado)
  → WM_LBUTTONDOWN/MOVE/UP na janela do bsmd-ce
  → FSP TOUCH (USB serial)
  → FostonDisplay.on_input (thread de leitura)
  → native_to_render (inverso exato da rotação do quadro)
  → touch.TouchUI (gestos → ações) → quadro seguinte com a sobreposição
```

* **Nada é injetado no sistema** (sem uinput, XTest ou libinput): o foco do
  teclado, menus abertos e arrastes do mouse do computador principal nunca são
  afetados — igual em X11 e Wayland, porque o toque nem chega ao compositor.
* Toque **de um ponto só**: não há multitoque simulado.
* Movimentos são limitados a 1 evento a cada 25 ms no aparelho.

## Gestos e ações

| Gesto | Ação |
|---|---|
| Toque | mostra a barra inferior + cabeçalho (6 s); na barra, aciona o botão |
| Deslizar ← / → | próximo / anterior tema |
| Deslizar ↑ ou segurar 0,7 s | menu: galeria de temas, Teste de toque, Calibrar, Voltar e **Sair para o menu do GPS** |
| Sair para o menu do GPS (2 toques em até 4 s) | fecha o cliente no aparelho, devolve o USB ao modo armazenamento e volta ao menu principal do FOSTON |
| Deslizar ↓ | fecha o que estiver aberto |

Cabeçalho: hora, data, nome do display e indicador de conexão (verde = saudável).
Barra: ◀ tema, nome do tema, tema ▶, brilho −/+ (**só quando o hardware tem
controle de luz de fundo** — o FS-707DC não tem), menu, fechar. Botões de
≥ 64 px de altura; em retrato a barra perde o rótulo e os botões crescem.
Cada toque desenha uma onda que se expande (feedback visual imediato).

As escolhas feitas no painel (tema, brilho) são salvas por display em
`$STATE_DIRECTORY/touch-<id>.json` e **descartadas assim que o mesmo ajuste é
mudado na janela de configuração** — a janela sempre prevalece.

## Calibração

O WinCE já entrega coordenadas calibradas (verificado: toques nos cantos deram
x 1–789, y 1–478). "Calibrar" (no menu do painel ou na janela) abre a
calibração nativa do aparelho (`TouchCalibrate`), cujo resultado o próprio WinCE
guarda. Orientação/inversão de eixos vêm da opção "Orientação" do display.

## Configuração (Meus Displays)

No grupo **Hardware** do FOSTON: interruptor *Touchscreen*, *Teste de toque*,
*Calibrar toque*, *Fechar o cliente no navegador* e *Instalar o cliente no navegador* (copia `bsmd-ce.exe` para
`BigScreen\` do volume montado e confere o SHA-256).

## Ainda não feito

* Controle do Big Media Player pelo toque: o canal de mídia é unidirecional por
  projeto (agente da sessão → serviço; ver `bsmd/media/ipc.py`). Abrir comandos
  no sentido inverso exige decisão de segurança própria.
