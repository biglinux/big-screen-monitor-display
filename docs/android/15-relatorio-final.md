# 15 — Relatório final

**Data:** 22/11/2026 · **Branch:** `feat/android-display` (inclui `feat/foston-fs707dc` e
`feat/tray-symbolic-wm-icon`) · Máquina: Manjaro, AMD Ryzen 7 5700G, sessão Big WindowMaker Wayland.

Legenda: ✅ demonstrado com evidência · 🧪 coberto por teste automatizado/simulação · ⏳ pendente
de hardware ou de execução · ❌ não feito.

## Critérios — Android

| Critério | Situação |
|---|---|
| APK instala e abre | ✅ APK gerado no GitHub Actions (5.4.0, minSdk 21); ⏳ instalação em aparelho real |
| Opções Rede e USB | 🧪 implementadas (telas no código); ⏳ visual no aparelho |
| Rede com o backend real | 🧪 backend real + cliente de referência sobre TLS (36 testes); ⏳ app real |
| USB pelo método documentado | 🧪 AOA com pyusb simulado; ⏳ cabo e aparelho reais. Ancoragem e adb usam o caminho de rede testado |
| Registro em Meus Displays | ✅ janela real (teste GTK) com status de um celular |
| Temas exibidos corretamente | 🧪 os 7 temas renderizados e transmitidos sem perdas ao cliente de referência ([11](11-desempenho.md)); ⏳ tela do aparelho |
| Telemetria real | ✅ mesma coleta dos painéis (sem dados fictícios) |
| Troca de tema pelo toque | 🧪 deslizar no cliente troca só o tema daquele display |
| Configurações individuais preservadas | 🧪 por display no `settings.json` + escolhas do toque persistidas |
| Comandos de mídia | 🧪 até o agente, com lista fechada; ⏳ player real a partir do celular |
| Reconexão sem duplicar | 🧪 troca de transporte mantém um display; conexão antiga isolada |

## Critérios — Linux

| Critério | Situação |
|---|---|
| Android como display adicional | 🧪 sessão própria no runtime |
| Vários displays simultâneos e independentes | 🧪 dois celulares, um parado sem afetar o outro; painéis USB pela suíte existente |
| Ícone oficial no Big WindowMaker | ✅ Wayland (wlmaker, dock reiniciado); X11 só via Xwayland (`xprop`) |
| Bandeja com monitor symbolic | ✅ visto no `big-wm-tray` (wlmaker) |
| Quatro cores de estado | 🧪 regras testadas; ✅ vermelho visto na bandeja real |
| Seleção do display no menu | 🧪 testes offscreen; ⏳ menu aberto na sessão real |
| Comandos só no display escolhido | 🧪 |
| Displays USB continuam funcionando | 🧪 suíte inteira: 1515 passaram local (1 pulado pelo compositor) e 100 % no CI |

## Critérios — Qualidade

| Critério | Situação |
|---|---|
| Sem regressões conhecidas | ✅ suíte Linux local e CI |
| Sem erros de compilação | ✅ Python e Kotlin (CI, sem avisos do compilador) |
| Análise estática | ✅ lint Android "No Issues Found"; Python: imports não usados verificados por AST (`ruff` indisponível na máquina) |
| Sem vazamentos conhecidos | ✅ `ResourceWarning` é erro na suíte; ⏳ sessão longa |
| Sem permissões desnecessárias | ✅ app só com rede; serviço sem acesso a celulares fora do modo acessório |
| Sem credenciais expostas | ✅ status sem tokens/segredos (testado); nenhuma chave de assinatura criada |
| Sem dependência de documentação | ✅ |
| Testes e benchmark registrados | ✅ [10](10-testes.md), [11](11-desempenho.md) |

## Limitações reais

1. **Sem validação em aparelho** — o APK compila, passa no lint e nos testes JUnit, mas a UI, o TLS
   do lado Java, a decodificação, o toque e o AOA ainda precisam de um celular de verdade.
2. **AOA** pode não existir ou estar restrito em alguns aparelhos recentes; exige modo MTP/PTP para
   a sessão ter acesso ao celular.
3. **Edição do Kojiro pelo toque** não implementada (evita um segundo editor incompatível; o editor
   GTK continua sendo o único).
4. Android 5.x guarda o token sem Keystore (não há chave simétrica de app nessas versões).
5. Testes instrumentados Android, suspensão/retomada, sessão de 24 h e bateria não executados.
6. Sem mDNS (descoberta própria por UDP); redes que isolam clientes exigem endereço manual.

## Próximos passos

1. Instalar o APK de depuração (artefato do workflow `Android app`) em 2–3 aparelhos (um Android 5–7,
   um recente, um tablet) e preencher os ⏳ de [10](10-testes.md)/[11](11-desempenho.md).
2. Testar AOA com cabo em aparelhos de fabricantes diferentes.
3. Testes instrumentados num módulo à parte; sessão de 24 h; medir bateria.
4. Edição do Kojiro pelo toque reaproveitando o modelo do editor (protocolo de comandos de layout).
5. Configurar a assinatura de produção (segredos do CI) antes de publicar o APK.
