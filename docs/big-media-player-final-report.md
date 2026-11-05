# Big Media Player — relatório final

## Entregue

| Etapa | Resultado |
| --- | --- |
| 1. Auditoria | arquitetura confirmada (ThemeRegistry, runtime por display, SettingsStore, coletor de telemetria, agente de som, janela GTK4 com aba por tema); serviço sandboxed sem acesso à sessão → agente de sessão + socket Unix |
| 2. MPRIS | `bsmd/media/mpris.py` (Gio, assíncrono, sinais), `selection.py` (ActivePlayerManager), comandos com capacidades |
| 3. Volume real | `bsmd/media/volume.py`: PipeWire/PulseAudio por eventos, wpctl e ALSA de reserva, mudo, saída escolhida, máximo seguro |
| 4. Motor visual | `bsmd/bigmedia/`: layout responsivo A–F (micro, retrato, paisagem, ultrawide), primitivas procedurais, cache de camadas, capa (formas, molduras, brilho, vinil, transição, fundo desfocado, cores da capa), logo da distro |
| 5–6. Skins | Bigamp, Bigmatch, Bigative, Bigalplayer, Big Media Player, BigXMMS2, BIGX Multimedia System |
| 7. Telemetria | faixa comum com 8 modos e 3 posições, itens do coletor existente |
| 8. Configurações | aba *Big Media Player*: prévia ao vivo, controles reais, galeria, 10 grupos, diagnóstico |
| 9. Refino | correções a partir de capturas em 9 resoluções; agente 56→41 MB; troca de player agendada no instante exato |
| 10. Entrega | 820 testes, documentação, autostart, PKGBUILD |

## Critérios de aceitação

| # | Critério | Situação |
| --- | --- | --- |
| 1 | aparece na lista de temas | ✅ `themes.REGISTRY`, galeria da janela |
| 2 | sete skins | ✅ |
| 3 | prévia | ✅ música real na janela; `DEMO` sem players |
| 4 | detecção MPRIS | ✅ testes D-Bus reais; Chrome e Firefox reais detectados |
| 5 | metadados reais | ✅ |
| 6 | capa | ✅ file/data/http(s) com limites; substituta original quando ausente |
| 7 | barra acompanha | ✅ interpolação + Seeked + ressincronização |
| 8 | tempos corretos quando fornecidos | ✅ µs → mm:ss/h:mm:ss; desconhecido nunca inventado |
| 9 | Play/Pause em interface real | ✅ janela, atalhos de teclado (Ctrl+Espaço), `--media play_pause` |
| 10 | Anterior/Próximo respeitam capacidades | ✅ desabilitados na janela e no LCD; recusados sem envio |
| 11 | volume da saída padrão | ✅ medido com PipeWire real |
| 12 | mudo | ✅ |
| 13 | logo da distribuição | ✅ busca ampliada (LOGO, ID, NAME, ID_LIKE, temas de ícones) + personalizada + genérica |
| 14 | telemetria opcional | ✅ |
| 15 | modos fixo, intermitente, oculto | ✅ (+ alternado, pausado, ocioso, alertas, auto) |
| 16 | configurações persistidas | ✅ esquema validado, helper polkit existente, por display |
| 17 | funciona sem hardware na prévia | ✅ |
| 18 | funciona sem MPRIS | ✅ tela de espera; agente ausente indicado |
| 19 | testes relevantes | ✅ 187 novos |
| 20 | sem regressões | ✅ 633 testes anteriores passam |
| 21 | leve e estável | ✅ 1,6 ms/quadro a 480×320; 1–3 % de CPU do serviço tocando |
| 22 | documentação | ✅ 10 documentos + README |

## Decisões

- **Agente de sessão + socket Unix unidirecional** em vez de abrir o D-Bus da
  sessão no serviço: preserva o sandbox (`DynamicUser`, `ProtectHome`) e a
  separação de usuários (uid do seat ativo).
- **Capas como RGB cru**: o serviço não executa decodificadores de imagem com
  dados da sessão.
- **Gio/GLib e `pactl`/`wpctl`** já presentes no sistema; nenhuma dependência
  obrigatória nova (`libpulse`/`wireplumber` como opcionais justificadas).
  `playerctl` não é necessário.
- **Botões no LCD só refletem estado**: nenhum painel suportado tem entrada.
  Toque/botões físicos não foram implementados porque nenhum modelo suportado
  documenta essa entrada.
- **Visualizador**: decorativo por padrão e rotulado `DECO`; espectro real
  (`FFT`) só por escolha explícita, capturando o monitor da saída com nome de
  stream visível nas configurações de som, e só enquanto algo toca. Não há
  sliders de equalizador falsos.

## Limitações conhecidas

- Sem touch: controles funcionais na janela, atalhos e linha de comando.
- MPRIS não tem descrição universal; usa `xesam:comment` quando existe.
- Miniaturas de vídeo dependem do site/navegador fornecer `mpris:artUrl`.
- `wpctl` e ALSA não têm fluxo de eventos: leitura a cada 2 s.
- Espectro real requer `parec` (libpulse) e é mono (monitor mixado da saída).
- Verificação de endereço público das capas tem uma janela teórica de
  *DNS rebinding* entre a checagem e a conexão (impacto: só uma imagem).
- Seleção por display: modos fixo/ignorados por display; o modo automático
  usa a escolha do agente (global) para manter janela e display em acordo.
- Traduções: textos novos em inglês com `gettext`; os catálogos são gerados
  pelo fluxo de tradução automática do CI.
- Não testados diretamente (não instalados): Spotify, VLC, Rhythmbox e outros
  players; PulseAudio puro; hardware USB físico com este tema.

## Ideias adicionais implementadas

Cores derivadas da capa (com contraste garantido), transição de capa, marquee
com pausa nas pontas (ou laço estilo LCD no Bigamp/BIGX), modo vinil, modo
festa, modo informação, modo baixo consumo, modo noturno com skin própria,
seleção de saída de áudio, skin por aplicativo, origem do player no título,
atalhos de teclado e comando de linha.
