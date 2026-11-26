/*
 * FSP - Foston Screen Protocol, version 1.
 *
 * Shared by the Windows CE client (this directory) and the host driver
 * (usr/share/big-screen-monitor-display/bsmd/displays/foston/protocol.py).
 * Both sides must agree byte for byte; tests/test_foston.py compiles the
 * portable decoder of this directory with the host compiler and feeds it
 * streams produced by the Python encoder.
 *
 * Every message: 16-byte header + payload, all integers little endian.
 *
 *   0  u8   'F'
 *   1  u8   'S'
 *   2  u8   version (1)
 *   3  u8   type
 *   4  u16  sequence
 *   6  u16  flags (reserved, 0)
 *   8  u32  payload length (<= FSP_MAX_PAYLOAD)
 *  12  u16  CRC-16/CCITT-FALSE of the payload
 *  14  u16  CRC-16/CCITT-FALSE of bytes 0..13
 *
 * The header CRC lets a receiver resynchronise after garbage by scanning
 * for the next "FS" whose header checks out.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef FSP_H
#define FSP_H

#include <stddef.h>
#include <stdint.h>

#define FSP_MAGIC0 0x46
#define FSP_MAGIC1 0x53
#define FSP_VERSION 1
#define FSP_HEADER 16
#define FSP_MAX_PAYLOAD (1024u * 1024u)

/* host -> device */
#define FSP_HELLO       0x01   /* u16 proto, u16 flags, utf-8 host name */
#define FSP_PING        0x02   /* u32 token */
#define FSP_RECT        0x10   /* u16 x,y,w,h; u8 encoding; u8 0; u16 0; data */
#define FSP_FILL        0x11   /* u16 x,y,w,h; u16 rgb565 */
#define FSP_PRESENT     0x12   /* u32 frame id: show everything received since the last one */
#define FSP_BRIGHTNESS  0x20   /* u8 percent */
#define FSP_CALIBRATE   0x21   /* run the system touch calibration */
#define FSP_BYE         0x22   /* u8 mode: 0 = wait for the host, 1 = quit the client */
#define FSP_TOUCHCFG    0x23   /* u8 enabled, u8 move interval in ms (0 = default) */

/* device -> host */
#define FSP_HELLO_ACK   0x81   /* see fsp_hello_ack layout in main.c / protocol.py */
#define FSP_PRESENTED   0x82   /* u32 frame id, u32 decode ms, u32 blit ms */
#define FSP_PONG        0x83   /* u32 token, u32 device tick */
#define FSP_NAK         0x84   /* u16 sequence, u8 reason */
#define FSP_CREDIT      0x85   /* u32 bytes of whole messages handled since HELLO (flow control) */
#define FSP_TOUCH       0x90   /* u8 kind, u8 0, u16 x, u16 y, u16 0, u32 tick */
#define FSP_KEY         0x91   /* u16 virtual key, u8 down */
#define FSP_LOG         0xA0   /* utf-8 text */

/* FSP_RECT encodings */
#define FSP_ENC_RAW     0      /* w*h RGB565 little endian */
#define FSP_ENC_RLE     1      /* tokens: u16 n; n & 0x8000 -> run of (n & 0x7fff) + 1 copies of one
                                  pixel, else n + 1 literal pixels */
#define FSP_ENC_DEFLATE 2      /* zlib stream (RFC 1950) of the raw encoding */

/* touch kinds */
#define FSP_TOUCH_DOWN  1
#define FSP_TOUCH_MOVE  2
#define FSP_TOUCH_UP    3

/* NAK reasons */
#define FSP_NAK_CRC      1
#define FSP_NAK_TOO_BIG  2
#define FSP_NAK_BAD_RECT 3
#define FSP_NAK_DECODE   4
#define FSP_NAK_UNKNOWN  5
#define FSP_NAK_RESYNC   6     /* a partial message stalled and was discarded */

static inline uint16_t fsp_get16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static inline uint32_t fsp_get32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static inline void fsp_put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static inline void fsp_put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

uint16_t fsp_crc16(const uint8_t *data, size_t len);

/* Build a header for a payload; returns FSP_HEADER. */
size_t fsp_header(uint8_t *out, uint8_t type, uint16_t seq, const uint8_t *payload, uint32_t len);

/* Incremental parser. Feed bytes; complete, verified messages are returned. */
typedef struct {
    uint8_t *buf;          /* capacity FSP_HEADER + FSP_MAX_PAYLOAD */
    size_t used;
    size_t cap;
    uint32_t dropped;      /* bytes skipped while resynchronising */
    uint32_t crc_errors;
} fsp_parser;

typedef struct {
    uint8_t type;
    uint16_t seq;
    const uint8_t *payload;
    uint32_t len;
} fsp_msg;

/* Result of fsp_next */
#define FSP_NEED_MORE 0
#define FSP_GOT_MSG   1
#define FSP_BAD_CRC   2    /* payload CRC mismatch: msg.seq/type filled, message skipped */

void fsp_parser_init(fsp_parser *p, uint8_t *buf, size_t cap);
/* Append up to len bytes; returns how many were taken (the rest must be fed again). */
size_t fsp_feed(fsp_parser *p, const uint8_t *data, size_t len);
/* Extract the next message. The payload pointer is valid until fsp_consume. */
int fsp_next(fsp_parser *p, fsp_msg *msg);
void fsp_consume(fsp_parser *p);

/* ---- framebuffer decoding (portable, no Windows dependencies) ---- */

typedef struct {
    uint16_t *pixels;      /* first pixel of row 0 */
    int width, height;
    int stride;            /* in pixels, negative for bottom-up DIBs */
} fsp_surface;

typedef struct {
    int x0, y0, x1, y1;    /* exclusive end; empty when x1 <= x0 */
} fsp_box;

void fsp_box_add(fsp_box *box, int x, int y, int w, int h);

/* Decode a FSP_RECT or FSP_FILL payload into the surface. Returns 0 or a NAK reason.
 * scratch must hold w*h*2 bytes for DEFLATE (max width*height*2). */
int fsp_apply(fsp_surface *s, uint8_t type, const uint8_t *payload, uint32_t len,
              uint8_t *scratch, size_t scratch_len, fsp_box *dirty);

/* zlib (RFC 1950/1951) decompression into a fixed buffer. Returns bytes written or -1. */
long fsp_inflate(const uint8_t *src, size_t src_len, uint8_t *dst, size_t dst_len);

#endif
