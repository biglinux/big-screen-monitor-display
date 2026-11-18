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
| Toque | barra inferior + faixa de status (6 s); na barra, aciona o botão |
| Deslizar ← / → | próximo / anterior tema |
| Deslizar ↑, segurar 0,7 s ou botão de grade da barra | menu |
| Deslizar ↓ | fecha o que estiver aberto |

## Menu (aparência Adwaita, como a janela de configuração)

Cabeçalho com o ícone do app (ou botão Voltar nas subpáginas), título, nome do
display, indicador de conexão e relógio; fundo fosco (o próprio tema desfocado).

| Cartão | Página |
|---|---|
| **Temas** | galeria com miniaturas reais dos 7 temas |
| **Aparência do tema atual** | Padrão: 8 esquemas de cores · GKrellM: 3 estilos · Planet: 5 cores de destaque · Computador Antigo: 4 esquemas · Big Media Player: 15 skins · Kojiro: 7 aparências (presets) · Brother Away: 14 histórias (a escolhida começa na hora) — todas com miniatura real, inclusive a cena de cada história |
| **Orientação** | Horizontal, Vertical e as duas invertidas, com desenho da tela |
| **Teste de toque** | desenha o caminho do dedo; segurar sai |
| **Calibrar** | calibração nativa do aparelho |
| **Sair para o menu do GPS** | dois toques em até 4 s: fecha o cliente, devolve o USB ao modo armazenamento e volta ao menu principal |

Miniaturas: renderizadas numa thread separada a meia resolução, guardadas por 10 min.
Ícones: Adwaita simbólicos via `rsvg-convert`, tingidos; há desenho vetorial de reserva.

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
