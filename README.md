# Big Screen Monitor Display

<p align="center">
  <img src="big-screen-monitor-display/usr/share/icons/hicolor/scalable/apps/big-screen-monitor-display.svg" width="128" alt="Big Screen Monitor Display"/>
</p>

<p align="center">
  <b>Dashboard de monitoramento de hardware moderno para displays USB LCD AX206</b>
</p>

---

## 📖 Sobre

O **Big Screen Monitor Display** é um aplicativo que transforma seu display USB LCD AX206 (como QTKeJi.Ltd USB-Display) em um painel de monitoramento de hardware em tempo real, similar ao AIDA64 SensorPanel.

### ✨ Funcionalidades

- 🎨 Interface moderna com tema escuro e ícones SVG
- 🔥 Monitoramento de CPU (uso % + temperatura com cores dinâmicas)
- 🧠 Monitoramento de RAM e SWAP
- 💾 Monitoramento de espaço em disco
- 🎮 Suporte a múltiplas GPUs (AMD/Intel/NVIDIA) com alternância automática
- 📊 Gráfico de linha com histórico de CPU, RAM e Temperatura
- 📋 Top 10 processos (CPU + Memória)
- 🌐 Velocidade de rede (RX/TX em Mbps)
- 🎥 Monitoramento de Encode/Decode da GPU (VCN)
- 🔄 Detecção automática de resolução do display

## 🔧 Instalação

### Arch Linux / BigLinux (via makepkg)

```bash
cd pkgbuild
makepkg -si
```

### Manual

```bash
sudo cp -r big-screen-monitor-display/usr/ /
sudo systemctl enable --now big-screen-monitor-display.service
```

## 📦 Dependências

- `python` >= 3.10
- `python-pillow`
- `python-psutil`
- `python-pyusb`
- `librsvg` (para conversão dos ícones SVG)
- `lm_sensors` (para leitura de temperaturas)

## 🖥️ Dispositivos Compatíveis

| Dispositivo | VID:PID | Status |
|---|---|---|
| QTKeJi.Ltd USB-Display | `1908:0102` | ✅ Suportado |
| GEMBIRD Digital Photo Frame (AX206) | `1908:0102` | ✅ Suportado |

## ⚙️ Uso

### Via systemd (recomendado)

```bash
# Iniciar o serviço
sudo systemctl start big-screen-monitor-display.service

# Habilitar no boot
sudo systemctl enable big-screen-monitor-display.service

# Ver status
sudo systemctl status big-screen-monitor-display.service
```

### Manual

```bash
sudo python3 /usr/share/big-screen-monitor-display/main.py
```

## 🏗️ Estrutura do Projeto

```
big-screen-monitor-display/
├── usr/
│   ├── bin/
│   │   └── big-screen-monitor-display.sh
│   ├── lib/
│   │   └── systemd/system/
│   │       └── big-screen-monitor-display.service
│   └── share/
│       ├── applications/
│       │   └── big-screen-monitor-display.desktop
│       ├── big-screen-monitor-display/
│       │   ├── main.py
│       │   └── img/
│       └── icons/
│           └── hicolor/scalable/apps/
│               └── big-screen-monitor-display.svg
├── pkgbuild/
│   ├── PKGBUILD
│   └── pkgbuild.install
├── .gitignore
└── README.md
```

## 📄 Licença

GPL-3.0

## 👤 Autor

BigLinux Team
