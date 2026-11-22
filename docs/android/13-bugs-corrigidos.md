# 13 — Problemas encontrados e correções

| # | Problema | Causa | Correção | Teste de regressão |
|---|---|---|---|---|
| 1 | Dois testes da FOSTON falhavam ao mesclar na `main` atual | `open(...).read()` sem fechar; a `main` passou a tratar `ResourceWarning` como erro | leitura com `with`/`pathlib` | os próprios testes (`test_foston.py`) |
| 2 | Funções `pixels_of` duplicadas após a mescla | mesma correção (Pillow 12.1) feita nas duas branches | mantida a de `conftest.pixels` | `test_bigmedia*.py` |
| 3 | Ícone genérico no Big WindowMaker (Wayland) | `app_id` do GTK (`br.com.biglinux.BigScreenMonitorDisplay`) ≠ nome do `.desktop`; X11 sem `_NET_WM_ICON` | `.desktop` renomeado para o `app_id`, `set_default_icon_name` (detalhes em [windowmaker/icon-windowmaker](../windowmaker/icon-windowmaker.md)) | `test_window_identity.py`, `test_install.py` |
| 4 | Bandeja mostrava serviço parado como display desconectado | um só vermelho para os dois casos | ponto cinza para serviço parado, regras de agregação ([windowmaker/symbolic-tray](../windowmaker/symbolic-tray.md)) | `test_tray_status.py` |
| 5 | Controle do Big Media Player pelo toque ausente (pendência da FOSTON) | canal de mídia só agente → serviço | resposta na mesma conexão com lista fechada, conferida dos dois lados | `test_media_controls_reach_the_agent_and_only_whitelisted` |
| 6 | "Calibrar" aparecia no menu de qualquer display com toque | menu fixo da FOSTON | só quando o driver tem calibração | `test_touch_menu_offers_calibration_only_where_it_exists` |
| 7 | Card em Meus Displays não mostrava o tema escolhido no próprio display | o card usava só as configurações salvas | usa o tema reportado pelo serviço quando a janela não tem mudança pendente | `test_android_in_my_displays` (card com o tema escolhido no celular) |
| 8 | App com versão de protocolo diferente só via a conexão cair | o hub fechava sem dizer por quê | `REJECT version` | `test_other_protocol_version_is_told_to_update` |
| 9 | (desenvolvimento) Cliente de teste perdia mensagens | leitura e escrita no mesmo `SSLSocket` do Python em duas threads (não suportado pelo OpenSSL) | o servidor já usava uma thread de E/S por conexão; o cliente de teste passou a usar a mesma classe `Link` | suíte `test_android.py` repetida 3× |
| 10 | (desenvolvimento) Integração não recebia quadros | testes sem `android_network`: o supervisor fechava a escuta, como deve | testes configuram a porta; sem rede o hub mantém escuta só em 127.0.0.1 para adb | `test_phone_becomes_a_display_with_real_frames` e seguintes |
| 11 | Uso de memória acima do `MemoryHigh` em telas grandes | caches dos temas crescem com a área de desenho (medido) | padrão de 1280 px no Android e limites 256M/384M | medição em [11](11-desempenho.md) |

## Pré-existente, não corrigido

`tests/test_gui.py::test_narrow_window_collapses` falha também na `origin/main` na sessão wlmaker
(o compositor não aplica o tamanho pedido pelo teste). Não relacionado a esta entrega.
