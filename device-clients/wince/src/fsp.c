/*
 * FSP portable core: CRC, framing, rectangle decoding and a small inflate.
 *
 * The inflate follows the structure of Mark Adler's public-domain "puff"
 * reference decoder (canonical Huffman decoding, one symbol at a time),
 * written again here for a fixed output buffer. Speed is adequate for
 * dashboard frames on a 468 MHz ARM9.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include <string.h>

#include "fsp.h"

/* ------------------------------------------------------------------ CRC */

static uint16_t crc_table[256];
static int crc_ready;

static void crc_init(void)
{
    int i, b;
    for (i = 0; i < 256; i++) {
        uint16_t c = (uint16_t)(i << 8);
        for (b = 0; b < 8; b++)
            c = (uint16_t)((c & 0x8000) ? (c << 1) ^ 0x1021 : (c << 1));
        crc_table[i] = c;
    }
    crc_ready = 1;
}

uint16_t fsp_crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;
    if (!crc_ready)
        crc_init();
    while (len--)
        crc = (uint16_t)((crc << 8) ^ crc_table[((crc >> 8) ^ *data++) & 0xFF]);
    return crc;
}

size_t fsp_header(uint8_t *out, uint8_t type, uint16_t seq, const uint8_t *payload, uint32_t len)
{
    out[0] = FSP_MAGIC0;
    out[1] = FSP_MAGIC1;
    out[2] = FSP_VERSION;
    out[3] = type;
    fsp_put16(out + 4, seq);
    fsp_put16(out + 6, 0);
    fsp_put32(out + 8, len);
    fsp_put16(out + 12, fsp_crc16(payload, len));
    fsp_put16(out + 14, fsp_crc16(out, 14));
    return FSP_HEADER;
}

/* --------------------------------------------------------------- parser */

void fsp_parser_init(fsp_parser *p, uint8_t *buf, size_t cap)
{
    p->buf = buf;
    p->cap = cap;
    p->used = 0;
    p->dropped = 0;
    p->crc_errors = 0;
}

size_t fsp_feed(fsp_parser *p, const uint8_t *data, size_t len)
{
    size_t room = p->cap - p->used;
    if (len > room)
        len = room;
    memcpy(p->buf + p->used, data, len);
    p->used += len;
    return len;
}

static void drop(fsp_parser *p, size_t n)
{
    if (n >= p->used) {
        p->used = 0;
        return;
    }
    memmove(p->buf, p->buf + n, p->used - n);
    p->used -= n;
}

static int header_ok(const uint8_t *h)
{
    return h[0] == FSP_MAGIC0 && h[1] == FSP_MAGIC1 && h[2] == FSP_VERSION &&
           fsp_get32(h + 8) <= FSP_MAX_PAYLOAD && fsp_get16(h + 14) == fsp_crc16(h, 14);
}

int fsp_next(fsp_parser *p, fsp_msg *msg)
{
    for (;;) {
        size_t i = 0;
        uint32_t len;
        if (p->used < FSP_HEADER) {
            /* keep a possible partial magic at the end */
            while (i < p->used && p->buf[i] != FSP_MAGIC0)
                i++;
            if (i) {
                p->dropped += (uint32_t)i;
                drop(p, i);
            }
            return FSP_NEED_MORE;
        }
        if (!header_ok(p->buf)) {
            /* resynchronise on the next magic byte */
            i = 1;
            while (i < p->used && p->buf[i] != FSP_MAGIC0)
                i++;
            p->dropped += (uint32_t)i;
            drop(p, i);
            continue;
        }
        len = fsp_get32(p->buf + 8);
        if (p->used < FSP_HEADER + len)
            return FSP_NEED_MORE;
        msg->type = p->buf[3];
        msg->seq = fsp_get16(p->buf + 4);
        msg->payload = p->buf + FSP_HEADER;
        msg->len = len;
        if (fsp_get16(p->buf + 12) != fsp_crc16(msg->payload, len)) {
            p->crc_errors++;
            fsp_consume(p);
            msg->payload = NULL;
            msg->len = 0;
            return FSP_BAD_CRC;
        }
        return FSP_GOT_MSG;
    }
}

void fsp_consume(fsp_parser *p)
{
    if (p->used >= FSP_HEADER)
        drop(p, FSP_HEADER + fsp_get32(p->buf + 8));
}

/* ------------------------------------------------------------- surfaces */

void fsp_box_add(fsp_box *box, int x, int y, int w, int h)
{
    if (w <= 0 || h <= 0)
        return;
    if (box->x1 <= box->x0 || box->y1 <= box->y0) {
        box->x0 = x; box->y0 = y; box->x1 = x + w; box->y1 = y + h;
        return;
    }
    if (x < box->x0) box->x0 = x;
    if (y < box->y0) box->y0 = y;
    if (x + w > box->x1) box->x1 = x + w;
    if (y + h > box->y1) box->y1 = y + h;
}

static uint16_t *row(fsp_surface *s, int y)
{
    return s->pixels + (long)y * s->stride;
}

static void put_raw(fsp_surface *s, int x, int y, int w, int h, const uint8_t *src)
{
    int r, c;
    for (r = 0; r < h; r++) {
        uint16_t *d = row(s, y + r) + x;
        for (c = 0; c < w; c++, src += 2)
            d[c] = (uint16_t)(src[0] | (src[1] << 8));
    }
}

static int put_rle(fsp_surface *s, int x, int y, int w, int h, const uint8_t *src, uint32_t len)
{
    const uint8_t *end = src + len;
    long total = (long)w * h, done = 0;
    int cx = 0, cy = 0;
    uint16_t *d = row(s, y) + x;
    while (done < total) {
        uint16_t token, pixel;
        long count;
        int literal;
        if (end - src < 2)
            return FSP_NAK_DECODE;
        token = fsp_get16(src);
        src += 2;
        literal = !(token & 0x8000);
        count = (long)(token & 0x7FFF) + 1;
        if (count > total - done)
            return FSP_NAK_DECODE;
        if (literal ? end - src < count * 2 : end - src < 2)
            return FSP_NAK_DECODE;
        pixel = fsp_get16(src);
        if (!literal)
            src += 2;
        done += count;
        while (count--) {
            if (literal) {
                pixel = fsp_get16(src);
                src += 2;
            }
            d[cx++] = pixel;
            if (cx == w) {
                cx = 0;
                if (++cy < h)
                    d = row(s, y + cy) + x;
            }
        }
    }
    return src == end ? 0 : FSP_NAK_DECODE;
}

int fsp_apply(fsp_surface *s, uint8_t type, const uint8_t *p, uint32_t len,
              uint8_t *scratch, size_t scratch_len, fsp_box *dirty)
{
    int x, y, w, h, result = 0;
    if (len < 10)
        return FSP_NAK_DECODE;
    x = fsp_get16(p); y = fsp_get16(p + 2); w = fsp_get16(p + 4); h = fsp_get16(p + 6);
    if (w <= 0 || h <= 0 || x + w > s->width || y + h > s->height)
        return FSP_NAK_BAD_RECT;
    if (type == FSP_FILL) {
        uint16_t color = fsp_get16(p + 8);
        int r, c;
        for (r = 0; r < h; r++) {
            uint16_t *d = row(s, y + r) + x;
            for (c = 0; c < w; c++)
                d[c] = color;
        }
    } else if (type == FSP_RECT) {
        const uint8_t *data = p + 14;
        uint32_t data_len = len - 14;
        size_t raw = (size_t)w * h * 2;
        if (len < 14)
            return FSP_NAK_DECODE;
        switch (p[8]) {
        case FSP_ENC_RAW:
            if (data_len != raw)
                return FSP_NAK_DECODE;
            put_raw(s, x, y, w, h, data);
            break;
        case FSP_ENC_RLE:
            result = put_rle(s, x, y, w, h, data, data_len);
            break;
        case FSP_ENC_DEFLATE:
            if (raw > scratch_len || fsp_inflate(data, data_len, scratch, raw) != (long)raw)
                return FSP_NAK_DECODE;
            put_raw(s, x, y, w, h, scratch);
            break;
        default:
            return FSP_NAK_DECODE;
        }
    } else {
        return FSP_NAK_UNKNOWN;
    }
    if (!result)
        fsp_box_add(dirty, x, y, w, h);
    return result;
}

/* -------------------------------------------------------------- inflate */

#define MAXBITS 15
#define MAXLCODES 286
#define MAXDCODES 30
#define MAXCODES (MAXLCODES + MAXDCODES)
#define FIXLCODES 288

typedef struct {
    const uint8_t *in;
    size_t inlen, incnt;
    uint8_t *out;
    size_t outlen, outcnt;
    uint32_t bitbuf;
    int bitcnt;
    int error;
} inflate_state;

typedef struct {
    short *count;
    short *symbol;
} huffman;

static int bits(inflate_state *s, int need)
{
    uint32_t val = s->bitbuf;
    while (s->bitcnt < need) {
        if (s->incnt == s->inlen) {
            s->error = 1;
            return 0;
        }
        val |= (uint32_t)s->in[s->incnt++] << s->bitcnt;
        s->bitcnt += 8;
    }
    s->bitbuf = val >> need;
    s->bitcnt -= need;
    return (int)(val & ((1UL << need) - 1));
}

static int stored(inflate_state *s)
{
    unsigned len;
    s->bitbuf = 0;
    s->bitcnt = 0;
    if (s->incnt + 4 > s->inlen)
        return -1;
    len = s->in[s->incnt] | (s->in[s->incnt + 1] << 8);
    if (s->in[s->incnt + 2] != (~len & 0xff) || s->in[s->incnt + 3] != ((~len >> 8) & 0xff))
        return -1;
    s->incnt += 4;
    if (s->incnt + len > s->inlen || s->outcnt + len > s->outlen)
        return -1;
    memcpy(s->out + s->outcnt, s->in + s->incnt, len);
    s->incnt += len;
    s->outcnt += len;
    return 0;
}

static int decode(inflate_state *s, const huffman *h)
{
    int len, code = 0, first = 0, index = 0, count;
    for (len = 1; len <= MAXBITS; len++) {
        code |= bits(s, 1);
        if (s->error)
            return -1;
        count = h->count[len];
        if (code - count < first)
            return h->symbol[index + (code - first)];
        index += count;
        first += count;
        first <<= 1;
        code <<= 1;
    }
    return -1;
}

static int construct(huffman *h, const short *length, int n)
{
    int symbol, len, left;
    short offs[MAXBITS + 1];
    for (len = 0; len <= MAXBITS; len++)
        h->count[len] = 0;
    for (symbol = 0; symbol < n; symbol++)
        h->count[length[symbol]]++;
    if (h->count[0] == n)
        return 0;
    left = 1;
    for (len = 1; len <= MAXBITS; len++) {
        left <<= 1;
        left -= h->count[len];
        if (left < 0)
            return left;
    }
    offs[1] = 0;
    for (len = 1; len < MAXBITS; len++)
        offs[len + 1] = (short)(offs[len] + h->count[len]);
    for (symbol = 0; symbol < n; symbol++)
        if (length[symbol] != 0)
            h->symbol[offs[length[symbol]]++] = (short)symbol;
    return left;
}

static const short lbase[29] = {3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31,
                                35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
static const short lext[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
                               3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
static const short dbase[30] = {1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
                                257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145,
                                8193, 12289, 16385, 24577};
static const short dext[30] = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
                               7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};

static int codes(inflate_state *s, const huffman *lencode, const huffman *distcode)
{
    int symbol, len;
    unsigned dist;
    do {
        symbol = decode(s, lencode);
        if (symbol < 0)
            return -1;
        if (symbol < 256) {
            if (s->outcnt == s->outlen)
                return -1;
            s->out[s->outcnt++] = (uint8_t)symbol;
        } else if (symbol > 256) {
            symbol -= 257;
            if (symbol >= 29)
                return -1;
            len = lbase[symbol] + bits(s, lext[symbol]);
            symbol = decode(s, distcode);
            if (symbol < 0 || symbol >= 30)
                return -1;
            dist = (unsigned)(dbase[symbol] + bits(s, dext[symbol]));
            if (s->error || dist > s->outcnt || s->outcnt + len > s->outlen)
                return -1;
            {
                uint8_t *d = s->out + s->outcnt;
                const uint8_t *from = d - dist;
                s->outcnt += len;
                while (len--)
                    *d++ = *from++;
            }
        }
    } while (symbol != 256);
    return 0;
}

static int fixed(inflate_state *s)
{
    static int virgin = 1;
    static short lencnt[MAXBITS + 1], lensym[FIXLCODES];
    static short distcnt[MAXBITS + 1], distsym[MAXDCODES];
    static huffman lencode, distcode;
    if (virgin) {
        int symbol;
        short lengths[FIXLCODES];
        lencode.count = lencnt; lencode.symbol = lensym;
        distcode.count = distcnt; distcode.symbol = distsym;
        for (symbol = 0; symbol < 144; symbol++) lengths[symbol] = 8;
        for (; symbol < 256; symbol++) lengths[symbol] = 9;
        for (; symbol < 280; symbol++) lengths[symbol] = 7;
        for (; symbol < FIXLCODES; symbol++) lengths[symbol] = 8;
        construct(&lencode, lengths, FIXLCODES);
        for (symbol = 0; symbol < MAXDCODES; symbol++) lengths[symbol] = 5;
        construct(&distcode, lengths, MAXDCODES);
        virgin = 0;
    }
    return codes(s, &lencode, &distcode);
}

static int dynamic(inflate_state *s)
{
    int nlen, ndist, ncode, index, err;
    short lengths[MAXCODES];
    short lencnt[MAXBITS + 1], lensym[MAXLCODES];
    short distcnt[MAXBITS + 1], distsym[MAXDCODES];
    huffman lencode, distcode;
    static const short order[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
    lencode.count = lencnt; lencode.symbol = lensym;
    distcode.count = distcnt; distcode.symbol = distsym;
    nlen = bits(s, 5) + 257;
    ndist = bits(s, 5) + 1;
    ncode = bits(s, 4) + 4;
    if (s->error || nlen > MAXLCODES || ndist > MAXDCODES)
        return -1;
    for (index = 0; index < ncode; index++)
        lengths[order[index]] = (short)bits(s, 3);
    for (; index < 19; index++)
        lengths[order[index]] = 0;
    if (s->error || construct(&lencode, lengths, 19) != 0)
        return -1;
    index = 0;
    while (index < nlen + ndist) {
        int symbol = decode(s, &lencode), len;
        if (symbol < 0)
            return -1;
        if (symbol < 16) {
            lengths[index++] = (short)symbol;
        } else {
            len = 0;
            if (symbol == 16) {
                if (index == 0)
                    return -1;
                len = lengths[index - 1];
                symbol = 3 + bits(s, 2);
            } else if (symbol == 17) {
                symbol = 3 + bits(s, 3);
            } else {
                symbol = 11 + bits(s, 7);
            }
            if (s->error || index + symbol > nlen + ndist)
                return -1;
            while (symbol--)
                lengths[index++] = (short)len;
        }
    }
    if (lengths[256] == 0)
        return -1;
    err = construct(&lencode, lengths, nlen);
    if (err && (err < 0 || nlen != lencode.count[0] + lencode.count[1]))
        return -1;
    err = construct(&distcode, lengths + nlen, ndist);
    if (err && (err < 0 || ndist != distcode.count[0] + distcode.count[1]))
        return -1;
    return codes(s, &lencode, &distcode);
}

long fsp_inflate(const uint8_t *src, size_t src_len, uint8_t *dst, size_t dst_len)
{
    inflate_state s;
    int last, type, err;
    /* zlib header: CM 8, no preset dictionary, check bits */
    if (src_len < 6 || (src[0] & 0x0F) != 8 || (src[1] & 0x20) || ((src[0] << 8) | src[1]) % 31)
        return -1;
    s.in = src + 2;
    s.inlen = src_len - 6;      /* trailing Adler-32 is not verified: the frame CRC covers it */
    s.incnt = 0;
    s.out = dst;
    s.outlen = dst_len;
    s.outcnt = 0;
    s.bitbuf = 0;
    s.bitcnt = 0;
    s.error = 0;
    do {
        last = bits(&s, 1);
        type = bits(&s, 2);
        if (s.error)
            return -1;
        err = type == 0 ? stored(&s) : type == 1 ? fixed(&s) : type == 2 ? dynamic(&s) : -1;
        if (err || s.error)
            return -1;
    } while (!last);
    return (long)s.outcnt;
}
