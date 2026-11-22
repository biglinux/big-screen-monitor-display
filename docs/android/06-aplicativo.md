# 06 — Aplicativo Android

`android/` — pacote `br.com.biglinux.bigscreen` (depuração: `.debug`), versão 5.4.0 (a mesma do programa no computador), **Android 5.0+**
(minSdk 21, targetSdk 36).

## Tecnologia escolhida

| Opção | Avaliação |
|---|---|
| Kotlin + **widgets do framework** (sem AndroidX) | roda do Android 5.0 em diante (celulares antigos são o público principal), APK pequeno, sem dependências para baixar ou atualizar; tema Material do próprio sistema (claro/escuro) | **escolhida** |
| Jetpack Compose + Material 3 | mais moderno, mas as bibliotecas Jetpack atuais exigem Android 6.0+ (minSdk 23), APK de vários MB e inicialização mais lenta em aparelhos antigos | rejeitada para esta versão |

Desenho: `DisplayView` (View com aceleração de hardware) desenha o quadro com filtragem; nenhum
`SurfaceView`/GL é necessário para 2–15 quadros/s de conteúdo majoritariamente estático.

## Telas

* **Início**: logo oficial, "Como deseja conectar?" com **Wi-Fi ou rede**, **Cabo USB**, **Ler o
  código** e **Adicionar pelo endereço**; seus computadores (toque conecta, toque longo esquece);
  computadores encontrados nesta rede; Configurações; Ajuda.
* **Display**: tela cheia imersiva (opcional), quadro escalado sem distorcer e centralizado, recortes
  de câmera respeitados (modo padrão do sistema), orientação vinda do computador (travada ou
  automática). Sobreposição de estado (conectando, código de pareamento, reconectando, motivo da
  desconexão com ação: tentar de novo, parear de novo, escolher computador). Botão discreto de
  menu que aparece ao tocar e some; **dois dedos** abrem o menu do app (menu do tema, tema anterior/
  próximo, configurações, diagnóstico, desconectar).
* **Configurações**: Conexão (nome do display, conectar automaticamente), Aparência (orientação,
  tela cheia), Tela (manter ligada, burn-in, brilho pelo computador), Desempenho (perfil, qualidade,
  tamanho do desenho), Interação (toque, controles de mídia), Sistema (versão, licença, projeto).
  As opções do display vão ao computador como `set` (validadas lá, mesma regra das escolhas feitas
  no toque) e só mudam conectado.
* **Diagnóstico**: computador, conexão, tempo conectado, FPS real, quadros, decodificação, ida e
  volta, tráfego, resolução do quadro → tela, último problema, versões.

Textos em inglês e português do Brasil; tema claro e escuro; rótulos de acessibilidade, títulos
de seção marcados (Android 9+), áreas de toque ≥ 48 dp.

## Ciclo de vida e energia

* Conecta em `onStart`, desconecta em `onStop` (BYE `paused`). **Sem serviço em segundo plano e sem
  wake lock**: a tela fica ligada pela flag da janela, só enquanto o tema aparece e só se "Manter a
  tela ligada" estiver ativo; ao sair, volta ao comportamento normal do aparelho.
* "Conectar automaticamente": abrir o app vai direto ao último computador; com o aparelho na
  tomada, vira display permanente.
* Brilho: só da janela do app (`screenBrightness`), sem permissão de sistema.
* Burn-in: desloca o quadro até 4 dp a cada 2 min.
* Rede/escrita fora da thread de UI; buffers de quadro reutilizados (dois bitmaps do tamanho do
  quadro, um `IntArray` de pixels); `release()` ao destruir.

## Permissões

Só `INTERNET` e `ACCESS_NETWORK_STATE`. Sem câmera (a câmera do sistema lê o QR e abre o link), sem
localização, sem armazenamento, sem `FOREGROUND_SERVICE`, sem `WAKE_LOCK`. `allowBackup=false` e
regras de extração que excluem as preferências (tokens) de backup e de cópia entre aparelhos.
