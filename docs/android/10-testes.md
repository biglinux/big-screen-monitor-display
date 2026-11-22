# 10 — Testes

## O que foi executado (22/11/2026, Manjaro, Python 3.14, sessão Big WindowMaker Wayland/wlmaker)

| Comando | Resultado |
|---|---|
| `python -m pytest -q -p no:cacheprovider` (suíte inteira) | **1515 passaram, 1 falhou** — `test_gui.py::test_narrow_window_collapses`, que já falha na `origin/main` nesta mesma sessão (o wlmaker não aplica o tamanho pedido); pré-existente |
| `python -m pytest tests/test_android.py` (×3 seguidas) | 37/37 em cada uma das 3 execuções |
| `python -m pytest tests/test_gui.py -k android` | janela real GTK/libadwaita: grupo Android, pedido, card do celular, página, diálogo com QR, spool |
| `python3 tools/android-bench.py …` | ver [11](11-desempenho.md) |

`pytest.ini` trata arquivo/socket não fechado como erro; os testes Android passam com isso.

## Cobertura dos testes automatizados (`tests/test_android.py`)

O celular é o cliente de referência `tests/android_client.py`, que fala BSDP sobre **TLS de verdade**
com o hub/runtime reais.

| Área | Testes |
|---|---|
| Protocolo | enquadramento byte a byte, magia/versão/tipo/tamanho inválidos, JSON não-objeto ou não-UTF-8, `HELLO` hostil (escapes, ids, nonce, tamanhos), retângulos fill/zlib/JPEG (zlib exato), formatos que o app aceita, HMAC/SAS ligados a cada entrada, vetores compartilhados com o Kotlin, tamanho de desenho por perfil |
| Hub | identidade criada uma vez e privada (0700/0600), descoberta sem segredos, pareamento por ticket (uso único) e autenticação com certificado fixado, token errado/aparelho desconhecido/ticket inválido, bloqueio após falhas, confirmação aprovada e recusada, lixo e não-TLS, versão diferente avisada, revogação derruba a conexão, PING e backlog limitado |
| Runtime | celular vira display com quadros reais e status; rotação redesenha na nova proporção; deslizar troca o tema **só deste display**; comandos do app conferidos (chaves proibidas e valores inválidos descartados); troca de transporte mantém **um** display e a conexão antiga não recebe mais nada; celular parado não trava outro; display desativado recebe BYE; spool (abrir pareamento, revogar) e nenhum segredo no status |
| Mídia | comando chega ao agente; ação fora da lista recusada no serviço **e** no agente; barra do toque só com botões que o player oferece |
| USB (AOA) | reconhecimento de celulares pelas interfaces no sysfs (painel e acessório excluídos); sequência 51/52×6/53; aparelho sem AOA não recebe mais nada; troca automática só para hash conhecido, uma vez por minuto; ponte bulk ↔ link com pareamento por confirmação e hash do serial lembrado |
| Android (JUnit, no CI) | provas, SAS, display id, PING/TOUCH/PRESENTED byte a byte, PRESENT/BRIGHTNESS/VIEW, RECT zlib e fill, entradas quebradas, base64url |

## O que NÃO foi testado (sem o equipamento nesta máquina)

* **Nenhum aparelho Android físico** e nenhum emulador (sem JDK/imagens de sistema): o APK, a
  interface do app, TLS do lado Java, decodificação real, toque real, rotação, brilho, AOA real,
  ancoragem USB e adb reverse ficam pendentes. O APK é compilado e o JUnit roda no GitHub Actions
  (`.github/workflows/android.yml`) — resultado do CI ainda não observado nesta entrega.
* Testes instrumentados no Android (Espresso) não foram escritos: dependeriam de AndroidX, que o app
  evita de propósito (Android 5.0+); fica como próximo passo com um módulo de teste separado.
* Suspensão/retomada do PC, sessões longas (> 1 h), consumo de bateria no celular.
* KDE Plasma, GNOME, Cinnamon, XFCE: a integração usa só o que já era testado nesses ambientes
  (status, spool, janela); não houve sessão desses ambientes nesta máquina.
* Displays USB físicos durante esta entrega: AX206 e FOSTON BigFoston estavam conectados ao serviço
  do sistema (versão instalada); a suíte cobre os drivers por simulação, sem regressão.
