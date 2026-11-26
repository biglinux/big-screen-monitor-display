# BSMD-lite — telemetria para displays caseiros

Uma linha de texto por segundo com CPU, GPU, RAM, disco, rede e a música tocando,
por **serial** (ESP32/Arduino no USB), **TCP** (Raspberry Pi, outro computador) ou
no terminal. Especificação: [docs/25-protocolo-bsmd-lite.md](../../docs/25-protocolo-bsmd-lite.md).

```bash
python3 bsmd_lite_bridge.py --stdout                    # ver as linhas
python3 bsmd_lite_bridge.py --serial /dev/ttyUSB0       # microcontrolador no USB
python3 bsmd_lite_bridge.py --tcp 7720 --bind 0.0.0.0   # aceitar clientes da rede
python3 lite_client.py 192.168.0.10 7720                # painel no terminal (cliente de referência)
```

Requisitos: o Big Screen Monitor Display (o `bsmd` do repositório ou o instalado),
`python-pyserial` para `--serial` e `playerctl` para a música e os botões de mídia.
