# 05 — Conexão por USB

Uma conexão física USB não dá, sozinha, um canal de dados com um app Android. Alternativas avaliadas:

| Método | Precisa de | Avaliação | Situação |
|---|---|---|---|
| **Android Open Accessory (AOA)** | só aceitar "Abrir com Big Screen Monitor Display" (uma vez, marcando "Sempre") | sem depuração, sem root, sem rede; canal bulk direto; suportado desde Android 3.1/4.x (base do Android Auto com fio) | **implementado**; ⏳ não validado em aparelho |
| Ancoragem USB (RNDIS/NCM) | ativar "Ancoragem USB" no celular | funciona hoje pela rede (mesma pilha, transporte `usb-tether`); o PC pode passar a usar a internet do celular como rota padrão (NetworkManager) | suportado, documentado |
| adb reverse | depuração USB ligada + `adb reverse tcp:7717 tcp:7717` | confiável, mas exige modo desenvolvedor | suportado (loopback, transporte `usb-adb`) |
| USB Host no celular | celular como host | inverte os papéis; o PC não é um periférico | descartado |

## Como o AOA funciona aqui

1. **Troca de modo — lado da sessão do usuário.** A janela (Meus Displays › "Usar como display" em
   cada celular no cabo) ou a bandeja (automaticamente, só para celulares **já pareados por USB**)
   enviam os pedidos AOA 51/52/53 com fabricante `BigLinux` e modelo `BigScreenMonitorDisplay`. A
   sessão já tem acesso ao celular pelas regras `uaccess` do sistema (MTP/PTP/adb). O celular
   reaparece como `18d1:2d00` (ou `2d01`) e o Android oferece abrir o app (`accessory_filter.xml`).
2. **Link — serviço.** Uma regra udev entrega **apenas** `18d1:2d00|2d01` ao grupo
   `big-screen-monitor`. O `AccessoryWatcher` reivindica os endpoints bulk e os liga a um par de
   sockets; dali em diante é o mesmo `Link`, handshake e token da rede (sem TLS: o cabo é o canal).
   Ao parear por USB, o serviço guarda um **hash** do número de série USB para reconhecer o celular
   na próxima vez (o número em si não é guardado nem publicado).
3. **Sem o cabo**, o app continua pela rede com a mesma identidade; o display e o tema são os mesmos.

O serviço nunca envia pedidos AOA e nunca recebe acesso a celulares fora do modo acessório: as regras
udev do projeto continuam sem liberar fabricantes inteiros.

## Requisitos e limitações (honestas)

* O celular precisa estar em "Transferência de arquivos" (MTP) ou "PTP" para a sessão ter acesso
  (`uaccess`); em "Somente carregar" muitos aparelhos não expõem interface alguma.
* Alguns fabricantes removeram o suporte a AOA em aparelhos recentes ou o restringem; não há
  promessa de plug-and-play universal. Ancoragem e adb ficam como alternativas.
* Se o número de série USB mudar no modo acessório (depende do aparelho), a reativação automática
  pela bandeja não reconhece o celular; "Usar como display" na janela continua funcionando.
* **Nada disso foi validado em aparelho real** nesta entrega (nenhum Android disponível): os testes
  usam um pyusb falso que reproduz a sequência e a ponte bulk (ver 10).
