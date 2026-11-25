# ZireMon — Monitor de Sistema para Palm Zire 72

Cliente nativo Palm OS 5 (`320x320` Hi-Res) que exibe telemetria em tempo real do **Big Screen Monitor Display** (`bsmd`) via **Bluetooth SPP**.

## Estrutura
- `pc/bsmd_palm_bridge.py`: Servidor Bluetooth SPP (BlueZ) que coleta telemetria via `bsmd.telemetry` e envia pacotes compactos para o Palm.
- `pc/send_prc.py`: Envia o `.prc` compilado diretamente para o Palm Zire 72 via Bluetooth OBEX (`obexd`).
- `palm/`: Código-fonte C, recursos `.rcp` e `Makefile` para compilar `ZireMon.prc`.

## Uso rápido

### 1. Compilar o app do Palm
```bash
cd palm
make
```

### 2. Enviar o `ZireMon.prc` para o Zire 72 via Bluetooth
```bash
cd palm
make send
```
*(Aceite o recebimento na tela do Palm Zire 72.)*

### 3. Iniciar a bridge no PC
```bash
python3 pc/bsmd_palm_bridge.py
```
No Palm, abra o **ZireMon**, toque na tela (ou use `Menu -> Connection -> Connect BT`), selecione o PC na lista Bluetooth (primeira vez) e acompanhe CPU, GPU, RAM, Disco, Rede e Mídia em tempo real.
