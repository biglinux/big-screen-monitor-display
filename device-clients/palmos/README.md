# ZireMon — Monitor de Sistema para Palm OS 5

Cliente nativo Palm OS 5 (`320x320` Hi-Res, testado no Palm Zire 72) que exibe a
telemetria do **Big Screen Monitor Display** (`bsmd`) via **Bluetooth SPP**:
CPU, GPU, RAM, disco, rede e a música tocando, com histórico de 48 amostras,
4 temas e controle de mídia pelo toque.

## Estrutura
- `palm/`: código C, recursos `.rcp`, `Makefile` e o `ZireMon.prc` já compilado.
- `pc/bsmd_palm_bridge.py`: bridge Bluetooth que coleta a telemetria com
  `bsmd.telemetry` (a mesma do serviço) e a música com `playerctl`.
- `pc/send_prc.py`: instala o `.prc` no Palm por Bluetooth OBEX (`obexd`).
- `pc/palm_bt.py`: detecta o Palm pareado no BlueZ (usado pelos dois scripts).

## Requisitos no PC
`python-dbus`, `python-gobject`, `bluez` e `bluez-obex` (para o `send_prc`),
`playerctl` (música e botões de mídia) e `pactl` ou `wpctl` (volume). A bridge
usa o `bsmd` do repositório ou o instalado em `/usr/share/big-screen-monitor-display`.

## Uso rápido

### 1. Parear
Pareie o Palm no Bluetooth do sistema. Com um único Palm pareado (nome com
Palm, Zire, Tungsten, Treo…), os scripts o encontram sozinhos; senão, informe o MAC.

### 2. Instalar o app no Palm
O `ZireMon.prc` já vem compilado. A partir de `device-clients/palmos`:
```bash
python3 pc/send_prc.py palm/ZireMon.prc           # ou: --mac AA:BB:CC:DD:EE:FF
```
(equivale a `make -C palm send`, que também não recompila). Aceite o
recebimento na tela do Palm. Para recompilar (`make -C palm`) é preciso o
prc-tools com o SDK 5r4; informe o local com `make -C palm TOOLCHAIN=/caminho`.

### 3. Iniciar a bridge
Também a partir de `device-clients/palmos`:
```bash
python3 pc/bsmd_palm_bridge.py                 # conecta no Palm (ZireMon escutando)
python3 pc/bsmd_palm_bridge.py --target AA:BB:CC:DD:EE:FF
python3 pc/bsmd_palm_bridge.py --target listen  # o Palm conecta: Menu -> Connection -> Connect BT
                                                # (só aceita o Palm pareado)
python3 pc/bsmd_palm_bridge.py --stdout         # só mostra os pacotes, sem Bluetooth
```
Outras opções: `--interval 2` (segundos entre envios), `--gpu 1` (qual GPU
mostrar; o padrão é a de mais VRAM, a dedicada).

## No Palm
- Ao abrir, o ZireMon fica escutando ("WAIT PC") até a bridge conectar.
- Toque no nome **ZireMon** (canto superior esquerdo) para trocar o tema:
  Slate, Matrix, Classic e Cyber.
- Toque no restante do cabeçalho, ou use o direcional esquerda/direita, para
  trocar de tela: painel, histórico (últimas 48 amostras ≈ 48 s) e mídia.
- Na tela de mídia: anterior, tocar/pausar, próxima e volume −/+.

## Protocolo
Uma linha por segundo, em cp1252 (Palm Latin), no máximo 255 bytes:

```
M|cpu%|cpuT|MHz|gpu%|gpuT|ram%|ramUsadaG|ramTotalG|disco%|rxMbps|txMbps|host|mídia\n
```

O Palm responde com `CMD|PLAY_PAUSE`, `CMD|NEXT`, `CMD|PREV`, `CMD|VOL_UP` ou
`CMD|VOL_DOWN` (um por linha); qualquer outra coisa é ignorada. Os testes em
`tests/test_palmos.py` compilam o parser C do Palm no host e conferem que ele
aceita todo pacote da bridge.
