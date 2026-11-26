# Android como display — documentação

Celulares e tablets Android viram displays do Big Screen Monitor Display, com os mesmos temas,
toque na própria tela, conexão por Wi-Fi/Ethernet ou cabo USB e gerenciamento em **Meus Displays**.

Estes arquivos registram o desenvolvimento. Nada no programa ou no aplicativo depende deles.

| Arquivo | Conteúdo |
|---|---|
| [01-auditoria](01-auditoria.md) | O que o projeto já tinha e o que foi reaproveitado |
| [02-arquitetura](02-arquitetura.md) | Arquitetura, estratégia de renderização, alternativas rejeitadas |
| [03-protocolo](03-protocolo.md) | BSDP v1: mensagens, handshake, limites |
| [04-conexao-rede](04-conexao-rede.md) | Wi-Fi/Ethernet: descoberta, pareamento, reconexão |
| [05-conexao-usb](05-conexao-usb.md) | USB: acessório Android (AOA), ancoragem, adb |
| [06-aplicativo](06-aplicativo.md) | O APK: tecnologia, telas, ciclo de vida, energia |
| [07-touchscreen](07-touchscreen.md) | Gestos, menus, troca de tema, Big Media Player |
| [08-integracao-linux](08-integracao-linux.md) | Runtime, Meus Displays, bandeja, serviço |
| [09-seguranca](09-seguranca.md) | Ameaças, TLS, tokens, pareamento, permissões |
| [10-testes](10-testes.md) | Testes automatizados e o que foi (e não foi) testado |
| [11-desempenho](11-desempenho.md) | Medições reais e metas |
| [12-instalacao-e-apk](12-instalacao-e-apk.md) | Instalação, compilação do APK, assinatura, CI |
| [13-bugs-corrigidos](13-bugs-corrigidos.md) | Problemas encontrados e correções |
| [15-relatorio-final](15-relatorio-final.md) | Critérios de aceitação, evidências, limitações |

O ícone no Big WindowMaker e o ícone symbolic da bandeja estão em [docs/windowmaker](../windowmaker/).

## Plano por etapas (e situação)

| Etapa | Situação |
|---|---|
| 1. Auditoria | ✅ [01](01-auditoria.md) |
| 2. Arquitetura e protocolo (com testes) | ✅ [02](02-arquitetura.md), [03](03-protocolo.md) |
| 3. Rede (backend Linux + app) | ✅ backend testado de ponta a ponta com cliente de referência; app ⏳ sem aparelho |
| 4. USB | 🟡 AOA implementado e testado com USB simulado; ⏳ hardware real |
| 5. APK | ✅ compilado no GitHub Actions (lint sem achados, JUnit ok); ⏳ aparelho |
| 6. Touchscreen | ✅ no computador (gestos, menu, mídia); ⏳ no aparelho |
| 7. Meus Displays | ✅ testado na janela real (GTK, sessão wlmaker) |
| 8. Ícone no Big WindowMaker | ✅ Wayland (wlmaker) verificado; X11 só via Xwayland |
| 9. Bandeja | ✅ ícone verificado no `big-wm-tray`; menu por testes offscreen |
| 10. Otimização | ✅ medições do lado Linux ([11](11-desempenho.md)); ⏳ no aparelho |
| 11. Testes e correções | ✅ suíte Linux; ⏳ testes instrumentados Android |
| 12. Compilação e entrega | ✅ APK de depuração e release (sem assinatura) como artefato do CI |
