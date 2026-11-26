# PLANNING.md — Roteiro a partir da 5.5.2

Análise completa do projeto feita em 26/11/2026, sobre a `main` em `8c2362a`
(PR #20). O roteiro anterior (3.x → 4.0) foi concluído e está no fim deste
arquivo, como histórico.

Cada etapa traz **o quê**, **por quê** e **como saber que terminou**. A ordem é
a de prioridade: as primeiras fases são baratas e protegem o que já existe; as
últimas são investimento.

## Status da execução (26/11/2026)

| Etapa | Status | Onde |
| --- | --- | --- |
| 0.1 Confirmar de onde o pacote é compilado | ⏳ **com você**: instalar o pacote do repositório BigLinux numa VM e ver `--version` | — |
| 0.2 Webhook falha de verdade (`curl -fsS`) | ✅ | PR #21 |
| 0.3 Pacote só com Tests verde na `main` | ✅ | PR #21 |
| 0.4 Release v5.5.2 | ✅ tag na `main` de 25/11 (a 5.5.2 do CHANGELOG) | — |
| 0.5 Uma fonte da versão (`test_version.py`, `tools/release.sh`) | ✅ | PR #21 |
| 1.1 Issues ativas com formulários, rótulo `hardware`, relato privado de vulnerabilidade | ✅ | PR #22 e configuração do repositório |
| 1.2 "Relatar um problema" na janela (28 idiomas) | ✅ | PR #22 |
| 1.3 `CHANGELOG.md`, README mais curto | ✅ | PR #22 |
| 1.4 `README.en.md` | ✅ | PR #22 |
| 1.5 `CONTRIBUTING.md`, `SECURITY.md` | ✅ | PR #22 |
| 2.1 "—" quando a GPU não mede o uso | ✅ todos os temas | PR #23 |
| 2.2 NVIDIA pela NVML | ✅ ⏳ falta validar numa NVIDIA real | PR #23 |
| 2.3 Intel: frequência | ✅ | PR #23 |
| 2.4 Nome "RX 580" errado | ✅ | PR #23 |
| 3.1 CI com Python 3.10, 3.12 e 3.14 | ✅ | PR #24 |
| 3.2 `ruff` no CI, 110 avisos → 0 | ✅ | PR #24 |
| 3.3 Cobertura com piso | ✅ subprocessos agora medidos (worker do SmartMonitor 0→80 %, miniaturas 0→88 %); `sdnotify` 100 %; piso 68 % no CI | PR #24 / #26 / acessibilidade |
| 3.4 Instalação em Debian, Ubuntu, Fedora, openSUSE, Arch | ✅ workflow *Install* | PR #24 |
| 4 Arquivos grandes | ✅ como regra no CONTRIBUTING (dividir só ao mexer) | PR #25 |
| 5.1 AUR (`-git`) | ✅ PKGBUILD gerado e compilado; ⏳ **com você**: publicar exige a sua conta no AUR | PR #25 |
| 5.2 `.deb`/`.rpm` no Open Build Service | ⏳ **com você**: exige conta no OBS; o workflow *Install* já cobre as 5 distros | — |
| 5.3 Página de compatibilidade | ✅ gerada do registro de drivers | PR #25 |
| 6.1 Protocolo BSMD-lite e bridge genérica | ✅ | PR #26 |
| 6.2 Exemplo para ESP32 | ⏳ precisa de hardware para validar; o cliente de referência em Python existe | — |
| 7.1 Teste com o Orca | ✅ parte automática: 9 botões só de ícone sem nome acessível corrigidos (o Orca lia só "botão") e um teste impede novos; ⏳ **com você**: percorrer a janela com o Orca | PR acessibilidade |
| 7.2 Primeiro uso guiado | ✅ procurar de novo · celular/tablet · "meu modelo não está na lista" | PR #27 |
| 7.3 Índice da documentação | ✅ `docs/README.md`, com teste de links | PR #27 |

---

## Diagnóstico em uma página

### O que está forte (não mexer sem motivo)

- **Engenharia do serviço**: `systemd` com `Type=notify`, watchdog que só pinga
  quando telemetria, desenho e transporte avançam, `DynamicUser`, `DevicePolicy`
  fechada, filtro de syscalls e rede restrita a faixas privadas. Poucos projetos
  desktop chegam a esse nível.
- **Testes**: 1581 testes, CI com PyQt5 e PyQt6, `ResourceWarning` tratado como
  erro, emuladores de protocolo e clientes C testados no host.
- **Código limpo**: o `ruff` (E, F, W, B) acha 113 avisos em ~53 mil linhas,
  quase todos cosméticos.
- **Traduções**: 28 idiomas, todos com 1732/1732 mensagens.
- **Documentação técnica**: 87 arquivos `.md` com decisões, medições e bugs.

### Para onde você não está olhando

1. **A entrega até o usuário.** O código está na 5.5.2, mas a última release
   publicada é a 5.5.1. O PKGBUILD compila de `github.com/biglinux/...`, que está
   parado desde 10/11 (`3d1dcfa`), enquanto todo o trabalho entra em
   `ruscher/...`. O workflow que pede o pacote ao BigLinux sempre fica verde porque
   o `curl` não usa `--fail`. Hoje **não há prova de que o usuário do BigLinux
   recebe a 5.5.x**.
2. **O pacote não espera os testes.** "Translate and Build Package" dispara em
   push de **qualquer branch** e em paralelo com os testes. Um push com teste
   quebrado ainda pede o build.
3. **Não há canal com quem usa.** As issues estão desativadas no GitHub. Um
   projeto que vive de compatibilidade de hardware (dezenas de painéis, coolers,
   celulares) não tem como receber "o meu modelo X não funciona".
4. **GPU só funciona de verdade em AMD.** O uso vem de `gpu_busy_percent`, que só
   o `amdgpu` expõe. NVIDIA (driver proprietário) e Intel mostram **0 %**, e a
   temperatura da NVIDIA também falta. O número aparece como se fosse real.
5. **O projeto depende de uma pessoa.** São 169 de 186 commits de um autor, e
   não há `CONTRIBUTING.md` nem `SECURITY.md`. O README está só em português,
   embora o app fale 28 idiomas.

---

## Fase 0 — Garantir que a entrega chega (1 a 3 dias)

### 0.1 Confirmar de onde o pacote é compilado
- **O quê:** descobrir se o build do BigLinux usa o `url` do webhook
  (`ruscher/...`) ou o `source=` do PKGBUILD (`biglinux/...`). Instalar o pacote
  do repositório do BigLinux numa VM e rodar `big-screen-monitor-display --version`.
- **Por quê:** se a resposta for `biglinux/`, nada desde 10/11 (Android, 28
  idiomas, Tailscale, ZireMon) chegou aos usuários.
- **Pronto quando:** o pacote do repositório mostra `5.5.2`. Se não mostrar,
  sincronize o `biglinux/` (PR ou push) ou aponte o PKGBUILD para o repositório
  certo.

### 0.2 Fazer o webhook falhar de verdade
- **O quê:** usar `curl -fsS` nos dois `curl` de
  `.github/workflows/translate-and-build-package.yml`.
- **Por quê:** hoje um token expirado ou um 404 aparece como "success".
- **Pronto quando:** um token inválido deixa o job vermelho.

### 0.3 Só pedir pacote com testes verdes e na `main`
- **O quê:** trocar `branches: ["*"]` por `main` e fazer o build depender dos
  testes (`workflow_run` do "Tests" com `conclusion == success`, ou juntar os dois
  num workflow com `needs:`).
- **Por quê:** evita publicar pacote de branch de trabalho ou com regressão.
- **Pronto quando:** um push numa branch qualquer não dispara o build, e um teste
  quebrado na `main` também não.

### 0.4 Publicar a release v5.5.2
- **O quê:** criar a tag `v5.5.2` e a release com o APK assinado.
- **Por quê:** o README anuncia a 5.5.2 e o QR de pareamento aponta para a
  release; quem baixa recebe a 5.5.1.
- **Pronto quando:** `gh release list` mostra a v5.5.2 como *Latest*.

### 0.5 Uma só fonte da versão
- **O quê:** um script de release (`tools/release.sh`) que confere se
  `bsmd/__init__.py`, `android/app/build.gradle.kts` (`versionName`/`versionCode`),
  o README e a tag dizem a mesma versão, e cria a tag. Um teste pode fazer a mesma
  conferência no CI.
- **Por quê:** hoje são 3 a 4 lugares editados à mão, e a 0.4 mostra que um deles
  já ficou para trás.

---

## Fase 1 — Abrir o canal com os usuários (1 semana)

### 1.1 Ativar as issues, com formulários
- **O quê:** ativar as issues e criar `.github/ISSUE_TEMPLATE/` com três
  formulários:
  - **Hardware não reconhecido**: pede `lsusb`, modelo e o relatório que a janela
    já gera em Diagnóstico.
  - **Bug**: pede versão, distro, passos e o relatório de diagnóstico.
  - **Pedido de recurso.**
- **Por quê:** o relatório de diagnóstico já existe (`config_gui.py`, botão de
  copiar). Falta para onde mandá-lo. Cada issue de hardware vira um teste e uma
  linha na tabela de compatibilidade.
- **Pronto quando:** uma issue de teste aberta pelo formulário traz o relatório
  completo.

### 1.2 Atalho "Relatar problema" na janela
- **O quê:** em Diagnóstico, um botão que copia o relatório e abre a página de
  nova issue já com o formulário certo.
- **Por quê:** o usuário leigo não vai procurar o GitHub sozinho.

### 1.3 `CHANGELOG.md` e um README mais curto
- **O quê:** levar as seções "Novidades da x.y" (linhas 48–239 do README) para um
  `CHANGELOG.md`. O README fica com: o que é, o que suporta, como instalar, como
  usar e links.
- **Por quê:** são 903 linhas. Quem chega pelo GitHub precisa passar por 200
  linhas de histórico antes de achar "Instalação".

### 1.4 README em inglês
- **O quê:** um `README.en.md` com o essencial (o que é, hardware suportado,
  instalação) e um link no topo de cada README para o outro.
- **Por quê:** é o que leva o projeto para fora do Brasil: donos de AX206 e
  Turing estão no mundo todo, e o app já fala 28 idiomas.

### 1.5 `CONTRIBUTING.md` e `SECURITY.md`
- **O quê:**
  - `CONTRIBUTING.md`: como rodar (`run-local.sh`, `pytest`), o padrão de commit,
    "drivers novos vêm com emulador e teste", e o fluxo de PR que já funcionou
    com o #11 e o #19.
  - `SECURITY.md`: como relatar uma vulnerabilidade em particular. O serviço
    escuta na rede (Android, TLS na porta 7717), então isso é necessário.
- **Por quê:** o Marcos já mandou dois PRs grandes. Com regras escritas, o
  terceiro chega pronto.

---

## Fase 2 — Telemetria honesta para todas as GPUs (2 a 3 semanas)

### 2.1 "—" quando o valor não existe
- **O quê:** `_empty_gpu` passa a usar `percent: None`, e os temas, o
  SmartMonitor e os clientes (Android, WinCE, Palm) mostram "—" para `None`.
- **Por quê:** o projeto já segue essa regra para a temperatura ("sem sensor →
  —"). Um 0 % falso numa NVIDIA a 100 % passa a impressão de que o monitor está
  quebrado.
- **Pronto quando:** um teste com uma GPU sem `gpu_busy_percent` mostra "—" em
  todos os temas.

### 2.2 NVIDIA via NVML
- **O quê:** ler `libnvidia-ml.so.1` por `ctypes` (sem dependência nova):
  - `nvmlDeviceGetUtilizationRates`, `GetTemperature`, `GetMemoryInfo`,
    `GetPowerUsage` e `GetClockInfo`;
  - casar com o `card*` do DRM pelo PCI bus id;
  - no `.service`: `DeviceAllow=/dev/nvidiactl rw`, `/dev/nvidia0 rw` (e
    `char-nvidia-frontend`). Hoje o `DevicePolicy=closed` bloqueia.
- **Por quê:** é a GPU da maioria dos gamers, o público natural de um monitor de
  hardware. `nvidia-smi` a cada segundo custa caro (~30 ms e um processo). A NVML
  em processo custa microssegundos.
- **Pronto quando:** uma máquina com NVIDIA mostra uso, temperatura e VRAM; sem
  driver, cai para "—" sem erro.

### 2.3 Intel
- **O quê:** frequência atual/máxima (`gt/gt0/rps_act_freq_mhz` no i915,
  `device/tile0/gt0/freq0/act_freq` no xe) e temperatura pelo hwmon do pacote. O
  uso fica "—".
- **Por quê:** o uso em % na Intel exige PMU (`CAP_PERFMON`) ou ler o `fdinfo` de
  outros processos. As duas coisas contrariam o sandbox, e não vale abrir o
  sandbox por isso.

### 2.4 Corrigir o nome de reserva
- **O quê:** `find_gpus` chama `1002:7590` de "RX 580", mas o RX 580 é o
  `1002:67df`. Remover o caso especial e deixar "AMD Radeon".

---

## Fase 3 — Qualidade contínua no CI (1 semana, depois é automático)

### 3.1 Python mínimo e atual
- **O quê:** matriz de CI com Python **3.10** (o mínimo do PKGBUILD; Ubuntu
  22.04) e **3.14** (Arch/BigLinux hoje), além do 3.12.
- **Por quê:** o CI roda só no 3.12, e o `pytest.ini` já mostra mudanças do 3.14
  afetando o PyGObject. Uma sintaxe nova escapa para o 3.10 sem ninguém ver.

### 3.2 `ruff` no CI
- **O quê:** um `ruff.toml` com `select = E, F, W, B` e `line-length = 120`, e o
  passo `ruff check` no CI. Antes, zerar os avisos atuais:
  - `B905` (`zip` sem `strict`): 29;
  - `B904` (`raise` sem `from`): 28;
  - `F811`: as funções `register_object` e `unix_signal_add` estão **definidas
    duas vezes** em `bsmd/media/agent.py` (linhas 34 e 44, repetidas em 52 e 59),
    sobra de merge.
- **Por quê:** o PLANNING antigo diz que o código novo passa no ruff, mas nada
  garante isso.

### 3.3 Cobertura medida
- **O quê:** `pytest --cov` no CI, com o relatório publicado e um piso que só
  sobe. Ver a seção [Cobertura](#cobertura-medida-em-26112026).
- **Por quê:** 1581 testes não dizem *onde* falta teste.

### 3.4 Instalação testada nas distros
- **O quê:** um job em container (`fedora`, `debian`, `opensuse/tumbleweed`) que
  roda `install-system.sh --dry-run` ou instala de fato e confere os arquivos.
- **Por quê:** o `install-system.sh` atende quatro famílias de distro, mas só é
  testado de verdade quando alguém reclama. Foi assim com o `psutil` no openSUSE
  (PR #11).

---

## Fase 4 — Arquitetura: dividir os arquivos gigantes sob demanda (contínuo)

Regra: **só divida um arquivo quando for mexer nele** por outro motivo, num PR
só de movimentação (sem mudar comportamento), com os testes verdes antes e
depois.

| Arquivo | Linhas | Sugestão de corte |
| --- | --- | --- |
| `bsmd/displays/smartmonitor/capture.py` | 1767 | captura × codificação × agendamento |
| `bsmd/runtime.py` | 1602 | ciclo do display (`DisplayWorker`) × orquestração × `status.json` |
| `bsmd/legacy_themes.py` | 1593 | um módulo por tema (Padrão, GKrellM, Planet, Computador Antigo) |
| `config_gui.py` | 1395 | uma página por arquivo, como `displays_page.py` e `kojiro_page.py` já fazem |
| `kojiro_page.py` | 1389 | idem |

**Por quê:** arquivos acima de ~800 linhas são onde contribuidores externos
desistem e onde os conflitos de merge acontecem. Reescrever tudo de uma vez seria
arriscado demais para um ganho que não aparece para o usuário.

---

## Fase 5 — Distribuição além do BigLinux (1 a 2 meses)

### 5.1 AUR
- **O quê:** publicar o PKGBUILD no AUR (`big-screen-monitor-display` ou `-git`).
- **Por quê:** donos de Arch, Manjaro e EndeavourOS procuram lá primeiro. Custa
  quase nada, porque o PKGBUILD já existe.

### 5.2 Pacotes `.deb` e `.rpm` pelo Open Build Service
- **O quê:** um projeto no OBS (build.opensuse.org) que gera pacotes para Debian,
  Ubuntu, Fedora e openSUSE a partir do mesmo repositório.
- **Por quê:** o `install-system.sh` funciona, mas não recebe atualizações. Um
  repositório de pacotes recebe pelo gerenciador da distro.
- **Fora de escopo:** Flatpak e Snap. O serviço precisa de `systemd` do sistema,
  `udev` e acesso direto a USB/hidraw, coisas que o sandbox deles não permite.

### 5.3 Página de compatibilidade
- **O quê:** um `docs/compatibilidade.md` (ou GitHub Pages) gerado do registro de
  drivers (`bsmd/displays/registry`): modelo, VID:PID, recursos (touch, sensores,
  LEDs) e status (testado no aparelho / só emulador / relatado por usuário).
- **Por quê:** é a primeira pergunta de quem tem um painel na mão. As issues da
  Fase 1 alimentam essa página.

---

## Fase 6 — Clientes de aparelho como plataforma (quando houver demanda)

### 6.1 Protocolo leve documentado
- **O quê:** o ZireMon (Palm) e o WinCE já usam pacotes simples. Formalizar um
  protocolo de texto versionado ("BSMD-lite": `M|v1|campo=valor|…` sobre serial,
  Bluetooth SPP ou TCP) com uma bridge genérica no serviço, em vez de uma bridge
  por aparelho.
- **Por quê:** o próximo contribuidor vai querer ESP32, Arduino com TFT, Kindle
  ou Raspberry Pi. Com o protocolo pronto, isso vira um projeto de fim de semana
  e não um fork da telemetria. A bridge do Palm já reimplementava a leitura de
  GPU (e errou as chaves, PR #20). Esse é o sintoma.
- **Pronto quando:** a bridge do Palm passa a ser um adaptador de 50 linhas sobre
  a bridge genérica.

### 6.2 Exemplo de referência para ESP32
- **O quê:** um cliente mínimo em `device-clients/esp32/` (ESP32 + TFT barato,
  ~R$ 60) falando BSMD-lite por USB serial ou Wi-Fi.
- **Por quê:** é o hardware que a comunidade *maker* já tem em casa.

---

## Fase 7 — Experiência e acessibilidade (contínuo)

### 7.1 Teste real com o Orca
- **O quê:** está pendente desde a 4.0 (ver o histórico abaixo). Percorrer a
  janela inteira só com teclado e Orca e registrar o resultado em `docs/`.
- **Por quê:** os rótulos existem, mas nunca foram ouvidos.

### 7.2 Primeiro uso guiado
- **O quê:** quando o serviço não acha nenhum display, a janela abre num
  assistente: "conecte o painel", "use o celular (QR)" ou "meu modelo não está
  na lista" (que leva à issue da Fase 1).
- **Por quê:** o caso mais comum de abandono é "instalei, não aconteceu nada".

### 7.3 Índice da documentação
- **O quê:** um `docs/README.md` que separe o guia do usuário dos relatórios
  técnicos e marque os relatórios históricos (00–22, auditorias e relatórios
  finais de cada fase) como arquivo.
- **Por quê:** são 87 arquivos em duas numerações misturadas com pastas por
  tema, e quem chega não sabe por onde começar.

---

## Resumo das prioridades

| Fase | Esforço | Impacto | Por que agora |
| --- | --- | --- | --- |
| 0 — Entrega | dias | **crítico** | sem isso, nada do resto chega ao usuário |
| 1 — Canal com usuários | 1 semana | alto | hardware novo só aparece se alguém puder relatar |
| 2 — GPU honesta | 2–3 semanas | alto | NVIDIA é a GPU mais comum do público-alvo |
| 3 — CI | 1 semana | médio | protege as fases seguintes |
| 4 — Arquitetura | contínuo | médio | facilita contribuidores |
| 5 — Distribuição | 1–2 meses | alto | leva o projeto para fora do BigLinux |
| 6 — Plataforma de clientes | sob demanda | médio | cresce com a comunidade *maker* |
| 7 — UX/acessibilidade | contínuo | médio | reduz o abandono no primeiro uso |

---

## Cobertura (medida em 26/11/2026)

Medida com `pytest --cov` (1581 testes passaram). O total é **71 %** (33 297
comandos, 9 807 sem teste). Código executado em subprocessos não entra na conta.

**O núcleo está bem coberto:** `settings` 94 %, `health` 95 %, `touch` 92 %,
drivers FOSTON e SmartMonitor 90–92 %, `runtime` 85 %, hub Android 86 % e
`telemetry` 74 %. A telemetria é o ponto fraco do núcleo e é onde a Fase 2 vai
mexer, então a cobertura dela deve subir junto.

**Lacunas que importam:**

| Arquivo | Cobertura | Por que importa |
| --- | --- | --- |
| `bsmd/sdnotify.py` | 0 % | é o que fala com o watchdog do `systemd`; um erro aqui reinicia o serviço a cada 30 s. Um teste com um socket `AF_UNIX` falso (`NOTIFY_SOCKET`) resolve |
| `main.py` | 0 % | argumentos de linha de comando e a entrada do serviço |
| `media_player_page.py` | 0 % | a página inteira do Big Media Player na janela |
| `config_gui.py`, `kojiro_page.py`, `displays_page.py`, `gui/*` | 11–14 % | a interface que o usuário vê. O `tests/gui_driver.py` já existe; dá para estender o mesmo padrão |
| `smartmonitor/worker.py`, `traykit/launch.py`, `traykit/thumbs.py` | 0 % | o processo da captura do SmartMonitor e a inicialização das bandejas |

**Meta sugerida:** piso de 71 % no CI agora, subindo 2 pontos por versão. Testes
de `sdnotify` e `main.py` primeiro, porque são baratos e protegem o serviço.

---

## Histórico — roteiro 3.x, concluído na 4.0

| Item do roteiro 3.x | Status 4.0 |
| --- | --- |
| Criar suíte de testes | ✅ 191 testes em `tests/` + CI (`.github/workflows/tests.yml`); 1581 na 5.5.2 |
| `subprocess.run` bloqueando a GTK | ✅ operações administrativas e diagnóstico em threads |
| `sensors` a cada segundo | ✅ sensor da CPU lido direto no sysfs (o `powerprofilesctl` a cada 0,4 s também saiu) |
| Toasts × HIG | ℹ️ revisto: *toasts* são o padrão recomendado pela HIG do GNOME/libadwaita para retorno passageiro; erros usam diálogos |
| Lock em `SYSTEM_STATS` | ✅ coleta em `bsmd/telemetry.py` com `STATS_LOCK` e `snapshot()` |
| `except:` nus | ✅ removidos (`except Exception` com contagem de erros por coletor) |
| `lspci` sem timeout | ✅ lista de argumentos, sem shell, timeout de 3 s, executado uma vez |
| Imports não usados / `ruff` | ✅ código novo passa no `ruff` (E, F, W, B); ⏳ ainda fora do CI (Fase 3.2) |
| `Image.ANTIALIAS` | ✅ não usado |
| Confirmação em "Restaurar padrões" | ✅ diálogo; nada muda no display até "Aplicar" |
| Rótulos acessíveis (Orca) | ✅ definidos; ⏳ teste real com Orca pendente (Fase 7.1) |
| Cache de SVG | ✅ cache positivo e negativo (não chama `rsvg-convert` a cada quadro) |
| Separar o monitor em módulo próprio | ✅ `bsmd/` (telemetria, drivers, runtime, temas, saúde) |
