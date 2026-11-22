# bsmd-ce: Windows CE (ARM) client of Big Screen Monitor Display.
#
# Toolchain: CeGCC arm-mingw32ce (https://cegcc.sourceforge.net, 0.59.1 or the
# GCC 4.6+/9.x builds of github.com/MaxKellermann/cegcc-build).
#   make CROSS=/opt/mingw32ce/bin/arm-mingw32ce-
# Host test of the portable core (no cross compiler needed):
#   make host-test

CROSS ?= arm-mingw32ce-
CC = $(CROSS)gcc
STRIP = $(CROSS)strip
CFLAGS ?= -O2 -Wall -Wextra -Wno-unused-parameter
# ARMv5TE (ARM926EJ-S in the MediaTek MT3351); Thumb is not used, the GDI calls dominate anyway.
ARCH_FLAGS ?= -march=armv5te -mtune=arm926ej-s
DEFS = -DUNICODE -D_UNICODE -D_WIN32_WCE=0x0500
LIBS = -lcoredll

SRC = src/main.c src/fsp.c
OUT = build/bsmd-ce.exe

all: $(OUT)

$(OUT): $(SRC) src/fsp.h src/splash_data.h
	mkdir -p build
	$(CC) $(CFLAGS) $(ARCH_FLAGS) $(DEFS) -o $@ $(SRC) $(LIBS)
	$(STRIP) $@

build/host_decode: tests/host_decode.c src/fsp.c src/fsp.h
	mkdir -p build
	cc -O2 -Wall -Wextra -std=c99 -o $@ tests/host_decode.c src/fsp.c

host-test: build/host_decode

clean:
	rm -rf build

.PHONY: all clean host-test

# Copy the built client to where the package ships it (the GUI installs it on the device from there).
PACKAGED = ../../usr/share/big-screen-monitor-display/device-clients/wince
package: $(OUT)
	install -m644 $(OUT) $(PACKAGED)/bsmd-ce.exe
	cd $(PACKAGED) && sha256sum bsmd-ce.exe > bsmd-ce.exe.sha256

.PHONY: package

# Regenerate the waiting-screen artwork (needs Pillow, rsvg-convert, Adwaita icons).
splash:
	python3 tools/make_splash.py

.PHONY: splash
