# 04 — Segurança, permissões e configurações

## Antes × depois

| Tema | 3.1.0 | 4.0.0 / 4.1.0 |
| --- | --- | --- |
| Usuário do serviço | `root` | `DynamicUser=yes` (usuário transitório sem privilégios) |
| Acesso aos painéis | udev `MODE="0666"` (qualquer processo local) | `0660`, grupo `big-screen-monitor` + `uaccess`, só para os IDs/seriais das famílias suportadas (4.1: o serviço saiu do grupo `uucp`) |
| Operações administrativas | sudoers `%wheel NOPASSWD` restart/enable/disable | Polkit + helper com verbos fixos (sudoers removido) |
| Configurações | serviço lia o **primeiro** `/home/*` | `/etc/big-screen-monitor-display/settings.json`, fonte única |
| Isolamento | `ProtectSystem=full`, `ProtectHome=read-only` | `ProtectSystem=strict`, `ProtectHome=read-only` (4.2.1; `yes` escondia as partições do `/home`), `DevicePolicy=closed`, filtro de syscalls, sem capabilities |

## Serviço sem root

`DynamicUser=yes` + `SupplementaryGroups=big-screen-monitor`. O grupo
`big-screen-monitor` vem de `usr/lib/sysusers.d/` e a regra udev o aplica
apenas aos nós dos painéis conhecidos (doc 14), inclusive as portas
seriais — por isso o serviço não precisa mais de `uucp` e não alcança
outras portas seriais. Dispositivos permitidos no cgroup: apenas
`char-usb_device`, `char-ttyACM` e `char-ttyUSB`, e mesmo nesses só abre os
nós com o grupo certo. Nada além disso é necessário:
psutil lê `/proc` e `/sys`; o tema GKrellM perde o acesso ao socket do Docker
(antes funcionava por ser root) — o módulo mostra 0 containers. Isso é
intencional: dar acesso ao Docker equivale a dar root.

Validado na máquina real com uma unit de runtime equivalente (veja 09):
`Type=notify`, watchdog, filtro de syscalls e `DevicePolicy=closed`
funcionando com a AX206.

## Polkit no lugar do sudoers

`/usr/lib/big-screen-monitor-display/bsm-helper` (executado via `pkexec`):

| Verbo | Efeito |
| --- | --- |
| `apply-settings` | JSON pela entrada padrão (≤ 64 KiB), validado pelo esquema, gravado atomicamente |
| `service start\|stop\|restart\|enable\|disable` | `systemctl` só para `big-screen-monitor-display.service` (`enable` usa `--now`) |
| `recover` | `systemctl kill --signal=SIGUSR1 --kill-whom=main` |
| `migrate` | importa uma única vez o arquivo antigo por usuário |
| `display-command` | JSON validado (≤ 4 KiB; ações `identify`, `pattern`, `clear_pattern`, `reconnect`) gravado no spool do serviço em execução; recusa link simbólico e cria com `O_EXCL\|O_NOFOLLOW` |

Nenhum argumento chega a um shell; o interpretador roda com `python3 -I`;
`pkexec` limpa o ambiente. A ação `br.com.biglinux.big-screen-monitor-display.manage`
exige `auth_admin_keep`; a regra `50-big-screen-monitor-display.rules` libera
sem senha **apenas** membros de `wheel` em sessão local ativa — o mesmo
alcance do sudoers anterior, mas restrito às operações validadas.

## Fonte única de configurações

- Caminho: `/etc/big-screen-monitor-display/settings.json` (0644, root).
- Validação (`bsmd/settings.py`): tipos, faixas e opções; chaves desconhecidas
  descartadas; valores inválidos voltam ao padrão **e são relatados**; arquivo
  corrompido nunca derruba o serviço.
- Gravação atômica: arquivo temporário + `fsync` + `rename`.
- O serviço detecta mudanças por `stat` a cada 1 s e aplica **sem reiniciar**:
  brilho, tema, orientação, idioma e até o modelo do display (reabre o driver).
- Migração: na instalação/atualização, `bsm-helper migrate` copia o arquivo
  antigo **mais recente** (`~/.config/big-screen-monitor/settings.json` de
  `/root` ou `/home/*`), convertendo valores legados (brilho 1–7, modelo
  "other"). Nunca sobrescreve um arquivo existente.
- Separação: configurações do dispositivo (`model`, `size`, `orientation`,
  `brightness`), da aplicação (tema, Brother Away, overlay, desempenho) e
  administrativas (habilitar/iniciar o serviço, via helper).

## Feedback ao aplicar

A janela grava via helper em segundo plano e mostra um *toast*
("Configurações aplicadas. O display será atualizado em instantes."), ou um
diálogo explicando a falha (autorização negada, helper ausente…). Som curto do
sistema opcional (`ui_sound_feedback`, desligado por padrão).

## Itens verificados

- `udevadm verify` nas regras (passa; o grupo só existe após o sysusers).
- `systemd-sysusers --dry-run` no arquivo de grupo.
- `xmllint` na política Polkit.
- 11 testes do helper: verbos inválidos, JSON inválido, entrada grande,
  somente esta unit, `recover` com SIGUSR1.
- O arquivo sudoers foi removido do pacote; não há regra `NOPASSWD: ALL`.
