# Instalação e uso

## 1. No computador

O pacote instala a regra udev (só `045e:00ce` com a string de produto deste
firmware; `uaccess` + grupo `big-screen-monitor`; ModemManager ignora a porta).
Em desenvolvimento, sem o pacote novo:

```bash
sudo install -m644 foston-monitor/udev/70-bsmd-foston-dev.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger --action=add --subsystem-match=tty
```

## 2. Copiar o cliente para o navegador

1. Conecte o FOSTON pelo USB (ele aparece como armazenamento).
2. Na janela: **Meus Displays → FOSTON → Instalar o cliente no navegador**
   (ou copie `/usr/share/big-screen-monitor-display/device-clients/wince/bsmd-ce.exe`
   para a pasta `BigScreen` do volume).
3. Ejete o volume, desconecte o cabo e **dê reset no FOSTON** (o WinCE guarda em
   cache a versão anterior dos arquivos).

## 3. No navegador (uma vez)

**Configurações → Caminho da navegação → BigScreen → bsmd-ce.exe.**
A partir daí o botão **Navegação** abre o Big Screen. O canto superior direito
mostra a versão (ex.: `bsmd-ce 1.1.0`).

## 4. Usar

Com o Big Screen aberto, conecte o cabo. O cliente troca a função USB para
serial sozinho; o serviço detecta `usb-<porta>` e começa a desenhar em ~1 s.

Sair: botão **Sair** na tela de espera, ou segurar o canto superior esquerdo por
3 s. Ao sair, o cliente devolve o modo armazenamento.

## Compilar o cliente

```bash
cd device-clients/wince
make host-test                                   # núcleo portátil, sem compilador cruzado
LD_LIBRARY_PATH=<deps32>/lib make CROSS=/opt/mingw32ce/bin/arm-mingw32ce-
make package CROSS=...                           # atualiza o binário empacotado + SHA-256
make splash                                      # regera a arte da tela de espera (src/splash_data.h)
```

CeGCC 0.59.1 (2009) precisa de `libgmp.so.3` e `libmpfr.so.1` de 32 bits:
GMP 4.3.2 e MPFR 2.4.2 compilam com `ABI=32 CFLAGS="-m32 -std=gnu89 ..."` num
prefixo privado. Toolchains mais novos (cegcc-build, GCC 9) também servem.
**Não use** `_vsnwprintf` nem `DT_END_ELLIPSIS` (ausentes neste WinCE).
