# Segurança / Security

## Como relatar / How to report

**Não abra uma issue pública.** Use o relato privado do GitHub:
[Security › Report a vulnerability](https://github.com/ruscher/big-screen-monitor-display/security/advisories/new).
Resposta inicial em até 7 dias.

**Do not open a public issue.** Use GitHub private reporting (link above).
First answer within 7 days.

## Versões atendidas / Supported versions

Só a versão mais recente (a release *Latest*) recebe correções.
Only the latest release receives fixes.

## O que é sensível / What is in scope

- **O serviço** (`big-screen-monitor-display.service`): roda sem root
  (`DynamicUser`), com `DevicePolicy=closed`, filtro de syscalls e rede limitada a
  faixas privadas (`IPAddressAllow`). Escapar desse isolamento é crítico.
- **O assistente Polkit** (`usr/lib/big-screen-monitor-display/bsm-helper`): só
  aceita operações validadas; executar outra coisa como root é crítico.
- **Displays Android pela rede**: TLS na porta 7717 e descoberta na UDP 7718, só
  com "Conectar pela rede" ligado. Parear sem o QR Code, ler a tela de outro
  usuário ou mandar toque/comandos sem pareamento está no escopo.
- **Clientes de aparelho** (`device-clients/`): a bridge do Palm só aceita o Palm
  pareado e só executa os comandos de mídia/volume da lista.

Arquitetura e decisões: [docs/04-seguranca-permissoes.md](docs/04-seguranca-permissoes.md)
e [docs/android/09-seguranca.md](docs/android/09-seguranca.md).
