# Sobrescreva com: make TOOLCHAIN=/caminho/do/prc-tools
TOOLCHAIN ?= $(HOME)/.local/share/palmos-toolchain
BIN := $(TOOLCHAIN)/usr/bin
export GCC_EXEC_PREFIX := $(TOOLCHAIN)/usr/lib/gcc-lib/
export PATH := $(BIN):$(TOOLCHAIN)/usr/m68k-palmos/bin:$(PATH)
SDK ?= $(TOOLCHAIN)/palm-os-sdk/sdk-5r4

CC := $(BIN)/m68k-palmos-gcc
BUILD_PRC := $(BIN)/build-prc
PILRC := $(BIN)/pilrc

APP := ZireMon
CREATOR := ZMon
TYPE := appl

CFLAGS := -O2 -Wall -Wno-multichar \
	-B$(TOOLCHAIN)/usr/lib/gcc-lib/m68k-palmos/2.95.3-kgpd/ \
	-B$(TOOLCHAIN)/usr/m68k-palmos/bin/ \
	-B$(TOOLCHAIN)/usr/m68k-palmos/lib/ \
	-I$(TOOLCHAIN)/usr/m68k-palmos/include \
	-I$(SDK)/include \
	-I$(SDK)/include/Core \
	-I$(SDK)/include/Core/Hardware \
	-I$(SDK)/include/Core/System \
	-I$(SDK)/include/Core/UI \
	-I$(SDK)/include/Dynamic \
	-I$(SDK)/include/Extensions/Bluetooth \
	-I$(SDK)/include/Extensions/ExpansionMgr \
	-I$(SDK)/include/Libraries \
	-I$(TOOLCHAIN)/palm-os-sdk/sdk-5r3/include/Core/System

LDFLAGS := -L$(TOOLCHAIN)/usr/m68k-palmos/lib -L$(TOOLCHAIN)/usr/lib/gcc-lib/m68k-palmos/2.95.3-kgpd

all: $(APP).prc

%.o: %.c ziremon_res.h
	$(CC) $(CFLAGS) -c $< -o $@

ziremon: ziremon.o
	$(CC) $(CFLAGS) $(LDFLAGS) $^ -o $@

# o pilrc gera vários *.bin (um por recurso): um carimbo marca quando estão em dia
resources.stamp: ziremon.rcp ziremon_res.h
	rm -f *.bin
	$(PILRC) -q ziremon.rcp .
	touch $@

$(APP).prc: ziremon resources.stamp
	$(BUILD_PRC) -o $(APP).prc -n "$(APP)" -c $(CREATOR) -t $(TYPE) ziremon *.bin

# make send            -> detecta o Palm pareado
# make send MAC=AA:..  -> envia para esse endereço
send: $(APP).prc
	python3 ../pc/send_prc.py $(APP).prc $(if $(MAC),--mac $(MAC))

# não apaga o ZireMon.prc versionado: use "make distclean" para isso
clean:
	rm -f *.o *.bin ziremon resources.stamp

distclean: clean
	rm -f $(APP).prc

.PHONY: all send clean distclean
