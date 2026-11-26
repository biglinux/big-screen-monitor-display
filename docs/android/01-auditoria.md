# 01 — Auditoria

Base: `origin/main` (5.3.1, com as bandejas do PR #13) + a branch local `feat/foston-fs707dc`
(cliente Windows CE, protocolo FSP, transporte TCP e **camada de toque** `bsmd/touch.py`), mesclada
em `feat/android-display` (conflitos só em testes, README, PKGBUILD e `pt.po`).

## O que existia e foi reaproveitado

| Peça | Onde | Uso no Android |
|---|---|---|
| Sessões por display (threads de render e transporte, máquina de estados, backoff, watchdog) | `bsmd/runtime.py` | o Android é mais uma `DisplaySession`; isolamento e recuperação são os mesmos |
| Contrato de driver raster com retângulos sujos | `bsmd/displays/base.py` (`RasterDriver`), `bsmd/frames.py` | `AndroidDisplay` herda; só codificação e envio são novos |
| Todos os temas (Padrão, GKrellM, Planet, Computador Antigo, Brother Away, Kojiro, Big Media Player) | `bsmd/themes.py` e pacotes | desenhados pelo mesmo renderizador; nenhum tema reimplementado no app |
| Configurações por display, validação, spool de comandos via `bsm-helper` (polkit) | `bsmd/settings.py`, `bsm-helper` | ids `android-…`, chaves `android_*`, comandos de pareamento |
| Camada de toque (gestos, barra, menu, galerias com miniaturas reais, preferências por display) | `bsmd/touch.py` (FOSTON) | usada como está, com acréscimos (mídia, "Automático", "Calibrar" só quando existe) |
| Agente de mídia MPRIS e hub | `bsmd/media/` | controles do Big Media Player pelo toque (canal de volta com lista fechada) |
| Transporte TCP e padrão de cliente em aparelho (BigFoston OS) | `bsmd/displays/transport.py`, FOSTON | referência de projeto; o Android ganhou protocolo próprio (ver 02) |
| Janela "Meus Displays", bandejas, status, diagnóstico | `displays_page.py`, `screentray/`, `traykit/` | Android aparece como os outros displays |

## Pontos de atenção encontrados

* O serviço roda com `DynamicUser`, `IPAddressDeny=any` e só 127.0.0.0/8 + a rede USB do FOSTON liberados:
  escutar na LAN é mudança de segurança → **opcional e desligado por padrão** (ver 09).
* As regras udev do projeto nunca liberam um fabricante inteiro ao serviço: o USB do Android foi
  desenhado para respeitar isso (ver 05).
* O canal de mídia era só agente → serviço por decisão de segurança; a FOSTON deixou "controle de mídia
  pelo toque" como pendência. Resolvido com lista fechada de ações (ver 07, 09).
* `tests/test_gui.py::test_narrow_window_collapses` já falha na `origin/main` nesta sessão
  (Big WindowMaker Wayland/wlmaker): pré-existente, não relacionado.
* Sem JDK na máquina e sem aparelho Android conectado durante o trabalho (só FOSTON/BigFoston e AX206).
