# FOSTON FS-707DC — investigação do hardware, USB e firmware

Unidade analisada em 18/11/2026, conectada ao hub USB `5-1.4` do computador de
desenvolvimento (BigLinux/Manjaro, kernel 6.18). Tudo abaixo foi **observado no
aparelho**, salvo quando marcado como "fonte externa".

## 1. Identificação

| Item | Valor observado | Como |
|---|---|---|
| SoC | MediaTek **MT3351** | `ID_REVISION=3351` no INQUIRY SCSI (udev) |
| Sistema | **Windows CE 5.0.1400** | `GetVersionEx` pelo cliente bsmd-ce |
| Plataforma / OEM | `APOLLO` / `MTK` | `SystemParametersInfo(SPI_GETPLATFORMTYPE / SPI_GETOEMINFO)` |
| RAM | 120 668 KB total, ~97–100 MB livres com o cliente | `GlobalMemoryStatus` |
| Tela | 800 × 480, 16 bpp | `GetSystemMetrics`, DIB 565 criada pelo cliente |
| Toque | resistivo, 1 ponto, já calibrado pelo WinCE | eventos reais cobrindo x 1–789, y 1–478 |
| Armazenamento exportado | 2,05 GB FAT32 (`0897-EDDF`) | `lsblk`, kernel |
| Luz de fundo | sem `HKCU\ControlPanel\Backlight\ACBacklightLevel` | cliente: `brightness = not supported` |

Fonte externa (anúncios e fórum, **não confirmado**): ARM 468 MHz, TV digital,
AV-IN, Bluetooth, transmissor FM — [GpsInfo](https://www.gpsinfo.com.br/viewtopic.php?t=3181),
[Zoom](https://www.zoom.com.br/navegador-gps/gps-foston-fs-707dc).
Os anúncios citam 64 MB de RAM; o aparelho reporta ~118 MB.

## 2. Funções USB

O firmware usa a pilha USB Function do Windows CE com os descritores de exemplo da
Microsoft ("PROTOTYPE--Remember to change idVendor"):

| Modo | VID:PID | Classe | Driver Linux | Nó |
|---|---|---|---|---|
| Serial (`Serial_Class`) | `045e:00ce` | vendor, bulk | `ipaq` | `/dev/ttyUSB0` |
| Armazenamento (`Mass_Storage_Class`) | `045e:ffff` | 08/06/50 BOT | `usb-storage` | `/dev/sdf` |

* Ao ligar, o aparelho enumera como **serial por ~21 s** e o shell troca para
  armazenamento (log do kernel, 13:58:28 → 13:58:49).
* Número de série no modo armazenamento: `A4E7EDDA-E575-4252-9D6B-4195D48BB863`;
  no modo serial não há número de série.
* Controlador USB Function: `$bus\BuiltIn_-1_26_0`, chave `Drivers\BuiltIn\UsbFn`.
* A porta serial do lado do aparelho é **COM6:** (`Drivers\Active` → `Serial_Class=COM6:`).
* `IOCTL_UFN_GET_CURRENT_CLIENT` e `IOCTL_UFN_CHANGE_CURRENT_CLIENT` funcionam;
  `IOCTL_UFN_ENUMERATE_AVAILABLE_CLIENTS` responde erro 87 (parâmetro inválido).
* O driver `ipaq` não implementa `TIOCMGET` (ler CTS dá `ENOTTY`).
* O kernel registra falhas de `ATA PASS-THROUGH(16)` e "Synchronize Cache failed"
  no modo armazenamento — inofensivas (o firmware não implementa esses comandos).

## 3. Firmware e software

* Navegação original: iGO 8 (`IGO8.exe`, build 8.3.2.92992 de 2009) — logs de crash
  em `7 pole 2012/crash.txt` citam `\SDMMC\iGO82\`.
* `SHELL.INI` aponta `\ResidentFlash\IGO\IGOPNA.exe` (pasta inexistente no volume).
* O menu do aparelho tem **Configurações → caminho da navegação**: o botão
  "Navegação" executa o `.exe` escolhido. É assim que o cliente roda,
  **sem modificar ROM, bootloader nem registro persistente**.
* O `coredll` deste firmware **não exporta `_vsnwprintf`**: um executável que o
  importe não carrega (falha silenciosa ao tocar em Navegação; visto com a 1.0.1).
* `DrawText` não aceita `DT_END_ELLIPSIS` (nada é desenhado).
* O volume fica montado **nos dois lados** durante o modo armazenamento: o WinCE
  mantém cache próprio; arquivos copiados pelo PC só são vistos corretamente após
  **reset** do aparelho. Gravações do aparelho nesse estado não chegaram ao PC.

## 4. Backup

| Item | Estado |
|---|---|
| Arquivos do volume (2 090) | `foston-monitor/backup/2026-11-18-volume/volume-files.tar` + `files.sha256` |
| Hash do tar | `49fc9c68874c59429f07c9bc1f0f235f9e10a623ae08edda71d63fc91e7ae799` |
| Imagem bruta de `/dev/sdf` | **não feita** (exige root): `sudo dd if=/dev/sdf of=foston-sdf.img bs=4M status=progress && sha256sum foston-sdf.img` |
| ROM/NAND interna | não acessível sem desmontagem; não foi necessária |

Nenhuma escrita persistente fora de `BigScreen\` no volume e da opção
"caminho da navegação" (alterada pelo usuário no menu, reversível pelo mesmo menu).

## 5. Pesquisa externa

* Troca dinâmica de função USB no WinCE: [Nicolas Besson](http://nicolasbesson.blogspot.com/2009/11/usb-function-profile-switcher.html),
  [PrabuKumar](https://prabukumar.wordpress.com/2008/10/07/usb-function-driver-dynamic-switching-in-wince/);
  valores dos IOCTL conferidos no [SDK Meizu M8 (usbfnioctl.h)](https://docs.huihoo.com/meizu/m8sdk/0.9.6.0/usbfnioctl_8h.html).
* Compilador: [CeGCC 0.59.1](https://sourceforge.net/projects/cegcc/files/cegcc/0.59.1/)
  (precisa de GMP 4.3.2 / MPFR 2.4.2 de 32 bits — compilados em prefixo privado).
* O fórum GpsInfo alerta que **firmwares de modelos parecidos (FS-707DT, yg918d) podem
  inutilizar o aparelho**: nenhum firmware foi gravado.
