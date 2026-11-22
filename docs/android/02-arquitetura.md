# 02 — Arquitetura

```
 COMPUTADOR (serviço do sistema)                                   CELULAR / TABLET
 ┌──────────────────────────────────────────────┐                ┌──────────────────────────────┐
 │ telemetria ─┐                                │                │ Big Screen Monitor Display   │
 │ mídia (MPRIS│via agente da sessão)           │                │  Session (thread própria)    │
 │             ▼                                │   TLS 1.2+     │   leitura → FrameCanvas      │
 │ DisplaySession android-xxxxxxxxxxxx          │  (rede)  ou    │   (retângulos → work → front)│
 │  render: tema → touch.decorate → mailbox     │  bulk USB AOA  │   fila de escrita (toques…)  │
 │  transporte: AndroidDisplay (RasterDriver)   ├───────────────►│  DisplayView (escala, toque) │
 │    retângulos sujos → FILL / RGB+zlib / JPEG │◄───────────────┤  menu do app, configurações  │
 │    PRESENT ↔ PRESENTED (1 quadro em trânsito)│ toques, VIEW,  │  reconexão, diagnóstico      │
 │  toque → touch.TouchUI (gestos, menus)       │ comandos, STATS└──────────────────────────────┘
 │ AndroidHub: escuta, descoberta UDP, handshake,│
 │   pareamento, tokens, links por aparelho      │
 │ AccessoryWatcher: celulares em modo acessório │
 └──────────────────────────────────────────────┘
```

## Decisão de renderização

| Alternativa | Avaliação | Situação |
|---|---|---|
| 1. Linux desenha e envia quadros comprimidos | fidelidade total, um só renderizador | parte da solução |
| 2. Só regiões alteradas (dirty rectangles) | o `RasterDriver` já calcula; tráfego cai a poucos kB/quadro | **adotada junto com 1** |
| 3. Dados estruturados e desenho no Android | exigiria reescrever 7 temas, 15 skins, o editor Kojiro e as histórias do Brother Away em Kotlin, e manter as duas versões iguais | **rejeitada** (duplicação, divergência) |
| 4. Híbrida | sem ganho medido que justifique a segunda implementação | rejeitada por ora |

Codificação por retângulo (`protocol.encode_rect`): área uniforme → `FILL` (3 bytes); senão RGB+zlib
nível 1 (sem perdas, rápido, texto nítido); em áreas fotográficas (zlib > 35 % do bruto, ≥ 96×96)
JPEG 88 se ficar menor — e nunca em "Sem perdas". PNG e WebP existem no protocolo (o app decodifica)
mas não são escolhidos: no PC custam 5–20× mais CPU que zlib nível 1 para o mesmo conteúdo de
interface. Qualidade "Automática": sem perdas no cabo, equilibrada na rede.

Tamanho de desenho: o app informa a área útil; o tema é desenhado nessa proporção, limitado pelo
perfil (Econômico 960 px, Equilibrado/Automático 1280, Fluido 1920, ou "Resolução da tela"), e o
celular amplia com filtragem. O aparelho **gira sozinho** (`capabilities.orientation = "device"`):
o runtime não rotaciona quadros para ele; pede travamento (`CONFIG.orientation`) ou rotação automática.

Fluxo e backpressure: o mailbox de 1 posição do runtime descarta quadros obsoletos; o driver só envia
o quadro N depois do `PRESENTED` do N−1 (um quadro em trânsito, o próximo é codificado enquanto o
celular decodifica); a fila de saída do link tem limite (4 MiB) e quem escreve espera. Toques vão no
sentido contrário, por outra direção do mesmo socket, e nunca esperam por quadros.

## Identidade e transporte

* Cada instalação do app gera um UUID aleatório (nada de IMEI/serial). O display é
  `android-` + 12 hex do SHA-256 desse id: **o mesmo display em Wi-Fi, USB ou adb**.
* Uma conexão nova do mesmo aparelho substitui a anterior no hub (BYE `replaced`); a sessão do
  runtime reabre com o link novo. Quadros e toques da conexão velha morrem com ela (um `Link` por
  conexão, um handler por link).
* Sem o cabo, o app volta pela rede com a mesma identidade e o mesmo token.

## Arquivos

| Arquivo | Papel |
|---|---|
| `bsmd/displays/android/protocol.py` | BSDP: framing, validação, codificação de retângulos, HMAC/SAS |
| `bsmd/displays/android/link.py` | uma conexão: thread única de E/S, fila de saída, PING automático |
| `bsmd/displays/android/hub.py` | escuta TLS + UDP, handshake, pareamento, substituição de links |
| `bsmd/displays/android/security.py` | certificado do PC, aparelhos pareados, tickets e pedidos |
| `bsmd/displays/android/driver.py` | `AndroidDisplay` (RasterDriver), CONFIG, comandos do app |
| `bsmd/displays/android/aoa.py` | USB: troca para acessório (sessão) e ponte bulk ↔ socket (serviço) |
| `bsmd/runtime.py` | `AndroidSource`, `_supervise_android`, orientação do aparelho, spool |
| `gui/android_page.py` | grupo Android, diálogo com QR Code, linhas da página do display |
| `android/` | o aplicativo |
