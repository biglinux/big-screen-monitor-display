/*
 * Host harness for the portable FSP core (compiled with the native gcc by
 * tests/test_foston.py). Reads an FSP stream from a file, feeds it to the
 * parser in pseudo-random chunk sizes (as a USB serial port would deliver
 * it), applies RECT/FILL messages to a WxH surface and writes the final
 * RGB565 framebuffer to the output file. A summary line goes to stdout:
 *
 *   messages=N presents=N crc_errors=N dropped=N naks=N last_present=ID
 *
 * Usage: host_decode WIDTH HEIGHT STREAM OUT [bottom-up]
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../src/fsp.h"

int main(int argc, char **argv)
{
    int width, height, bottom_up, messages = 0, presents = 0, naks = 0;
    uint32_t last_present = 0;
    uint16_t *fb;
    uint8_t *stream, *buf, *scratch;
    long size;
    size_t offset = 0;
    unsigned seed = 12345;
    FILE *f;
    fsp_parser parser;
    fsp_surface surface;
    fsp_box dirty = {0, 0, 0, 0};

    if (argc < 5)
        return 2;
    width = atoi(argv[1]);
    height = atoi(argv[2]);
    bottom_up = argc > 5 && !strcmp(argv[5], "bottom-up");
    f = fopen(argv[3], "rb");
    if (!f)
        return 3;
    fseek(f, 0, SEEK_END);
    size = ftell(f);
    fseek(f, 0, SEEK_SET);
    stream = malloc(size ? size : 1);
    if (fread(stream, 1, size, f) != (size_t)size)
        return 4;
    fclose(f);

    fb = calloc((size_t)width * height, 2);
    buf = malloc(FSP_HEADER + FSP_MAX_PAYLOAD);
    scratch = malloc((size_t)width * height * 2);
    fsp_parser_init(&parser, buf, FSP_HEADER + FSP_MAX_PAYLOAD);
    surface.width = width;
    surface.height = height;
    surface.stride = bottom_up ? -width : width;
    surface.pixels = bottom_up ? fb + (size_t)(height - 1) * width : fb;

    while (offset < (size_t)size || parser.used) {
        fsp_msg msg;
        int r;
        size_t chunk;
        seed = seed * 1103515245u + 12345u;
        chunk = 1 + (seed >> 16) % 7000;
        if (chunk > (size_t)size - offset)
            chunk = (size_t)size - offset;
        offset += fsp_feed(&parser, stream + offset, chunk);
        while ((r = fsp_next(&parser, &msg)) != FSP_NEED_MORE) {
            if (r == FSP_BAD_CRC) {
                naks++;
                continue;
            }
            messages++;
            if (msg.type == FSP_RECT || msg.type == FSP_FILL) {
                if (fsp_apply(&surface, msg.type, msg.payload, msg.len, scratch,
                              (size_t)width * height * 2, &dirty))
                    naks++;
            } else if (msg.type == FSP_PRESENT && msg.len >= 4) {
                presents++;
                last_present = fsp_get32(msg.payload);
            }
            fsp_consume(&parser);
        }
        if (offset >= (size_t)size && parser.used < FSP_HEADER)
            break;
        if (offset >= (size_t)size && parser.used) {
            /* truncated tail: nothing more will come */
            break;
        }
    }

    f = fopen(argv[4], "wb");
    if (!f)
        return 5;
    fwrite(fb, 2, (size_t)width * height, f);   /* host is little endian like the device */
    fclose(f);
    printf("messages=%d presents=%d crc_errors=%u dropped=%u naks=%d last_present=%u\n",
           messages, presents, parser.crc_errors, parser.dropped, naks, last_present);
    return 0;
}
