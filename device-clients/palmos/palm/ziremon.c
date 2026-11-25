#include <PalmOS.h>
#include <SerialMgr.h>
#include <BtLib.h>
#include <BtCommVdrv.h>

#include "ziremon_res.h"

#define APP_CREATOR     'ZMon'
#define PREF_ID         1
#define PREF_VERSION    2

#define RX_BUF_SIZE     256
#define LINE_BUF_SIZE   256
#define HIST_LEN        48
#define NUM_THEMES      4
#define NUM_SCREENS     3

typedef struct {
    UInt8 r, g, b;
} RGB;

typedef struct {
    const Char *name;
    RGB bg, header, card, track;
    RGB text, muted;
    RGB cpu, gpu, ram, disk, net;
    RGB badge, badgeText;
} Theme;

static const Theme gThemes[NUM_THEMES] = {
    { /* 0: Dark Slate */
        "Slate",
        {15,20,30}, {20,28,42}, {24,33,48}, {35,45,62},
        {248,250,252}, {148,163,184},
        {56,189,248}, {167,139,250}, {52,211,153}, {251,191,36}, {125,211,252},
        {16,185,129}, {15,20,30}
    },
    { /* 1: Matrix */
        "Matrix",
        {5,10,5}, {9,20,9}, {12,26,12}, {19,42,19},
        {220,252,231}, {74,222,128},
        {34,197,94}, {22,163,74}, {74,222,128}, {134,239,172}, {34,197,94},
        {34,197,94}, {5,10,5}
    },
    { /* 2: Palm Classic */
        "Classic",
        {198,212,184}, {181,196,166}, {185,200,170}, {158,173,143},
        {30,41,24}, {59,74,50},
        {30,41,24}, {45,59,36}, {30,41,24}, {59,74,50}, {30,41,24},
        {30,41,24}, {198,212,184}
    },
    { /* 3: Cyberpunk */
        "Cyber",
        {18,10,24}, {27,15,36}, {32,16,43}, {50,26,66},
        {253,244,255}, {216,180,254},
        {236,72,153}, {245,158,11}, {34,211,238}, {244,63,94}, {232,121,249},
        {245,158,11}, {18,10,24}
    }
};

typedef struct {
    Boolean valid;
    Char cpuPct[8];
    Char cpuTemp[8];
    Char cpuMhz[8];
    Char gpuPct[8];
    Char gpuTemp[8];
    Char ramPct[8];
    Char ramUsed[8];
    Char ramTotal[8];
    Char diskPct[8];
    Char netRx[10];
    Char netTx[10];
    Char host[24];
    Char media[52];
    Int16 cpuVal;
    Int16 gpuVal;
    Int16 ramVal;
    Int16 diskVal;
    Int16 netVal;
} TelemetryData;

typedef struct {
    Boolean hasAddr;
    BtLibDeviceAddressType addr;
    UInt8 themeIdx;
    UInt8 screenIdx;
} AppPrefs;

static UInt16 gPortId = 0;
static Boolean gConnected = false;
static Boolean gListening = false;
static Boolean gHiRes = false;
static Char gStatusMsg[48] = "Listening BT SPP...";
static Char gLineBuf[LINE_BUF_SIZE];
static UInt16 gLinePos = 0;
static TelemetryData gData;
static AppPrefs gPrefs;

static UInt8 gHistCpu[HIST_LEN];
static UInt8 gHistGpu[HIST_LEN];
static UInt8 gHistNet[HIST_LEN];

/* --- Helpers --- */

static Int16 ParseIntSimple(const Char *s) {
    Int16 val = 0;
    Boolean neg = false;
    if (!s || !*s) return 0;
    if (*s == '-') { neg = true; s++; }
    while (*s >= '0' && *s <= '9') {
        val = (val * 10) + (*s - '0');
        s++;
    }
    return neg ? -val : val;
}

static void CopyField(Char *dst, UInt16 dstSize, const Char *src, UInt16 len) {
    UInt16 n = (len < dstSize - 1) ? len : (dstSize - 1);
    if (n > 0) MemMove(dst, src, n);
    dst[n] = '\0';
}

static void PushHist(UInt8 *arr, Int16 val) {
    UInt16 i;
    if (val < 0) val = 0;
    if (val > 100) val = 100;
    for (i = 0; i < HIST_LEN - 1; i++) arr[i] = arr[i + 1];
    arr[HIST_LEN - 1] = (UInt8)val;
}

static UInt8 MaxHist(const UInt8 *arr) {
    UInt8 m = 0;
    UInt16 i;
    for (i = 0; i < HIST_LEN; i++) {
        if (arr[i] > m) m = arr[i];
    }
    return m;
}

static void InitDefaultData(void) {
    MemSet(&gData, sizeof(gData), 0);
    MemSet(gHistCpu, sizeof(gHistCpu), 0);
    MemSet(gHistGpu, sizeof(gHistGpu), 0);
    MemSet(gHistNet, sizeof(gHistNet), 0);
    StrCopy(gData.cpuPct, "0");
    StrCopy(gData.cpuTemp, "--");
    StrCopy(gData.cpuMhz, "0");
    StrCopy(gData.gpuPct, "0");
    StrCopy(gData.gpuTemp, "--");
    StrCopy(gData.ramPct, "0");
    StrCopy(gData.ramUsed, "0.0");
    StrCopy(gData.ramTotal, "0.0");
    StrCopy(gData.diskPct, "0");
    StrCopy(gData.netRx, "0.0");
    StrCopy(gData.netTx, "0.0");
    StrCopy(gData.host, "linux");
    StrCopy(gData.media, "-");
}

/* Format: M|cpu%|cpuT|mhz|gpu%|gpuT|ram%|ramU|ramT|disk%|rx|tx|host|media */
static Boolean ParseTelemetryLine(const Char *line) {
    const Char *p = line;
    const Char *fields[14];
    UInt16 lens[14];
    UInt16 idx = 0;

    if (line[0] != 'M' || line[1] != '|') return false;

    fields[idx] = p;
    while (*p && idx < 14) {
        if (*p == '|') {
            lens[idx] = (UInt16)(p - fields[idx]);
            idx++;
            if (idx < 14) fields[idx] = p + 1;
        }
        p++;
    }
    if (idx < 14) {
        lens[idx] = (UInt16)(p - fields[idx]);
        idx++;
    }
    if (idx < 14) return false;

    CopyField(gData.cpuPct, sizeof(gData.cpuPct), fields[1], lens[1]);
    CopyField(gData.cpuTemp, sizeof(gData.cpuTemp), fields[2], lens[2]);
    CopyField(gData.cpuMhz, sizeof(gData.cpuMhz), fields[3], lens[3]);
    CopyField(gData.gpuPct, sizeof(gData.gpuPct), fields[4], lens[4]);
    CopyField(gData.gpuTemp, sizeof(gData.gpuTemp), fields[5], lens[5]);
    CopyField(gData.ramPct, sizeof(gData.ramPct), fields[6], lens[6]);
    CopyField(gData.ramUsed, sizeof(gData.ramUsed), fields[7], lens[7]);
    CopyField(gData.ramTotal, sizeof(gData.ramTotal), fields[8], lens[8]);
    CopyField(gData.diskPct, sizeof(gData.diskPct), fields[9], lens[9]);
    CopyField(gData.netRx, sizeof(gData.netRx), fields[10], lens[10]);
    CopyField(gData.netTx, sizeof(gData.netTx), fields[11], lens[11]);
    CopyField(gData.host, sizeof(gData.host), fields[12], lens[12]);
    CopyField(gData.media, sizeof(gData.media), fields[13], lens[13]);

    gData.cpuVal = ParseIntSimple(gData.cpuPct);
    gData.gpuVal = ParseIntSimple(gData.gpuPct);
    gData.ramVal = ParseIntSimple(gData.ramPct);
    gData.diskVal = ParseIntSimple(gData.diskPct);
    gData.netVal = ParseIntSimple(gData.netRx) * 2;
    if (gData.netVal > 100) gData.netVal = 100;

    PushHist(gHistCpu, gData.cpuVal);
    PushHist(gHistGpu, gData.gpuVal);
    PushHist(gHistNet, gData.netVal);

    gData.valid = true;
    return true;
}

/* --- Drawing --- */

static void SetRGB(RGB c, Boolean isFore) {
    RGBColorType rc;
    rc.index = 0; rc.r = c.r; rc.g = c.g; rc.b = c.b;
    if (isFore) WinSetForeColorRGB(&rc, NULL);
    else WinSetBackColorRGB(&rc, NULL);
}

static void SetTextRGB(RGB c) {
    RGBColorType rc;
    rc.index = 0; rc.r = c.r; rc.g = c.g; rc.b = c.b;
    WinSetTextColorRGB(&rc, NULL);
}

static void FillRect(Coord x, Coord y, Coord w, Coord h, RGB c) {
    RectangleType rect;
    rect.topLeft.x = x; rect.topLeft.y = y;
    rect.extent.x = w; rect.extent.y = h;
    SetRGB(c, true);
    WinDrawRectangle(&rect, 0);
}

static void DrawCard(Coord x, Coord y, Coord w, Coord h, RGB c) {
    RectangleType rect;
    rect.topLeft.x = x; rect.topLeft.y = y;
    rect.extent.x = w; rect.extent.y = h;
    SetRGB(c, true);
    WinDrawRectangle(&rect, 6);
}

static void DrawBar(Coord x, Coord y, Coord w, Coord h, Int16 pct, RGB fill, RGB track) {
    Coord fillW;
    RGB warn = {245, 158, 11};
    RGB crit = {239, 68, 68};
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;
    FillRect(x, y, w, h, track);
    fillW = (Coord)((Int32)w * pct / 100);
    if (fillW > 0) {
        if (pct >= 85) fill = crit;
        else if (pct >= 65) fill = warn;
        FillRect(x, y, fillW, h, fill);
    }
}

static void DrawText(Coord x, Coord y, const Char *txt, FontID font, RGB c) {
    FntSetFont(font);
    SetTextRGB(c);
    WinDrawChars(txt, StrLen(txt), x, y);
}

static void DrawSparkline(Coord x, Coord y, Coord w, Coord h, const UInt8 *arr, RGB c, RGB track) {
    UInt16 i;
    Coord bw = w / HIST_LEN;
    if (bw < 2) bw = 2;
    FillRect(x, y, w, h, track);
    for (i = 0; i < HIST_LEN; i++) {
        Coord bh = (Coord)((Int32)h * arr[i] / 100);
        if (bh > 0) {
            FillRect(x + (Coord)(i * bw), y + h - bh, bw - 1, bh, c);
        }
    }
}

static void DrawButton(Coord x, Coord y, Coord w, Coord h, const Char *lbl, RGB bg, RGB fg) {
    DrawCard(x, y, w, h, bg);
    SetRGB(bg, false);
    DrawText(x + (w / 2) - (StrLen(lbl) * 4), y + (h / 2) - 6, lbl, boldFont, fg);
}

static void RedrawDashboard(void) {
    Char buf[64];
    const Theme *t = &gThemes[gPrefs.themeIdx % NUM_THEMES];

    WinPushDrawState();
    if (gHiRes) WinSetCoordinateSystem(kCoordinatesDouble);

    FillRect(0, 0, 320, 320, t->bg);
    SetRGB(t->card, false);

    /* Header */
    FillRect(0, 0, 320, 34, t->header);
    SetRGB(t->header, false);
    DrawText(10, 8, "ZireMon", boldFont, t->cpu);

    if (gPrefs.screenIdx == 0) StrCopy(buf, gData.host);
    else if (gPrefs.screenIdx == 1) StrCopy(buf, "[2/3] HIST");
    else StrCopy(buf, "[3/3] MEDIA");
    DrawText(94, 9, buf, stdFont, t->muted);

    if (gConnected) {
        FillRect(216, 9, 96, 16, t->badge);
        SetRGB(t->badge, false);
        DrawText(224, 10, "BT ONLINE", boldFont, t->badgeText);
    } else if (gListening) {
        RGB waitC = {245, 158, 11};
        FillRect(216, 9, 96, 16, waitC);
        SetRGB(waitC, false);
        DrawText(232, 10, "WAIT PC", boldFont, t->badgeText);
    } else {
        FillRect(216, 9, 96, 16, t->muted);
        SetRGB(t->muted, false);
        DrawText(234, 10, "OFFLINE", boldFont, t->badgeText);
    }

    if (gPrefs.screenIdx == 0) {
        /* Screen 1: Dashboard */
        DrawCard(8, 42, 304, 62, t->card);
        SetRGB(t->card, false);
        DrawText(18, 48, "CPU", boldFont, t->cpu);
        StrCopy(buf, gData.cpuPct); StrCat(buf, "%");
        DrawText(64, 48, buf, largeBoldFont, t->text);
        StrCopy(buf, gData.cpuTemp); StrCat(buf, " C   ");
        StrCat(buf, gData.cpuMhz); StrCat(buf, " MHz");
        DrawText(160, 50, buf, stdFont, t->muted);
        DrawBar(18, 78, 284, 14, gData.cpuVal, t->cpu, t->track);

        DrawCard(8, 112, 304, 56, t->card);
        SetRGB(t->card, false);
        DrawText(18, 118, "GPU", boldFont, t->gpu);
        StrCopy(buf, gData.gpuPct); StrCat(buf, "%");
        DrawText(68, 118, buf, largeBoldFont, t->text);
        StrCopy(buf, "Temp: "); StrCat(buf, gData.gpuTemp); StrCat(buf, " C");
        DrawText(180, 120, buf, stdFont, t->muted);
        DrawBar(18, 144, 284, 12, gData.gpuVal, t->gpu, t->track);

        DrawCard(8, 176, 148, 68, t->card);
        SetRGB(t->card, false);
        DrawText(18, 182, "RAM", boldFont, t->ram);
        StrCopy(buf, gData.ramPct); StrCat(buf, "%");
        DrawText(70, 182, buf, boldFont, t->text);
        StrCopy(buf, gData.ramUsed); StrCat(buf, "/");
        StrCat(buf, gData.ramTotal); StrCat(buf, "G");
        DrawText(18, 202, buf, stdFont, t->muted);
        DrawBar(18, 222, 128, 10, gData.ramVal, t->ram, t->track);

        DrawCard(164, 176, 148, 68, t->card);
        SetRGB(t->card, false);
        DrawText(174, 182, "DISK", boldFont, t->disk);
        StrCopy(buf, gData.diskPct); StrCat(buf, "%");
        DrawText(224, 182, buf, boldFont, t->text);
        DrawText(174, 202, "Root /", stdFont, t->muted);
        DrawBar(174, 222, 128, 10, gData.diskVal, t->disk, t->track);

        DrawCard(8, 252, 304, 60, t->card);
        SetRGB(t->card, false);
        StrCopy(buf, "NET  RX "); StrCat(buf, gData.netRx);
        StrCat(buf, " Mbps   TX "); StrCat(buf, gData.netTx); StrCat(buf, " Mbps");
        DrawText(18, 258, buf, stdFont, t->net);
        if (gConnected) {
            StrCopy(buf, "Media: ");
            StrNCat(buf, gData.media, sizeof(buf) - 1);
            DrawText(18, 280, buf, stdFont, t->text);
        } else {
            DrawText(18, 280, gStatusMsg, stdFont, t->disk);
        }
    } else if (gPrefs.screenIdx == 1) {
        /* Screen 2: History Sparklines */
        DrawCard(8, 42, 304, 84, t->card);
        SetRGB(t->card, false);
        StrPrintF(buf, "CPU %s%%", gData.cpuPct);
        DrawText(18, 48, buf, boldFont, t->cpu);
        StrPrintF(buf, "Pico: %d%%", (Int16)MaxHist(gHistCpu));
        DrawText(220, 48, buf, stdFont, t->muted);
        DrawSparkline(18, 68, 284, 48, gHistCpu, t->cpu, t->track);

        DrawCard(8, 134, 304, 84, t->card);
        SetRGB(t->card, false);
        StrPrintF(buf, "GPU %s%%", gData.gpuPct);
        DrawText(18, 140, buf, boldFont, t->gpu);
        StrPrintF(buf, "Pico: %d%%", (Int16)MaxHist(gHistGpu));
        DrawText(220, 140, buf, stdFont, t->muted);
        DrawSparkline(18, 160, 284, 48, gHistGpu, t->gpu, t->track);

        DrawCard(8, 226, 304, 84, t->card);
        SetRGB(t->card, false);
        StrCopy(buf, "NET RX "); StrCat(buf, gData.netRx); StrCat(buf, " Mbps");
        DrawText(18, 232, buf, boldFont, t->net);
        DrawSparkline(18, 252, 284, 48, gHistNet, t->net, t->track);
    } else {
        /* Screen 3: Media Touch Control */
        DrawCard(8, 42, 304, 110, t->card);
        SetRGB(t->card, false);
        DrawText(18, 52, "TOCANDO AGORA (MPRIS)", stdFont, t->muted);
        StrNCopy(buf, gData.media, 40);
        buf[40] = '\0';
        DrawText(18, 86, buf, boldFont, t->text);

        DrawButton(16, 168, 88, 56, "|<", t->card, t->text);
        DrawButton(116, 168, 88, 56, ">||", t->cpu, t->badgeText);
        DrawButton(216, 168, 88, 56, ">|", t->card, t->text);

        DrawButton(36, 240, 116, 52, "VOL -", t->card, t->text);
        DrawButton(168, 240, 116, 52, "VOL +", t->card, t->text);
    }

    WinPopDrawState();
}

/* --- Bluetooth SPP --- */

static void SendCommandBT(const Char *cmd) {
    Err err;
    if (!gConnected || gPortId == 0) return;
    SrmSend(gPortId, (void *)cmd, StrLen(cmd), &err);
}

static void DisconnectBT(void) {
    if (gPortId != 0) {
        SrmClose(gPortId);
        gPortId = 0;
    }
    gConnected = false;
    gListening = false;
    gLinePos = 0;
    StrCopy(gStatusMsg, "Disconnected. Tap to listen.");
    RedrawDashboard();
}

static Boolean ListenBT(void) {
    Err err;
    SrmOpenConfigType config;
    BtVdOpenParams btParams;
    BtLibSdpUuidType sppUuid;

    if (gPortId != 0) {
        SrmClose(gPortId);
        gPortId = 0;
    }
    gConnected = false;
    gListening = false;

    MemSet(&sppUuid, sizeof(sppUuid), 0);
    sppUuid.size = btLibUuidSize16;
    sppUuid.UUID[0] = 0x11;
    sppUuid.UUID[1] = 0x01;

    MemSet(&btParams, sizeof(btParams), 0);
    btParams.role = btVdServer;
    btParams.u.server.uuid = sppUuid;
    btParams.u.server.name = "ZireMon";

    MemSet(&config, sizeof(config), 0);
    config.function = 0;
    config.drvrDataP = (MemPtr)&btParams;
    config.drvrDataSize = sizeof(btParams);

    err = SrmExtOpen(sysFileCVirtRfComm, &config, sizeof(config), &gPortId);
    if (err != errNone) {
        gPortId = 0;
        StrPrintF(gStatusMsg, "Listen err: 0x%04X", (UInt16)err);
        RedrawDashboard();
        return false;
    }

    gListening = true;
    gLinePos = 0;
    StrCopy(gStatusMsg, "Waiting PC connection...");
    RedrawDashboard();
    return true;
}

static Boolean ConnectBT(Boolean forcePicker) {
    Err err;
    SrmOpenConfigType config;
    BtVdOpenParams btParams;
    BtLibSdpUuidType sppUuid;

    if (gConnected || gListening) DisconnectBT();

    StrCopy(gStatusMsg, "Connecting Bluetooth SPP...");
    RedrawDashboard();

    MemSet(&sppUuid, sizeof(sppUuid), 0);
    sppUuid.size = btLibUuidSize16;
    sppUuid.UUID[0] = 0x11;
    sppUuid.UUID[1] = 0x01;

    MemSet(&btParams, sizeof(btParams), 0);
    btParams.role = btVdClient;
    btParams.u.client.method = btVdUseUuidList;
    btParams.u.client.u.uuidList.tab = &sppUuid;
    btParams.u.client.u.uuidList.len = 1;

    if (!forcePicker && gPrefs.hasAddr) {
        btParams.u.client.remoteDevAddr = gPrefs.addr;
    }

    MemSet(&config, sizeof(config), 0);
    config.function = 0;
    config.drvrDataP = (MemPtr)&btParams;
    config.drvrDataSize = sizeof(btParams);

    err = SrmExtOpen(sysFileCVirtRfComm, &config, sizeof(config), &gPortId);
    if (err != errNone) {
        gPortId = 0;
        gConnected = false;
        StrPrintF(gStatusMsg, "BT error: 0x%04X", (UInt16)err);
        RedrawDashboard();
        return false;
    }

    gConnected = true;
    gLinePos = 0;
    StrCopy(gStatusMsg, "Connected! Waiting data...");
    RedrawDashboard();
    return true;
}

static void PollSerialData(void) {
    UInt32 avail = 0;
    Err err;
    Char rx[RX_BUF_SIZE];
    UInt32 got, i;
    Boolean updated = false;

    if (!gPortId) return;

    err = SrmReceiveCheck(gPortId, &avail);
    if (err != errNone && err != serErrLineErr) {
        if (gListening && !gConnected) return;
        ListenBT();
        return;
    }
    if (avail == 0) return;

    if (avail > sizeof(rx)) avail = sizeof(rx);
    got = SrmReceive(gPortId, rx, avail, 0, &err);
    if (err != errNone && err != serErrTimeOut && err != serErrLineErr) {
        if (gListening && !gConnected) return;
        ListenBT();
        return;
    }

    for (i = 0; i < got; i++) {
        Char c = rx[i];
        if (c == '\r') continue;
        if (c == '\n') {
            gLineBuf[gLinePos] = '\0';
            if (ParseTelemetryLine(gLineBuf)) {
                gConnected = true;
                gListening = false;
                updated = true;
            }
            gLinePos = 0;
        } else if (gLinePos < LINE_BUF_SIZE - 1) {
            gLineBuf[gLinePos++] = c;
        } else {
            gLinePos = 0;
        }
    }

    if (updated) RedrawDashboard();
}

/* --- Events --- */

static Boolean MainFormHandleEvent(EventPtr eventP) {
    Boolean handled = false;
    Coord px, py;

    switch (eventP->eType) {
        case frmOpenEvent:
            FrmDrawForm(FrmGetActiveForm());
            ListenBT();
            handled = true;
            break;

        case frmUpdateEvent:
            FrmDrawForm(FrmGetActiveForm());
            RedrawDashboard();
            handled = true;
            break;

        case keyDownEvent:
            if (eventP->data.keyDown.chr == vchrRockerRight || eventP->data.keyDown.chr == pageDownChr) {
                gPrefs.screenIdx = (gPrefs.screenIdx + 1) % NUM_SCREENS;
                RedrawDashboard();
                handled = true;
            } else if (eventP->data.keyDown.chr == vchrRockerLeft || eventP->data.keyDown.chr == pageUpChr) {
                gPrefs.screenIdx = (gPrefs.screenIdx + NUM_SCREENS - 1) % NUM_SCREENS;
                RedrawDashboard();
                handled = true;
            }
            break;

        case penDownEvent:
            px = gHiRes ? (eventP->screenX * 2) : eventP->screenX;
            py = gHiRes ? (eventP->screenY * 2) : eventP->screenY;
            if (py <= 34) {
                if (px < 90) {
                    gPrefs.themeIdx = (gPrefs.themeIdx + 1) % NUM_THEMES;
                } else {
                    gPrefs.screenIdx = (gPrefs.screenIdx + 1) % NUM_SCREENS;
                }
                RedrawDashboard();
                handled = true;
            } else if (gPrefs.screenIdx == 2 && gConnected) {
                if (py >= 168 && py <= 224) {
                    if (px >= 16 && px <= 104) SendCommandBT("CMD|PREV\n");
                    else if (px >= 116 && px <= 204) SendCommandBT("CMD|PLAY_PAUSE\n");
                    else if (px >= 216 && px <= 304) SendCommandBT("CMD|NEXT\n");
                    handled = true;
                } else if (py >= 240 && py <= 292) {
                    if (px >= 36 && px <= 152) SendCommandBT("CMD|VOL_DOWN\n");
                    else if (px >= 168 && px <= 284) SendCommandBT("CMD|VOL_UP\n");
                    handled = true;
                }
            } else if (!gConnected && !gListening) {
                ListenBT();
                handled = true;
            }
            break;

        case menuEvent:
            switch (eventP->data.menu.itemID) {
                case MenuListen:
                    ListenBT(); handled = true; break;
                case MenuConnect:
                    ConnectBT(false); handled = true; break;
                case MenuDisconnect:
                    DisconnectBT(); handled = true; break;
                case MenuPick:
                    ConnectBT(true); handled = true; break;
                case MenuNextTheme:
                    gPrefs.themeIdx = (gPrefs.themeIdx + 1) % NUM_THEMES;
                    RedrawDashboard(); handled = true; break;
                case MenuNextScreen:
                    gPrefs.screenIdx = (gPrefs.screenIdx + 1) % NUM_SCREENS;
                    RedrawDashboard(); handled = true; break;
                case MenuAbout:
                    FrmAlert(AboutAlert); handled = true; break;
            }
            break;

        default:
            break;
    }
    return handled;
}

static Boolean AppHandleEvent(EventPtr eventP) {
    FormPtr frmP;
    UInt16 formId;

    if (eventP->eType == frmLoadEvent) {
        formId = eventP->data.frmLoad.formID;
        frmP = FrmInitForm(formId);
        FrmSetActiveForm(frmP);
        if (formId == MainForm) {
            FrmSetEventHandler(frmP, MainFormHandleEvent);
        }
        return true;
    }
    return false;
}

static void AppEventLoop(void) {
    EventType event;
    Err error;
    Int32 waitTicks = SysTicksPerSecond() / 4;

    do {
        EvtGetEvent(&event, (gConnected || gListening) ? waitTicks : evtWaitForever);
        if (!SysHandleEvent(&event)) {
            if (!MenuHandleEvent(0, &event, &error)) {
                if (!AppHandleEvent(&event)) {
                    FrmDispatchEvent(&event);
                }
            }
        }
        if (gConnected || gListening) {
            EvtResetAutoOffTimer();
            PollSerialData();
        }
    } while (event.eType != appStopEvent);
}

static Err AppStart(void) {
    UInt32 density = kDensityLow;
    UInt16 prefSize = sizeof(gPrefs);

    InitDefaultData();
    MemSet(&gPrefs, sizeof(gPrefs), 0);
    PrefGetAppPreferences(APP_CREATOR, PREF_ID, &gPrefs, &prefSize, true);

    if (WinScreenGetAttribute(winScreenDensity, &density) == errNone &&
        density >= kDensityDouble) {
        gHiRes = true;
    }

    FrmGotoForm(MainForm);
    return errNone;
}

static void AppStop(void) {
    DisconnectBT();
    PrefSetAppPreferences(APP_CREATOR, PREF_ID, PREF_VERSION, &gPrefs, sizeof(gPrefs), true);
    FrmCloseAllForms();
}

UInt32 PilotMain(UInt16 cmd, MemPtr cmdPBP, UInt16 launchFlags) {
    Err error;
    if (cmd == sysAppLaunchCmdNormalLaunch) {
        error = AppStart();
        if (error) return error;
        AppEventLoop();
        AppStop();
    }
    return errNone;
}
