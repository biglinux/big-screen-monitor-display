# Como contribuir

Obrigado por querer ajudar! *English speakers: issues and PRs in English are
welcome too.*

## Formas de ajudar (da mais fácil para a mais trabalhosa)

1. **Testar um display nível B.** A maioria dos drivers está implementada e
   conferida contra a referência, mas ninguém confirmou no aparelho. Se você tem
   um, abra uma issue com o formulário **Hardware**. Um relato confirmando que
   funciona vale tanto quanto um PR.
2. **Relatar bugs** com o relatório de diagnóstico (*Diagnóstico › Relatar um
   problema*, na janela).
3. **Traduções**: veja [docs/i18n.md](docs/i18n.md).
4. **Código**: temas, drivers, clientes de aparelho (`device-clients/`).

## Rodando a partir do código

```bash
./install-system.sh --print-deps    # pacotes que faltam neste sistema
./run-local.sh config               # janela de configuração
./run-local.sh --simulate 480x320 --snapshot /tmp/frame.png   # sem hardware
QT_QPA_PLATFORM=offscreen python -m pytest -q tests
```

O serviço instalado e o `run-local.sh` não disputam o mesmo display: pare o
serviço (`sudo systemctl stop big-screen-monitor-display`) antes de testar um
painel com o código local.

## Regras para um PR ser aceito

- **Testes verdes** (`pytest`) e, para código novo, `ruff check` sem avisos
  (configuração em `ruff.toml`). O CI roda os dois.
- **Driver novo vem com emulador e teste.** Veja `bsmd/displays/foston/emulator.py`
  e `tests/test_foston.py`: o protocolo é testado byte a byte sem o aparelho. No
  PR, diga se você testou no hardware (nível A) ou só no emulador (nível B).
- **Texto novo na interface passa pelo gettext** (`_()`), seguido de
  `tools/update-pot.sh`. O teste `tests/test_i18n_catalogs.py` exige os 28
  catálogos completos. Se você não traduz, diga no PR e as traduções entram
  antes do merge.
- **Sem número falso.** Um sensor que não existe aparece como "—", nunca como 0.
- **O serviço continua sem root e isolado.** Mudanças em
  `usr/lib/systemd/system/*.service`, nas regras udev ou no `bsm-helper` precisam
  explicar no PR por que a permissão é necessária.
- **Commits** curtos, em português ou inglês, no formato `área: o que mudou`
  (`palmos: …`, `janela: …`, `pacote: …`).

## Como os PRs são integrados

Os commits do PR entram como estão (autoria preservada). Se a revisão achar
problemas, as correções vêm num PR seguinte e ficam registradas em
`docs/NN-integracao-prXX.md` (exemplos: [PR #11](docs/22-integracao-pr11.md),
[PR #19](docs/23-integracao-pr19-palmos.md)).

## Publicando uma versão (mantenedores)

1. Atualize a versão em `bsmd/__init__.py`, `android/app/build.gradle.kts`
   (`versionName` e `versionCode = maior*10000 + menor*100 + correção`) e o selo
   do README. Mova a seção `## [Não lançado]` do `CHANGELOG.md` para
   `## [x.y.z]`. O `tests/test_version.py` confere tudo isso.
2. Faça o merge na `main` e espere o *Tests* ficar verde.
3. Rode `tools/release.sh` (ou `--dry-run` para só conferir). Ele envia a tag
   `vx.y.z`; o workflow *Android app* compila o APK e publica a release, e o
   *Translate and Build Package* pede o pacote ao BigLinux depois dos testes.

## Segurança

Vulnerabilidades: veja [SECURITY.md](SECURITY.md). Nunca numa issue pública.
