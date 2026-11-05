# Big Media Player — testes

`python3 -m pytest -q tests` → **820 testes passando** (633 anteriores, sem
regressão, + 187 novos: 166 nos arquivos abaixo e 21 casos do tema novo nos testes responsivos existentes, que percorrem todo `THEME_IDS`).

## Arquivos

| Arquivo | Tipo | Cobertura |
| --- | --- | --- |
| `tests/test_media.py` (27) | unitário | contrato e validação; interpolação; formatação; política de seleção (automático, roubo após 2 s, clipes curtos, último, fixo, ignorados, troca desligada, player encerrado); decodificador de quadros (tamanho, JSON inválido); seat ativo; **socket Unix real** servidor↔publicador (permissões, uid do par, coalescência, cliente não autorizado, quadro gigante); hub (capa, espectro, agente ausente, usuário do seat); capas (SSRF, `file://`, `data:`, formatos, limites, cache, falhas); parsers de volume (incluindo a saída real com `(null)`); FFT (tom de 1 kHz na banda certa, silêncio) |
| `tests/test_media_dbus.py` (7) | **integração D-Bus real** num `dbus-daemon` privado | descoberta e metadados; `PropertiesChanged`/`Seeked`/troca de faixa; barra parada quando pausado; comandos e capacidades (Next recusado sem ser enviado, Shuffle, SetPosition); player encerrado; duração desconhecida; **agente→hub→tema** com capa de arquivo, navegador que não rouba o Spotify tocando e assume após a pausa; agente real como processo: interface D-Bus, instância única |
| `tests/test_bigmedia.py` (132) | tema | 7 skins × 9 resoluções; estados (pausado, sem capa, ao vivo, sem capacidades, sem players, sem agente); nada inventado (duração, sensores); capacidades e volume no quadro; demo só na prévia; 5 modos de espera; troca para outro tema e retorno; 8 modos × 3 posições de telemetria; regras de visibilidade; rótulos DECO/FFT; 17 opções de aparência; player fixo/ignorado por display; skin por aplicativo/noite; intervalo de quadro; **nenhuma área se sobrepõe**; validação de texto e por display; candidatos de logo; custo de render |
| `tests/mpris_fake.py` | dublê | player MPRIS2 real em Gio (também executável: `python3 tests/mpris_fake.py nome`) |

Os testes D-Bus são pulados quando PyGObject ou `dbus-daemon` faltam (imagem
mínima do CI).

## Verificações manuais nesta máquina

| Verificação | Resultado |
| --- | --- |
| Serviço `--simulate` + agente real + player de teste no D-Bus da sessão | snapshots recebidos pelo socket; `--media next` trocou a faixa; quadro com volume real 19 % |
| Volume real (PipeWire) | mudança externa 19→22 %, mute e unmute refletidos em ~90 ms; escrita confirmada; volume restaurado |
| Chrome real tocando vídeo | detectado e escolhido automaticamente (título, duração, posição; Anterior/Próximo desabilitados porque o Chrome não os anuncia; sem `artUrl` → arte de substituição) |
| Firefox real tocando | detectado ("Mozilla firefox") |
| Janela GTK4 | aba renderizada com o player real e controles (captura `config_gui.py --screenshot … --page theme_big_media_player`) |

## Não testado diretamente

Spotify, VLC, Rhythmbox e os demais players **não estavam instalados**; seguem a
mesma especificação MPRIS coberta pelo player de teste. PulseAudio puro,
`wpctl`-only e ALSA-only: cobertos pelos parsers (com saídas reais), não por
servidores reais. Hardware USB: os temas usam o mesmo pipeline já validado; o
Big Media Player foi exercitado no painel simulado (incluindo throughput serial).
Leitor de tela (Orca): rótulos acessíveis definidos, teste real pendente.
