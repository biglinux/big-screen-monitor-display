#include <PalmOS.h>
#include <SerialMgr.h>
#include <BtLib.h>
#include <BtCommVdrv.h>

#include "ziremon_res.h"

#define APP_CREATOR     'ZMon'
#define PREF_ID         1
#define PREF_VERSION    1

#define RX_BUF_SIZE     256
#define LINE_BUF_SIZE   256

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
} TelemetryData;

typedef struct {
    Boolean hasAddr;
    BtLibDeviceAddressType addr;
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

static void InitDefaultData(void) {
    MemSet(&gData, sizeof(gData), 0);
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
    gData.valid = true;
    return true;
}

/* --- Drawing (320x320 HiRes Dark Theme) --- */

static void SetRGB(UInt8 r, UInt8 g, UInt8 b, Boolean isFore) {
    RGBColorType c;
    c.index = 0;
    c.r = r;
    c.g = g;
    c.b = b;
    if (isFore) WinSetForeColorRGB(&c, NULL);
    else WinSetBackColorRGB(&c, NULL);
}

static void SetTextRGB(UInt8 r, UInt8 g, UInt8 b) {
    RGBColorType c;
    c.index = 0;
    c.r = r;
    c.g = g;
    c.b = b;
    WinSetTextColorRGB(&c, NULL);
}

static void FillRect(Coord x, Coord y, Coord w, Coord h, UInt8 r, UInt8 g, UInt8 b) {
    RectangleType rect;
    rect.topLeft.x = x;
    rect.topLeft.y = y;
    rect.extent.x = w;
    rect.extent.y = h;
    SetRGB(r, g, b, true);
    WinDrawRectangle(&rect, 0);
}

static void DrawBar(Coord x, Coord y, Coord w, Coord h, Int16 pct, UInt8 r, UInt8 g, UInt8 b) {
    Coord fillW;
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;

    /* Track */
    FillRect(x, y, w, h, 35, 45, 62);

    /* Fill */
    fillW = (Coord)((Int32)w * pct / 100);
    if (fillW > 0) {
        if (pct >= 85) { r = 239; g = 68; b = 68; }
        else if (pct >= 65) { r = 245; g = 158; b = 11; }
        FillRect(x, y, fillW, h, r, g, b);
    }
}

static void DrawText(Coord x, Coord y, const Char *txt, FontID font, UInt8 r, UInt8 g, UInt8 b) {
    FntSetFont(font);
    SetTextRGB(r, g, b);
    WinDrawChars(txt, StrLen(txt), x, y);
}

static void DrawCard(Coord x, Coord y, Coord w, Coord h) {
    RectangleType rect;
    rect.topLeft.x = x;
    rect.topLeft.y = y;
    rect.extent.x = w;
    rect.extent.y = h;
    SetRGB(24, 33, 48, true);
    WinDrawRectangle(&rect, 6);
}

static void RedrawDashboard(void) {
    Char buf[64];

    WinPushDrawState();
    if (gHiRes) {
        WinSetCoordinateSystem(kCoordinatesDouble);
    }

    /* Background #0F141E */
    FillRect(0, 0, 320, 320, 15, 20, 30);
    SetRGB(24, 33, 48, false);

    /* Header bar */
    FillRect(0, 0, 320, 34, 20, 28, 42);
    DrawText(10, 8, "ZireMon", boldFont, 56, 189, 248);
    DrawText(94, 9, gData.host, stdFont, 148, 163, 184);

    if (gConnected) {
        FillRect(216, 9, 96, 16, 16, 185, 129);
        SetRGB(16, 185, 129, false);
        DrawText(224, 10, "BT ONLINE", boldFont, 15, 20, 30);
    } else if (gListening) {
        FillRect(216, 9, 96, 16, 245, 158, 11);
        SetRGB(245, 158, 11, false);
        DrawText(232, 10, "WAIT PC", boldFont, 15, 20, 30);
    } else {
        FillRect(216, 9, 96, 16, 100, 116, 139);
        SetRGB(100, 116, 139, false);
        DrawText(234, 10, "OFFLINE", boldFont, 15, 20, 30);
    }

    /* Card 1: CPU */
    DrawCard(8, 42, 304, 62);
    SetRGB(24, 33, 48, false);
    DrawText(18, 48, "CPU", boldFont, 56, 189, 248);

    StrCopy(buf, gData.cpuPct);
    StrCat(buf, "%");
    DrawText(62, 48, buf, largeBoldFont, 248, 250, 252);

    StrCopy(buf, gData.cpuTemp);
    StrCat(buf, " C   ");
    StrCat(buf, gData.cpuMhz);
    StrCat(buf, " MHz");
    DrawText(160, 50, buf, stdFont, 203, 213, 225);

    DrawBar(18, 78, 284, 14, gData.cpuVal, 56, 189, 248);

    /* Card 2: GPU */
    DrawCard(8, 112, 304, 56);
    SetRGB(24, 33, 48, false);
    DrawText(18, 118, "GPU", boldFont, 167, 139, 250);

    StrCopy(buf, gData.gpuPct);
    StrCat(buf, "%");
    DrawText(68, 118, buf, largeBoldFont, 248, 250, 252);

    StrCopy(buf, "Temp: ");
    StrCat(buf, gData.gpuTemp);
    StrCat(buf, " C");
    DrawText(180, 120, buf, stdFont, 203, 213, 225);

    DrawBar(18, 144, 284, 12, gData.gpuVal, 167, 139, 250);

    /* Card 3: RAM & DISK */
    DrawCard(8, 176, 148, 68);
    SetRGB(24, 33, 48, false);
    DrawText(18, 182, "RAM", boldFont, 52, 211, 153);
    StrCopy(buf, gData.ramPct);
    StrCat(buf, "%");
    DrawText(70, 182, buf, boldFont, 248, 250, 252);

    StrCopy(buf, gData.ramUsed);
    StrCat(buf, "/");
    StrCat(buf, gData.ramTotal);
    StrCat(buf, "G");
    DrawText(18, 202, buf, stdFont, 148, 163, 184);
    DrawBar(18, 222, 128, 10, gData.ramVal, 52, 211, 153);

    DrawCard(164, 176, 148, 68);
    SetRGB(24, 33, 48, false);
    DrawText(174, 182, "DISK", boldFont, 251, 191, 36);
    StrCopy(buf, gData.diskPct);
    StrCat(buf, "%");
    DrawText(224, 182, buf, boldFont, 248, 250, 252);
    DrawText(174, 202, "Root /", stdFont, 148, 163, 184);
    DrawBar(174, 222, 128, 10, gData.diskVal, 251, 191, 36);

    /* Card 4: NET & MEDIA */
    DrawCard(8, 252, 304, 60);
    SetRGB(24, 33, 48, false);
    StrCopy(buf, "NET  RX ");
    StrCat(buf, gData.netRx);
    StrCat(buf, " Mbps   TX ");
    StrCat(buf, gData.netTx);
    StrCat(buf, " Mbps");
    DrawText(18, 258, buf, stdFont, 125, 211, 252);

    if (gConnected) {
        StrCopy(buf, "Media: ");
        StrNCat(buf, gData.media, sizeof(buf) - 1);
        DrawText(18, 280, buf, stdFont, 226, 232, 240);
    } else {
        DrawText(18, 280, gStatusMsg, stdFont, 251, 191, 36);
    }

    WinPopDrawState();
}

/* --- Bluetooth SPP --- */

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

    if (gConnected) {
        DisconnectBT();
    }

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
        StrPrintF(gStatusMsg, "BT error: 0x%04X (Tap retry)", (UInt16)err);
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
        DisconnectBT();
        return;
    }
    if (avail == 0) return;

    if (avail > sizeof(rx)) avail = sizeof(rx);
    got = SrmReceive(gPortId, rx, avail, 0, &err);
    if (err != errNone && err != serErrTimeOut && err != serErrLineErr) {
        if (gListening && !gConnected) return;
        DisconnectBT();
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

    if (updated) {
        RedrawDashboard();
    }
}

/* --- Palm OS App Boilerplate --- */

static Boolean MainFormHandleEvent(EventPtr eventP) {
    Boolean handled = false;

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

        case penDownEvent:
            if (!gConnected && !gListening) {
                ListenBT();
                handled = true;
            }
            break;

        case menuEvent:
            switch (eventP->data.menu.itemID) {
                case MenuListen:
                    ListenBT();
                    handled = true;
                    break;
                case MenuConnect:
                    ConnectBT(false);
                    handled = true;
                    break;
                case MenuDisconnect:
                    DisconnectBT();
                    handled = true;
                    break;
                case MenuPick:
                    ConnectBT(true);
                    handled = true;
                    break;
                case MenuAbout:
                    FrmAlert(AboutAlert);
                    handled = true;
                    break;
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
