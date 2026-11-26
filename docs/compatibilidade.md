# Compatibilidade de hardware

<!-- Gerado por tools/make_compat.py a partir de bsmd/displays/registry.py. Não edite à mão. -->

Cada família lista os identificadores USB que o serviço reconhece. A detecção só
lê o `sysfs`; nada é enviado a um aparelho antes de você escolher o modelo.

| Nível | Significado |
| --- | --- |
| **A** | testado no aparelho |
| **B** | implementado, aguardando teste físico |
| **C** | protocolo conhecido, em implementação |
| **D** | em investigação |
| **E** | não suportado |

**Tem um aparelho nível B?** [Conte se funciona](https://github.com/ruscher/big-screen-monitor-display/issues/new?template=1-hardware.yml): um relato confirmando
já promove o driver para A.

| Família | Fabricante | Modelos | IDs USB | Resolução | Transporte | Nível |
| --- | --- | --- | --- | --- | --- | --- |
| **AX206 DPF (AIDA64 / USB-Display)** | Appotech AX206 based frames | AX206 3.5", AX206 5", USB-Display | `1908:0102` | reported by the device (320x240, 480x320, 800x480...) | usb | ✅ A — testado no aparelho |
| **FOSTON FS-707DC (BigFoston OS)** | FOSTON (MediaTek MT3351 navigators with BigFoston OS) | FOSTON FS-707DC 7" (BigFoston OS) | `0525:a4aa` | reported by the device (800x480 on the FS-707DC) | network | ✅ A — testado no aparelho |
| **FOSTON FS-707DC Touch Display** | FOSTON (Windows CE / MediaTek MT3351 navigators) | FOSTON FS-707DC 7" | `045e:00ce` | reported by the device (800x480 on the FS-707DC) | serial | ✅ A — testado no aparelho |
| **SmartMonitor 3.5" (HID, llhmi / llTechCo)** | SmartMonitor (sold under many brands) | 3.5" PC CPU Data Monitor, SmartMonitor 3.5" | `0483:0065` | 480x320 | hid | ✅ A — testado no aparelho |
| **DeepCool AG DIGITAL** | DeepCool | AG400 DIGITAL, AG620 DIGITAL, AG300 DIGITAL, AG500 DIGITAL | `3633:0008` | numeric CPU display | hid | 🧪 B — implementado, aguardando teste físico |
| **DeepCool AK DIGITAL** | DeepCool | AK400 DIGITAL, AK400 DIGITAL SE, AK620 DIGITAL, AK620 DIGITAL SE, AK500 DIGITAL, AK500S DIGITAL, AK500S DIGITAL SE | `3633:0001` `3633:0002` `3633:0003` `3633:0004` | numeric CPU display | hid | 🧪 B — implementado, aguardando teste físico |
| **DeepCool AK400 DIGITAL PRO** | DeepCool | AK400 DIGITAL PRO | `3633:0010` | numeric CPU display | hid | 🧪 B — implementado, aguardando teste físico |
| **DeepCool AK500/AK620 DIGITAL PRO** | DeepCool | AK500 DIGITAL PRO, AK620 DIGITAL PRO | `3633:0011` `3633:0012` | numeric CPU display | hid | 🧪 B — implementado, aguardando teste físico |
| **DeepCool LD240/LD360** | DeepCool | LD240, LD360 | `3633:000a` | numeric CPU display | hid | 🧪 B — implementado, aguardando teste físico |
| **DeepCool LS SE DIGITAL** | DeepCool | LS520 SE DIGITAL, LS720 SE DIGITAL | `3633:0006` | numeric CPU display | hid | 🧪 B — implementado, aguardando teste físico |
| **DeepCool MYSTIQUE 240/360** | DeepCool | MYSTIQUE 240, MYSTIQUE 360 | `3633:0009` | 2.8" LCD, information mode | usb | 🧪 B — implementado, aguardando teste físico |
| **Kipye Qiye Smart Display 3.5"** | Kipye / Qiye | Kipye Qiye Smart Display 3.5" | `454d:4e41` | 320x480 | serial | 🧪 B — implementado, aguardando teste físico |
| **Turing Smart Screen 2.1"/2.8"/5"/8.8" (rev. C)** | Turing / TURZX | Turing 2.1", Turing 2.8", Turing 5", Turing 8.8" (rev. C) | `????:*` `1a86:ca21` `0525:a4a7` `1d6b:0121` `1d6b:0106` | 480x480, 480x800, 480x1920 | serial | 🧪 B — implementado, aguardando teste físico |
| **Turing Smart Screen 3.5" / UsbPCMonitor** | Turing / TURZX, UsbPCMonitor | Turing 3.5" (rev. A), UsbPCMonitor 3.5", UsbPCMonitor 5", UsbPCMonitor 7" | `1a86:5722` | 320x480, 480x800, 600x1024 | serial | 🧪 B — implementado, aguardando teste físico |
| **Turing Smart Screen USB (2.8" round, 4.6", 5.2", 8", 8.8", 9.2", 12.3")** | Turing / TURZX | Turing 2.8" round, Turing 4.6", Turing 5.2", Turing 8.0", Turing 8.8" (USB), Turing 9.2", Turing 12.3" | `1cbe:0028` `1cbe:0046` `1cbe:0050` `1cbe:0080` `1cbe:0088` `1cbe:0092` `1cbe:0123` | 480x480, 320x960, 720x1280, 800x1280, 480x1920, 462x1920, 720x1920 | usb | 🧪 B — implementado, aguardando teste físico |
| **WeAct Studio Display FS V1 0.96"** | WeAct Studio | WeAct Display FS V1 0.96" | `1a86:fe0c` | 80x160 | serial | 🧪 B — implementado, aguardando teste físico |
| **WeAct Studio Display FS V1 3.5"** | WeAct Studio | WeAct Display FS V1 3.5" | `1a86:fe0c` | 320x480 | serial | 🧪 B — implementado, aguardando teste físico |
| **XuanFang 3.5" rev. B / flagship** | XuanFang | XuanFang 3.5" rev. B, XuanFang 3.5" flagship (RGB LEDs) | `1a86:5722` | 320x480 | serial | 🧪 B — implementado, aguardando teste físico |

Fora do USB: celulares e tablets **Android** (Wi-Fi, cabo USB sem depuração ou
Tailscale) são nível A; os clientes experimentais para aparelhos antigos
(Windows CE, Palm OS 5) ficam em [`device-clients/`](../device-clients/).
