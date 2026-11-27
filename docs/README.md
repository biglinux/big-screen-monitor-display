# Documentação

Comece pelo que você quer fazer. Os relatórios técnicos registram decisões,
medições e bugs de cada fase do projeto; os mais antigos ficam no fim, como
histórico.

## Usar

| Quero… | Leia |
| --- | --- |
| saber se o meu aparelho funciona | [compatibilidade.md](compatibilidade.md) (gerada dos drivers) |
| instalar fora do Arch/BigLinux | [21 — Instalação manual](21-instalacao-manual.md) |
| usar o celular ou tablet como display | [android/12 — Instalação e APK](android/12-instalacao-e-apk.md) · [android/04 — Rede e Tailscale](android/04-conexao-rede.md) |
| testar um painel que ainda é nível B | [17 — Testes em hardware real](17-testes-hardware.md) e o [formulário de hardware](https://github.com/ruscher/big-screen-monitor-display/issues/new?template=1-hardware.yml) |
| distribuições e ambientes gráficos testados | [20 — Compatibilidade](20-compatibilidade.md) |
| um display caseiro (ESP32, Raspberry Pi) | [25 — Protocolo BSMD-lite](25-protocolo-bsmd-lite.md) |
| resolver o SmartMonitor travado depois de suspender | [smartmonitor-usb-reset.md](smartmonitor-usb-reset.md) |

## Por recurso

| Recurso | Começo | Todos |
| --- | --- | --- |
| Big Media Player | [visão geral](big-media-player-overview.md) | arquitetura, MPRIS, volume, skins, Modern Collection, desempenho e testes: `big-media-player-*.md` |
| Kojiro (papel de parede como painel) | [visão geral](kojiro-overview.md) | editor, elementos, predefinições, formato, desempenho e testes: `kojiro-*.md` |
| Brother Away | [07 — Direção de arte](07-brother-away-design.md) | [08 — Motor narrativo](08-brother-away-narrativa.md) |
| Android | [android/README.md](android/README.md) | protocolo, segurança, toque, desempenho: [android/](android/) |
| Coolers DeepCool | [deepcool/02 — Arquitetura](deepcool/02-arquitetura.md) | [deepcool/](deepcool/) |
| FOSTON FS-707DC | [foston-fs707dc/13 — Relatório final](foston-fs707dc/13-relatorio-final.md) | [foston-fs707dc/](foston-fs707dc/) |
| Bandejas do sistema | [19 — Bandejas](19-bandejas.md) | [windowmaker/](windowmaker/) |
| GPU (AMD, NVIDIA, Intel) | [24 — GPU de todos os fabricantes](24-gpu-todos-os-fabricantes.md) | |
| Traduções | [i18n.md](i18n.md) | |
| Nome e logo do sistema | [session-identity.md](session-identity.md) | |

## Como funciona por dentro

| Assunto | Documento |
| --- | --- |
| drivers e detecção | [13 — Arquitetura dos drivers](13-arquitetura-drivers.md) · [14 — Detecção](14-deteccao.md) · [12 — Protocolos](12-protocolos.md) |
| vários displays ao mesmo tempo | [15 — Múltiplos displays](15-multi-display.md) |
| watchdog e recuperação | [03 — Watchdog](03-watchdog-recuperacao.md) |
| segurança e permissões | [04 — Segurança](04-seguranca-permissoes.md) · [android/09](android/09-seguranca.md) · [SECURITY.md](../SECURITY.md) |
| temas | [06 — Arquitetura de temas](06-arquitetura-temas.md) |
| interface (design system) | [redesign/](redesign/) |
| desempenho | [05 — Antes × depois](05-performance-benchmarks.md) · [16 — Benchmarks](16-benchmarks.md) |

## Contribuir

[CONTRIBUTING.md](../CONTRIBUTING.md) · **[Planejamento estratégico](PLANEJAMENTO-ESTRATEGICO.md)** (auditoria e roadmap atual) · [PLANNING.md](../PLANNING.md) (roteiro executado) ·
[CHANGELOG.md](../CHANGELOG.md) · integrações de PRs externos:
[22 — PR #11](22-integracao-pr11.md), [23 — PR #19](23-integracao-pr19-palmos.md).

## Histórico (relatórios de fases encerradas)

Mantidos como registro das decisões; o estado atual está nos documentos acima.

- **4.0 (reconstrução):** [01 — Auditoria da 3.1](01-auditoria-tecnica.md) ·
  [02 — Travamentos](02-analise-travamentos.md) · [09 — Testes](09-testes-validacao.md) ·
  [10 — Relatório final](10-relatorio-final.md)
- **4.1 (Universal Display Engine):** [11 — Compatibilidade de hardware](11-compatibilidade-hardware.md) ·
  [18 — Relatório final](18-relatorio-universal-display-engine.md)
- **4.2 a 4.4:** [kojiro-final-report.md](kojiro-final-report.md) ·
  [big-media-player-final-report.md](big-media-player-final-report.md) ·
  [big-media-player-modern-report.md](big-media-player-modern-report.md)
