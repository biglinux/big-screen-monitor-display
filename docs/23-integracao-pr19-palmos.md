# 23 — Integração do PR #19 (ZireMon, cliente Palm OS 5)

PR: <https://github.com/ruscher/big-screen-monitor-display/pull/19>, de Marcos
Queiroz Gomes (`marquimRcc`), branch `feat/palmos-zire72-client` — 3 commits,
8 arquivos, todos novos em `device-clients/palmos/`: app nativo em C para Palm
OS 5 (`ZireMon.prc`), bridge Bluetooth SPP e instalador OBEX.

Os commits do PR entraram como estão (autoria preservada); as correções vieram
por cima, na branch `fix/palmos-bridge`.

## Impacto no que já existe

Nenhum. `device-clients/` não é empacotado (PKGBUILD e `install-system.sh` não o
tocam), a bridge roda num processo próprio com o seu `telemetry.Collector` e só
lê o `bsmd`. A suíte completa (1581 testes) passou antes e depois da integração.

## Bugs encontrados e corrigidos

| # | Problema no PR | Efeito | Correção |
| --- | --- | --- | --- |
| 1 | GPU lida pelas chaves `usage`/`gpu_percent`; o `bsmd` usa `percent` | GPU sempre 0 % no Palm | `percent` e `temp_value` (com o texto `"56°C"` como reserva) |
| 2 | música lida de `status.json` → `media.title/artist`, que não existem (ali só há diagnóstico do socket) | linha de mídia sempre vazia | `playerctl metadata` com timeout de 1 s, no mesmo thread da coleta |
| 3 | MAC do Palm do autor (`00:07:E0:47:3B:EC`) como padrão na bridge e no `send_prc` | para qualquer outro usuário, tentativas eternas num aparelho que não existe | detecção do Palm pareado no BlueZ (`palm_bt.py`); com nenhum ou vários, erro listando os pareados |
| 4 | `active_gpu_idx` usado indiretamente; o `bsmd` alterna a GPU ativa a cada 3 s | em máquinas com iGPU + dGPU, o histórico "GPU" misturaria as duas | GPU fixa: a de mais VRAM, ou `--gpu N` |
| 5 | modo `--target listen` não lia os comandos do Palm | botões de mídia mortos nesse modo | um só `serve_socket` para os dois modos, com leitura de comandos |
| 6 | bloco `_connect_loop`/`Role=client` inalcançável (o modo cliente retorna antes) | código morto, confuso | removido; o perfil BlueZ é sempre `server` |
| 7 | pacote em ASCII com `errors="replace"` | "Canção" chegava como "Can??o" | cp1252 (Palm Latin), cortado por bytes no tamanho dos campos do Palm |
| 8 | host e mídia só tinham `|` trocado | `\t`/controles chegavam ao Palm | caracteres não imprimíveis viram espaço |
| 9 | `send_prc` registrava o sinal de progresso depois do `SendFile` e só removia a sessão OBEX no caminho feliz | "complete" rápido perdido; sessões órfãs no `obexd` | sinal antes, `RemoveSession` em `finally`, timeout de 120 s com mensagem clara |
| 10 | `Makefile`: alvo `ziremon.bin` nunca é gerado (o pilrc gera `tFRM*.bin` etc.) e toolchain fixo em `~/.local` | `pilrc` e `build-prc` refeitos a todo `make`; impossível usar outro caminho | carimbo `resources.stamp`, `TOOLCHAIN ?=`, `make send MAC=…`; `clean` não apaga o `.prc` versionado (`distclean` apaga) |
| 11 | `dbus`/`gi` importados no topo da bridge | `--stdout` (modo teste) exigia D-Bus | importados só no modo `listen` |
| 12 | `Popen` sem espera para playerctl/pactl | processos zumbis até o próximo `Popen` | `subprocess.run` com timeout de 3 s; volume com `pactl` ou `wpctl -l 1.0` |
| 13 | artefatos de build fora do `.gitignore` | `*.o`, `*.bin` e `ziremon` iriam parar num commit | entradas no `.gitignore` |

## O que ficou como está

- **Código C e `ZireMon.prc`**: o `.prc` versionado foi gerado a partir do
  `ziremon.c` do último commit do PR (6296 → 10121 bytes no mesmo commit que
  trouxe os temas). Sem o prc-tools aqui, mudar o C deixaria binário e fonte fora
  de sincronia, então o protocolo foi mantido e o lado do PC se adaptou a ele.
- Observações para uma próxima versão do app (nenhuma afeta o uso hoje):
  `PrefGetAppPreferences` não confere a versão devolvida (preferências de uma
  versão antiga com outro layout seriam lidas como estão); `ParseIntSimple` em
  `Int16` estoura acima de 32767 (só a rede em Mbps chegaria perto, e o valor é
  limitado na barra); `AppStop` redesenha a tela ao desconectar, já saindo.

## Testes novos (`tests/test_palmos.py`, 15 testes)

- Layout do pacote (14 campos), escolha de GPU, temperatura pelo texto, snapshot vazio.
- Campos de texto não quebram o protocolo (`|`, `\n`, emoji, 300 caracteres) e cabem no buffer de 256 bytes do Palm.
- Música via `playerctl` falso (com player, sem player, sem o programa).
- Comandos do Palm: mídia, volume com `pactl` e com `wpctl`, ação desconhecida não executa nada.
- Parser SDP do canal RFCOMM e detecção do Palm pareado.
- **Parser do Palm de verdade**: `ParseTelemetryLine` é extraído do `ziremon.c` e
  compilado com o gcc do host sobre um shim das APIs do Palm OS; aceita o pacote
  normal e o pior caso, recusa lixo.

## Validação manual

- `bsmd_palm_bridge.py --stdout` numa máquina com iGPU + dGPU: GPU dedicada
  estável (34 %, 56 °C), `--gpu 1` mostra a integrada, música com acentos.
- Sem Palm pareado: a bridge sai na hora com a lista de pareados em vez de ficar
  tentando um MAC alheio.
- Bluetooth com o Zire 72 real não pôde ser testado aqui (o autor testou o
  fluxo com o aparelho); o caminho de rede não mudou de protocolo.
