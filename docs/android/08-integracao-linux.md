# 08 — Integração com o Linux

## Runtime

* `AndroidHub` é criado pelo `Runtime` do serviço (não em `--simulate`). O supervisor
  (`_supervise_android`, 1×/s e na hora em que um celular termina o handshake) liga/desliga a escuta
  conforme `android_network`/`android_usb`/`android_port`, roda o `AccessoryWatcher` e cria uma
  `DisplaySession` `android-xxxxxxxxxxxx` para cada aparelho com link vivo (`AndroidSource`).
* Display desativado ("Usar este display" desligado): a sessão é removida e o app recebe BYE `disabled`.
* A sessão do Android usa a mesma máquina de estados, backoff, watchdog e incidentes dos painéis USB;
  um celular lento ou parado só degrada a própria sessão (`test_stalled_phone_does_not_block_the_others`).
* Coleta de sensores continua única e compartilhada; nenhum serviço novo.
* Status (`status.json`) ganha `android`: escuta, porta, endereços, impressão digital, pedidos de
  pareamento (com código), pareados (sem tokens), conectados, contadores. Nenhum segredo.

## Meus Displays

* Cada celular conectado vira um card (ícone de celular, nome do aparelho, resolução do desenho, tema
  real — inclusive o escolhido pelo toque) e uma página própria com: nome, uso, tema, orientação,
  brilho, desempenho, **qualidade da imagem, tamanho do desenho, girar com o celular, manter a tela
  ligada, burn-in, toque, controles de mídia, remover pareamento**, conexão (Wi-Fi/USB e endereço),
  protocolo (BSDP · TLS), Android/app/tela/dpi, identificar (o padrão "identify" aparece no celular),
  padrões de teste e reconectar.
* Grupo **Celulares e tablets Android**: conectar pela rede, conectar por cabo USB, estado da escuta,
  pedidos de pareamento (Permitir/Recusar com o código), aparelhos pareados (conectado/último
  contato, remover com confirmação), celulares no cabo ("Usar como display") e **Adicionar Android…**.
* Comandos (aprovar, recusar, remover, abrir/fechar pareamento) vão pelo spool root do `bsm-helper`
  (polkit), como os demais comandos por display.

## Bandeja

Os displays Android aparecem na bandeja como qualquer display (seleção, "Todos os displays", estado
colorido, comandos só onde há capacidade — ver [docs/windowmaker/symbolic-tray.md](../windowmaker/symbolic-tray.md)).
A bandeja também reativa por USB celulares já pareados por cabo (ver 05).

## Serviço e pacotes

* `big-screen-monitor-display.service`: `IPAddressAllow` com faixas privadas e link-local (públicas
  continuam bloqueadas); `MemoryHigh` 256M / `MemoryMax` 384M (medido, ver 11).
* udev: só `18d1:2d00|2d01` (modo acessório) para o grupo do serviço.
* Dependência nova: `openssl` (certificado do computador). Opcional: `python-qrcode` (QR na janela).
