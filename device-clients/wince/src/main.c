/*
 * bsmd-ce - Big Screen Monitor Display client for Windows CE devices
 * (FOSTON FS-707DC and similar MediaTek MT3351 navigators).
 *
 * The client turns the device into a touch display of the Linux host:
 *
 *   1. Copies itself to RAM (\Temp) and restarts from there, so the USB
 *      storage the executable came from can be detached safely.
 *   2. Writes an inspection report (OS, memory, screen, USB function
 *      clients, active drivers, backlight keys) next to the original file.
 *   3. Switches the USB function client to Serial_Class (the host sees a
 *      045e:00ce "PocketPC" serial port, /dev/ttyUSB*), remembering the
 *      previous client (usually Mass_Storage_Class) to restore it on exit.
 *   4. Speaks FSP (fsp.h) on that port: draws rectangles received from the
 *      host into a 16-bit DIB, shows them on PRESENT and reports touches.
 *
 * Nothing persistent is changed on the device: no registry writes except
 * the standard backlight level when the host asks for brightness, no ROM or
 * boot changes. Quitting (corner hold or the Exit button on the waiting
 * screen) restores the USB client.
 *
 * Build: see ../Makefile (CeGCC arm-mingw32ce).
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#include "fsp.h"
#include "splash_data.h"

#define CLIENT_VERSION "bsmd-ce 1.2.1"
#define CLIENT_VERSION_W L"bsmd-ce 1.2.1"
#define WM_APP_CALIBRATE (WM_APP + 1)
#define WM_APP_STATUS    (WM_APP + 2)
#define CORNER 64                 /* top-left exit corner, pixels */
#define CORNER_HOLD_MS 3000
#define TIMER_KEEPALIVE 1
#define TIMER_CORNER 2

/* ---------------------------------------------------------------- state */

static HINSTANCE g_inst;
static HWND g_hwnd;
static int g_width, g_height;
static HDC g_memdc;
static HBITMAP g_dib, g_olddib;
static fsp_surface g_surface;
static CRITICAL_SECTION g_fb_lock, g_write_lock;
static HANDLE g_port = INVALID_HANDLE_VALUE;
static volatile LONG g_connected;      /* host said HELLO */
static volatile LONG g_quit;
static volatile LONG g_quit_reader;
static volatile LONG g_touch_enabled = 1;
static DWORD g_move_interval = 25;
static uint16_t g_tx_seq;
static WCHAR g_origin_dir[MAX_PATH];  /* directory the user launched the client from */
static WCHAR g_status[160] = L"Iniciando...";
static WCHAR g_host[64];
static WCHAR g_port_name[16];
static WCHAR g_prev_client[128];      /* USB function client to restore */
static int g_switched_usb;
static int g_backlight_kind;          /* 0 none, 1 registry */
static int g_backlight_level = 255;
static DWORD g_last_move;
static int g_last_x = -1, g_last_y = -1;
static DWORD g_corner_since;
static RECT g_exit_button;

static uint16_t *g_art;               /* waiting-screen artwork (splash_data.h), when the panel is 800x480 */
static uint8_t *g_rx_buf;             /* parser buffer */
static uint8_t *g_scratch;            /* inflate output */
static size_t g_scratch_len;

static void set_status(const WCHAR *text);

/* Diagnostic lines shown on the waiting screen (what the USB function
 * controller and the driver list really said on this device). */
#define DIAG_LINES 5
#define DIAG_UFN 0
#define DIAG_CLIENT 1
#define DIAG_LIST 2
#define DIAG_PORT 3
#define DIAG_USBDRV 4
static WCHAR g_diag[DIAG_LINES][160];

static void diag_set(int line, const WCHAR *text)
{
    if (wcscmp(text, g_diag[line])) {
        wcsncpy(g_diag[line], text, 159);
        g_diag[line][159] = 0;
        if (g_hwnd)
            PostMessageW(g_hwnd, WM_APP_STATUS, 0, 0);
    }
}

/* _snwprintf only: this device's coredll has no _vsnwprintf (bsmd-ce 1.0.1 did not load). */
#define diag(line, ...) do { WCHAR diag_text_[160]; _snwprintf(diag_text_, 159, __VA_ARGS__); \
                             diag_text_[159] = 0; diag_set(line, diag_text_); } while (0)

/* ------------------------------------------------------------- logging */

static FILE *g_log;

static void log_line(const char *fmt, ...)
{
    va_list ap;
    if (!g_log)
        return;
    fprintf(g_log, "[%lu] ", (unsigned long)GetTickCount());
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
}

/* -------------------------------------------------- dynamic coredll calls */

typedef struct {
    DWORD dwSize;
    HANDLE hDevice;
    HANDLE hParentDevice;
    WCHAR szLegacyName[6];
    WCHAR szDeviceKey[MAX_PATH];
    WCHAR szDeviceName[MAX_PATH];
    WCHAR szBusName[MAX_PATH];
} DEVINFO_CE;

typedef HANDLE (WINAPI *FindFirstDevice_t)(int, const void *, DEVINFO_CE *);
typedef BOOL (WINAPI *FindClose_t)(HANDLE);
typedef void (WINAPI *SystemIdleTimerReset_t)(void);
typedef HANDLE (WINAPI *SetPowerRequirement_t)(PVOID, int, ULONG, PVOID, ULONG);
typedef BOOL (WINAPI *TouchCalibrate_t)(void);
typedef BOOL (WINAPI *CeSetThreadPriority_t)(HANDLE, int);

static HMODULE g_coredll;
static SystemIdleTimerReset_t p_idle_reset;
static HANDLE g_power_req;

static FARPROC core_proc(const WCHAR *name)
{
    if (!g_coredll)
        g_coredll = LoadLibraryW(L"coredll.dll");
    return g_coredll ? GetProcAddressW(g_coredll, name) : NULL;
}

static void keep_awake_init(void)
{
    SetPowerRequirement_t set_req = (SetPowerRequirement_t)core_proc(L"SetPowerRequirement");
    p_idle_reset = (SystemIdleTimerReset_t)core_proc(L"SystemIdleTimerReset");
    if (set_req)
        g_power_req = set_req((PVOID)L"BKL1:", 0 /* D0 */, 1 /* POWER_NAME */, NULL, 0);
    log_line("keep awake: idle reset %s, backlight requirement %s",
             p_idle_reset ? "yes" : "no", g_power_req ? "yes" : "no");
}

static void keep_awake_done(void)
{
    typedef DWORD (WINAPI *ReleasePowerRequirement_t)(HANDLE);
    ReleasePowerRequirement_t rel = (ReleasePowerRequirement_t)core_proc(L"ReleasePowerRequirement");
    if (g_power_req && rel)
        rel(g_power_req);
    g_power_req = NULL;
}

/* -------------------------------------------------------- USB function */

typedef struct { WCHAR szName[128]; } UFN_NAME;
typedef struct { WCHAR szName[128]; WCHAR szDescription[250]; } UFN_INFO;
/* usbfnioctl.h: CTL_CODE(FILE_DEVICE_UNKNOWN, n, METHOD_BUFFERED, FILE_ANY_ACCESS) */
#define UFN_IOCTL(n) ((0x22UL << 16) | ((n) << 2))
#define IOCTL_UFN_ENUMERATE_AVAILABLE_CLIENTS UFN_IOCTL(2)
#define IOCTL_UFN_GET_CURRENT_CLIENT          UFN_IOCTL(3)
#define IOCTL_UFN_CHANGE_CURRENT_CLIENT       UFN_IOCTL(4)
#define DEVACCESS_BUSNAMESPACE 0x0100UL        /* FILE_WRITE_ATTRIBUTES */

static const GUID GUID_USBFN = {0xE2BDC372, 0x598F, 0x4619, {0xBC, 0x50, 0x54, 0xB3, 0xF7, 0x84, 0x8D, 0x35}};

static HANDLE try_open(const WCHAR *name, DWORD access, DWORD share, WCHAR *errors, size_t room)
{
    HANDLE h;
    size_t used;
    if (!name || !name[0])
        return INVALID_HANDLE_VALUE;
    h = CreateFileW(name, access, share, NULL, OPEN_EXISTING, 0, NULL);
    if (h != INVALID_HANDLE_VALUE)
        return h;
    used = wcslen(errors);
    if (used + 24 < room)
        _snwprintf(errors + used, room - used - 1, L" %ls/%lx=%lu", name, access, GetLastError());
    return INVALID_HANDLE_VALUE;
}

/* Open the USB function bus driver. Several ways exist across BSPs; every
 * failure is recorded (shown on screen and in the report). */
static HANDLE ufn_open(FILE *report)
{
    FindFirstDevice_t find_first = (FindFirstDevice_t)core_proc(L"FindFirstDevice");
    FindClose_t find_close = (FindClose_t)core_proc(L"FindClose");
    DEVINFO_CE di;
    HANDLE h = INVALID_HANDLE_VALUE;
    WCHAR errors[200], used_name[MAX_PATH];
    static const WCHAR *legacy[] = {L"UFN1:", L"UFN0:", L"UFN2:", NULL};
    int i;
    errors[0] = 0;
    used_name[0] = 0;
    memset(&di, 0, sizeof(di));
    if (find_first) {
        HANDLE search;
        di.dwSize = sizeof(di);
        search = find_first(3 /* DeviceSearchByGuid */, &GUID_USBFN, &di);
        if (search != INVALID_HANDLE_VALUE && search != NULL) {
            if (report)
                fprintf(report, "usbfn bus: legacy=%ls key=%ls name=%ls bus=%ls\n", di.szLegacyName,
                        di.szDeviceKey, di.szDeviceName, di.szBusName);
            if (find_close)
                find_close(search);
            if ((h = try_open(di.szBusName, GENERIC_READ, FILE_SHARE_READ, errors, 200)) == INVALID_HANDLE_VALUE &&
                (h = try_open(di.szBusName, DEVACCESS_BUSNAMESPACE, 0, errors, 200)) == INVALID_HANDLE_VALUE &&
                (h = try_open(di.szLegacyName, 0, 0, errors, 200)) == INVALID_HANDLE_VALUE)
                h = try_open(di.szDeviceName, 0, 0, errors, 200);
            if (h != INVALID_HANDLE_VALUE)
                wcscpy(used_name, di.szBusName[0] ? di.szBusName : di.szLegacyName);
        } else {
            _snwprintf(errors, 199, L" guid:%lu", GetLastError());
        }
    } else {
        wcscpy(errors, L" sem FindFirstDevice");
    }
    for (i = 0; h == INVALID_HANDLE_VALUE && legacy[i]; i++) {
        if ((h = try_open(legacy[i], DEVACCESS_BUSNAMESPACE, 0, errors, 200)) == INVALID_HANDLE_VALUE &&
            (h = try_open(legacy[i], GENERIC_READ | GENERIC_WRITE, 0, errors, 200)) == INVALID_HANDLE_VALUE)
            h = try_open(legacy[i], 0, 0, errors, 200);
        if (h != INVALID_HANDLE_VALUE)
            wcscpy(used_name, legacy[i]);
    }
    errors[199] = 0;
    if (h == INVALID_HANDLE_VALUE)
        diag(DIAG_UFN, L"USB fn: nao abriu:%ls", errors);
    else
        diag(DIAG_UFN, L"USB fn: %ls (%ls)", used_name, di.szDeviceKey[0] ? di.szDeviceKey : L"-");
    if (report)
        fprintf(report, "usbfn open: %ls %ls\n", h == INVALID_HANDLE_VALUE ? L"FAILED" : used_name, errors);
    return h;
}

static int ufn_current(HANDLE h, WCHAR *out, size_t out_chars)
{
    UFN_INFO info;
    DWORD got = 0;
    memset(&info, 0, sizeof(info));
    if (!DeviceIoControl(h, IOCTL_UFN_GET_CURRENT_CLIENT, NULL, 0, &info, sizeof(info), &got, NULL))
        return 0;
    wcsncpy(out, info.szName, out_chars - 1);
    out[out_chars - 1] = 0;
    return 1;
}

static int ufn_change(HANDLE h, const WCHAR *name)
{
    UFN_NAME n;
    memset(&n, 0, sizeof(n));
    wcsncpy(n.szName, name, 127);
    return DeviceIoControl(h, IOCTL_UFN_CHANGE_CURRENT_CLIENT, &n, sizeof(n), NULL, 0, NULL, NULL) ? 1 : 0;
}

static void ufn_report(FILE *report)
{
    HANDLE h = ufn_open(report);
    UFN_INFO list[8];
    DWORD got = 0, i;
    WCHAR current[128];
    if (h == INVALID_HANDLE_VALUE)
        return;
    memset(list, 0, sizeof(list));
    if (DeviceIoControl(h, IOCTL_UFN_ENUMERATE_AVAILABLE_CLIENTS, NULL, 0, list, sizeof(list), &got, NULL)) {
        for (i = 0; i < got / sizeof(UFN_INFO) && i < 8; i++)
            fprintf(report, "usbfn client: %ls (%ls)\n", list[i].szName, list[i].szDescription);
    } else {
        fprintf(report, "usbfn clients: enumerate failed (error %lu)\n", GetLastError());
    }
    if (ufn_current(h, current, 128))
        fprintf(report, "usbfn current client: %ls\n", current);
    else
        fprintf(report, "usbfn current client: query failed (error %lu)\n", GetLastError());
    CloseHandle(h);
}

#define UFN_KEY L"Drivers\\USB\\FunctionDrivers"

static int read_default_client(WCHAR *out, DWORD chars)
{
    HKEY key;
    DWORD len = chars * sizeof(WCHAR), type = 0;
    int ok = 0;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, UFN_KEY, 0, 0, &key) != ERROR_SUCCESS)
        return 0;
    if (RegQueryValueExW(key, L"DefaultClientDriver", NULL, &type, (BYTE *)out, &len) == ERROR_SUCCESS &&
        type == REG_SZ && out[0]) {
        out[chars - 1] = 0;
        ok = 1;
    }
    RegCloseKey(key);
    return ok;
}

/* IOCTL_UFN_CHANGE_CURRENT_CLIENT on the FS-707DC also saves the new client
 * as the boot default (found 2026-11-19: after using the panel the navigator
 * kept starting as a serial port instead of USB storage, until Ajustes -> USB
 * was used). Put the saved default back right after switching. */
static void restore_default_client(const WCHAR *value)
{
    typedef LONG (WINAPI *RegFlushKey_t)(HKEY);
    RegFlushKey_t flush = (RegFlushKey_t)core_proc(L"RegFlushKey");
    WCHAR now[128];
    HKEY key;
    if (!read_default_client(now, 128) || !_wcsicmp(now, value))
        return;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, UFN_KEY, 0, 0, &key) != ERROR_SUCCESS)
        return;
    RegSetValueExW(key, L"DefaultClientDriver", 0, REG_SZ, (const BYTE *)value,
                   (DWORD)((wcslen(value) + 1) * sizeof(WCHAR)));
    if (flush)
        flush(key);
    RegCloseKey(key);
    log_line("DefaultClientDriver %ls -> %ls (restored)", now, value);
}

/* Make sure Serial_Class is the active USB client. Returns 1 when it is. */
static int ensure_serial_client(void)
{
    HANDLE h = ufn_open(NULL);
    WCHAR current[128];
    int ok = 0;
    if (h == INVALID_HANDLE_VALUE)
        return 0;
    if (ufn_current(h, current, 128)) {
        if (!_wcsicmp(current, L"Serial_Class")) {
            diag(DIAG_CLIENT, L"Cliente USB: Serial_Class (ativo)");
            ok = 1;
        } else if (ufn_change(h, L"Serial_Class")) {
            WCHAR saved[128];
            if (read_default_client(saved, 128) && !_wcsicmp(saved, L"Serial_Class") &&
                _wcsicmp(current, L"Serial_Class"))
                restore_default_client(current);
            diag(DIAG_CLIENT, L"Cliente USB: %ls -> Serial_Class", current);
            if (!g_switched_usb) {
                wcscpy(g_prev_client, current);
                g_switched_usb = 1;
            }
            log_line("usb client %ls -> Serial_Class", current);
            ok = 1;
        } else {
            DWORD err = GetLastError();
            diag(DIAG_CLIENT, L"Cliente USB: %ls; troca falhou (erro %lu)", current, err);
            log_line("usb client switch from %ls failed (error %lu)", current, err);
        }
    } else {
        diag(DIAG_CLIENT, L"Cliente USB: consulta falhou (erro %lu)", GetLastError());
    }
    {
        UFN_INFO list[8];
        DWORD got = 0, i;
        WCHAR text[160];
        text[0] = 0;
        memset(list, 0, sizeof(list));
        if (DeviceIoControl(h, IOCTL_UFN_ENUMERATE_AVAILABLE_CLIENTS, NULL, 0, list, sizeof(list), &got, NULL)) {
            for (i = 0; i < got / sizeof(UFN_INFO) && i < 8; i++) {
                size_t used = wcslen(text);
                _snwprintf(text + used, 159 - used, L"%ls%ls", i ? L", " : L"", list[i].szName);
            }
            text[159] = 0;
            diag(DIAG_LIST, L"Disponiveis: %ls", text[0] ? text : L"(nenhum)");
        } else {
            diag(DIAG_LIST, L"Disponiveis: consulta falhou (erro %lu)", GetLastError());
        }
    }
    CloseHandle(h);
    return ok;
}

static void restore_usb_client(void)
{
    HANDLE h;
    if (!g_switched_usb || !g_prev_client[0])
        return;
    h = ufn_open(NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    log_line("restoring usb client %ls: %s", g_prev_client, ufn_change(h, g_prev_client) ? "ok" : "failed");
    CloseHandle(h);
}

/* ------------------------------------------------------- registry helpers */

static void report_key(FILE *report, HKEY root, const WCHAR *path, int depth)
{
    HKEY key;
    DWORD index;
    WCHAR name[128], sub[256];
    BYTE data[512];
    if (RegOpenKeyExW(root, path, 0, 0, &key) != ERROR_SUCCESS) {
        fprintf(report, "[%ls] (absent)\n", path);
        return;
    }
    fprintf(report, "[%ls]\n", path);
    for (index = 0;; index++) {
        DWORD name_len = 128, data_len = sizeof(data) - 2, type = 0;
        if (RegEnumValueW(key, index, name, &name_len, NULL, &type, data, &data_len) != ERROR_SUCCESS)
            break;
        if (type == REG_DWORD && data_len == 4)
            { DWORD v; memcpy(&v, data, 4); fprintf(report, "  %ls = dword:%lu\n", name, v); }
        else if (type == REG_SZ || type == REG_MULTI_SZ || type == REG_EXPAND_SZ) {
            data[data_len] = 0;
            data[data_len + 1] = 0;
            fprintf(report, "  %ls = \"%ls\"\n", name, (WCHAR *)data);
        } else
            fprintf(report, "  %ls = (type %lu, %lu bytes)\n", name, type, data_len);
    }
    if (depth > 0) {
        for (index = 0;; index++) {
            DWORD name_len = 128;
            if (RegEnumKeyExW(key, index, name, &name_len, NULL, NULL, NULL, NULL) != ERROR_SUCCESS)
                break;
            _snwprintf(sub, 255, L"%ls\\%ls", path, name);
            sub[255] = 0;
            report_key(report, root, sub, depth - 1);
        }
    }
    RegCloseKey(key);
}

/* Find the COM port created by the USB Serial_Class function driver. */
static int find_usb_serial_port(WCHAR *out, size_t out_chars)
{
    HKEY active, entry;
    DWORD index;
    WCHAR name[64], key_path[MAX_PATH], dev[32];
    int found = 0;
    WCHAR usb_keys[160];
    int count = 0;
    usb_keys[0] = 0;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, L"Drivers\\Active", 0, 0, &active) != ERROR_SUCCESS)
        return 0;
    for (index = 0; !found; index++) {
        DWORD name_len = 64, len, type;
        if (RegEnumKeyExW(active, index, name, &name_len, NULL, NULL, NULL, NULL) != ERROR_SUCCESS)
            break;
        if (RegOpenKeyExW(active, name, 0, 0, &entry) != ERROR_SUCCESS)
            continue;
        len = sizeof(key_path);
        key_path[0] = 0;
        dev[0] = 0;
        if (RegQueryValueExW(entry, L"Key", NULL, &type, (BYTE *)key_path, &len) == ERROR_SUCCESS) {
            WCHAR lower[MAX_PATH];
            size_t i;
            for (i = 0; key_path[i] && i < MAX_PATH - 1; i++)
                lower[i] = towlower(key_path[i]);
            lower[i] = 0;
            count++;
            if (wcsstr(lower, L"usb") || wcsstr(lower, L"ufn")) {
                const WCHAR *tail = wcsrchr(key_path, L'\\');
                size_t used = wcslen(usb_keys);
                WCHAR devname[16];
                DWORD dl = sizeof(devname);
                devname[0] = 0;
                RegQueryValueExW(entry, L"Name", NULL, &type, (BYTE *)devname, &dl);
                devname[15] = 0;
                if (used < 150)
                    _snwprintf(usb_keys + used, 159 - used, L"%ls%ls=%ls", used ? L" " : L"",
                               tail ? tail + 1 : key_path, devname[0] ? devname : L"-");
                usb_keys[159] = 0;
            }
            if (wcsstr(lower, L"serial_class") || wcsstr(lower, L"usbser") || wcsstr(lower, L"usbfnserial")) {
                len = sizeof(dev);
                if (RegQueryValueExW(entry, L"Name", NULL, &type, (BYTE *)dev, &len) == ERROR_SUCCESS && dev[0]) {
                    wcsncpy(out, dev, out_chars - 1);
                    out[out_chars - 1] = 0;
                    found = 1;
                }
            }
        }
        RegCloseKey(entry);
    }
    RegCloseKey(active);
    diag(DIAG_USBDRV, L"Drivers USB: %ls", usb_keys[0] ? usb_keys : L"(nenhum)");
    diag(DIAG_PORT, found ? L"Porta serial USB: %ls" : L"Porta serial USB: nenhuma (%d drivers ativos)",
         found ? out : (WCHAR *)L"", count);
    return found;
}

/* ------------------------------------------------------------- backlight */

static int backlight_probe(void)
{
    HKEY key;
    DWORD value = 0, len = sizeof(value), type;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"ControlPanel\\Backlight", 0, 0, &key) != ERROR_SUCCESS)
        return 0;
    if (RegQueryValueExW(key, L"ACBacklightLevel", NULL, &type, (BYTE *)&value, &len) == ERROR_SUCCESS &&
        type == REG_DWORD) {
        g_backlight_kind = 1;
        g_backlight_level = value > 100 ? (int)(value * 100 / 255) : (int)value;
    }
    RegCloseKey(key);
    return g_backlight_kind;
}

static void backlight_set(int percent)
{
    HKEY key;
    DWORD value, len = sizeof(value), type, current = 0;
    HANDLE event;
    if (!g_backlight_kind)
        return;
    if (percent < 5)
        percent = 5;                   /* never black out the panel from the host */
    if (percent > 100)
        percent = 100;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"ControlPanel\\Backlight", 0, 0, &key) != ERROR_SUCCESS)
        return;
    RegQueryValueExW(key, L"ACBacklightLevel", NULL, &type, (BYTE *)&current, &len);
    value = current > 100 ? (DWORD)(percent * 255 / 100) : (DWORD)percent;
    RegSetValueExW(key, L"ACBacklightLevel", 0, REG_DWORD, (BYTE *)&value, sizeof(value));
    RegSetValueExW(key, L"BattBacklightLevel", 0, REG_DWORD, (BYTE *)&value, sizeof(value));
    RegCloseKey(key);
    event = CreateEventW(NULL, FALSE, FALSE, L"BackLightChangeEvent");
    if (event) {
        SetEvent(event);
        CloseHandle(event);
    }
    g_backlight_level = percent;
    log_line("backlight %d%% (raw %lu)", percent, value);
}

/* -------------------------------------------------------- inspection report */

static void write_report(void)
{
    WCHAR path[MAX_PATH], oem[128];
    FILE *report;
    OSVERSIONINFOW os;
    SYSTEM_INFO si;
    MEMORYSTATUS mem;
    HDC dc;
    _snwprintf(path, MAX_PATH - 1, L"%ls\\bsmd-device-info.txt", g_origin_dir);
    path[MAX_PATH - 1] = 0;
    report = _wfopen(path, L"w");
    if (!report) {
        report = _wfopen(L"\\Temp\\bsmd-device-info.txt", L"w");
        if (!report)
            return;
    }
    fprintf(report, "%s inspection report\n", CLIENT_VERSION);
    os.dwOSVersionInfoSize = sizeof(os);
    GetVersionExW(&os);
    fprintf(report, "os: Windows CE %lu.%lu build %lu (%ls)\n", os.dwMajorVersion, os.dwMinorVersion,
            os.dwBuildNumber, os.szCSDVersion);
    oem[0] = 0;
    SystemParametersInfoW(258 /* SPI_GETOEMINFO */, sizeof(oem), oem, 0);
    fprintf(report, "oem: %ls\n", oem);
    oem[0] = 0;
    SystemParametersInfoW(257 /* SPI_GETPLATFORMTYPE */, sizeof(oem), oem, 0);
    fprintf(report, "platform type: %ls\n", oem);
    GetSystemInfo(&si);
    fprintf(report, "cpu: arch %u type %lu level %u revision %u processors %lu page %lu\n",
            si.wProcessorArchitecture, si.dwProcessorType, si.wProcessorLevel, si.wProcessorRevision,
            si.dwNumberOfProcessors, si.dwPageSize);
    mem.dwLength = sizeof(mem);
    GlobalMemoryStatus(&mem);
    fprintf(report, "memory: physical %lu KB total, %lu KB free; virtual %lu KB\n",
            mem.dwTotalPhys / 1024, mem.dwAvailPhys / 1024, mem.dwTotalVirtual / 1024);
    dc = GetDC(NULL);
    fprintf(report, "screen: %dx%d, %d bpp, %d dpi\n", GetSystemMetrics(SM_CXSCREEN),
            GetSystemMetrics(SM_CYSCREEN), GetDeviceCaps(dc, BITSPIXEL), GetDeviceCaps(dc, LOGPIXELSX));
    ReleaseDC(NULL, dc);
    fprintf(report, "launched from: %ls\n", g_origin_dir);
    ufn_report(report);
    report_key(report, HKEY_LOCAL_MACHINE, L"Drivers\\USB\\FunctionDrivers", 1);
    report_key(report, HKEY_LOCAL_MACHINE, L"Drivers\\Active", 1);
    report_key(report, HKEY_CURRENT_USER, L"ControlPanel\\Backlight", 0);
    report_key(report, HKEY_LOCAL_MACHINE, L"HARDWARE\\DEVICEMAP\\TOUCH", 0);
    report_key(report, HKEY_LOCAL_MACHINE, L"Drivers\\BuiltIn\\Touch", 0);
    report_key(report, HKEY_LOCAL_MACHINE, L"System\\StorageManager\\Profiles", 1);
    report_key(report, HKEY_LOCAL_MACHINE, L"Ident", 0);
    report_key(report, HKEY_LOCAL_MACHINE, L"Platform", 0);
    fclose(report);
}

/* ---------------------------------------------------------------- output */

static int send_msg(uint8_t type, const uint8_t *payload, uint32_t len)
{
    uint8_t header[FSP_HEADER];
    DWORD written;
    int ok;
    if (g_port == INVALID_HANDLE_VALUE)
        return 0;
    EnterCriticalSection(&g_write_lock);
    fsp_header(header, type, g_tx_seq++, payload, len);
    ok = WriteFile(g_port, header, FSP_HEADER, &written, NULL) && written == FSP_HEADER;
    if (ok && len)
        ok = WriteFile(g_port, payload, len, &written, NULL) && written == len;
    LeaveCriticalSection(&g_write_lock);
    return ok;
}

static void send_touch(int kind, int x, int y)
{
    uint8_t p[12];
    if (!g_connected || !g_touch_enabled)
        return;
    p[0] = (uint8_t)kind;
    p[1] = 0;
    fsp_put16(p + 2, (uint16_t)(x < 0 ? 0 : x));
    fsp_put16(p + 4, (uint16_t)(y < 0 ? 0 : y));
    fsp_put16(p + 6, 0);
    fsp_put32(p + 8, GetTickCount());
    send_msg(FSP_TOUCH, p, 12);
}

static void send_hello_ack(void)
{
    uint8_t p[512];
    size_t n = 32;
    OSVERSIONINFOW os;
    MEMORYSTATUS mem;
    WCHAR oem[96], platform[64];
    char text[160];
    os.dwOSVersionInfoSize = sizeof(os);
    GetVersionExW(&os);
    mem.dwLength = sizeof(mem);
    GlobalMemoryStatus(&mem);
    fsp_put16(p, FSP_VERSION);
    fsp_put16(p + 2, (uint16_t)g_width);
    fsp_put16(p + 4, (uint16_t)g_height);
    fsp_put16(p + 6, 16);
    fsp_put32(p + 8, os.dwMajorVersion);
    fsp_put32(p + 12, os.dwMinorVersion);
    fsp_put32(p + 16, os.dwBuildNumber);
    fsp_put32(p + 20, mem.dwTotalPhys / 1024);
    fsp_put32(p + 24, mem.dwAvailPhys / 1024);
    p[28] = (uint8_t)g_backlight_kind;
    p[29] = (uint8_t)g_backlight_level;
    p[30] = 1;
    p[31] = (uint8_t)((g_switched_usb ? 1 : 0) | 2 /* sends FSP_CREDIT */);
    oem[0] = platform[0] = 0;
    SystemParametersInfoW(258, sizeof(oem), oem, 0);
    SystemParametersInfoW(257, sizeof(platform), platform, 0);
#define ADD_TEXT(s) do { size_t l = strlen(s); if (n + l + 1 < sizeof(p)) { memcpy(p + n, s, l + 1); n += l + 1; } } while (0)
    ADD_TEXT(CLIENT_VERSION);
    WideCharToMultiByte(CP_UTF8, 0, platform, -1, text, sizeof(text), NULL, NULL);
    ADD_TEXT(text);
    WideCharToMultiByte(CP_UTF8, 0, oem, -1, text, sizeof(text), NULL, NULL);
    ADD_TEXT(text);
    WideCharToMultiByte(CP_UTF8, 0, g_port_name, -1, text, sizeof(text), NULL, NULL);
    ADD_TEXT(text);
    WideCharToMultiByte(CP_UTF8, 0, g_prev_client, -1, text, sizeof(text), NULL, NULL);
    ADD_TEXT(text);
#undef ADD_TEXT
    send_msg(FSP_HELLO_ACK, p, (uint32_t)n);
}

/* ------------------------------------------------------------ drawing */

static void blit_box(const fsp_box *box)
{
    HDC dc;
    if (box->x1 <= box->x0 || box->y1 <= box->y0)
        return;
    dc = GetDC(g_hwnd);
    BitBlt(dc, box->x0, box->y0, box->x1 - box->x0, box->y1 - box->y0, g_memdc, box->x0, box->y0, SRCCOPY);
    ReleaseDC(g_hwnd, dc);
}

/* Waiting screen with the artwork rendered at build time (tools/make_splash.py):
 * only the live texts are drawn here. */
static void load_art(void)
{
    size_t bytes = (size_t)SPLASH_W * SPLASH_H * 2;
    if (g_width != SPLASH_W || g_height != SPLASH_H)
        return;
    g_art = (uint16_t *)malloc(bytes);
    if (g_art && fsp_inflate(splash_z, SPLASH_Z_LEN, (uint8_t *)g_art, bytes) != (long)bytes) {
        free(g_art);
        g_art = NULL;
    }
    log_line("splash artwork %s", g_art ? "loaded" : "not used");
}

static HFONT make_font(int height, int bold)
{
    LOGFONTW lf;
    memset(&lf, 0, sizeof(lf));
    lf.lfHeight = -height;
    lf.lfWeight = bold ? FW_BOLD : FW_NORMAL;
    lf.lfQuality = 5;
    wcscpy(lf.lfFaceName, L"Tahoma");
    return CreateFontIndirectW(&lf);
}

static void draw_art_splash(void)
{
    RECT r, calc;
    HFONT f_status, f_small, f_ver, old;
    fsp_box all;
    int y, line;
    EnterCriticalSection(&g_fb_lock);
    for (y = 0; y < g_height; y++)
        memcpy(g_surface.pixels + (long)y * g_surface.stride, g_art + (long)y * g_width, (size_t)g_width * 2);
    f_status = make_font(21, 1);
    f_small = make_font(13, 0);
    f_ver = make_font(13, 0);
    SetBkMode(g_memdc, TRANSPARENT);
    old = (HFONT)SelectObject(g_memdc, f_status);
    SetTextColor(g_memdc, SPLASH_TEXT);
    /* status, centred vertically in its area */
    SetRect(&calc, SPLASH_STATUS_X0, 0, SPLASH_STATUS_X1, 0);
    DrawTextW(g_memdc, g_status, -1, &calc, DT_CENTER | DT_WORDBREAK | DT_CALCRECT);
    y = (SPLASH_STATUS_Y0 + SPLASH_STATUS_Y1 - (calc.bottom - calc.top)) / 2;
    SetRect(&r, SPLASH_STATUS_X0, y, SPLASH_STATUS_X1, SPLASH_STATUS_Y1);
    DrawTextW(g_memdc, g_status, -1, &r, DT_CENTER | DT_WORDBREAK);
    SelectObject(g_memdc, f_small);
    SetTextColor(g_memdc, SPLASH_DIM);
    for (line = 0; line < DIAG_LINES; line++) {
        SetRect(&r, SPLASH_DIAG_X0, SPLASH_DIAG_Y0 + line * 15, SPLASH_DIAG_X1, SPLASH_DIAG_Y0 + (line + 1) * 15);
        DrawTextW(g_memdc, g_diag[line], -1, &r, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
    }
    SelectObject(g_memdc, f_ver);
    SetTextColor(g_memdc, SPLASH_FAINT);
    SetRect(&r, SPLASH_VERSION_X0, SPLASH_VERSION_Y0, SPLASH_VERSION_X1, SPLASH_VERSION_Y1);
    DrawTextW(g_memdc, CLIENT_VERSION_W, -1, &r, DT_RIGHT | DT_SINGLELINE | DT_VCENTER);
    SelectObject(g_memdc, old);
    DeleteObject(f_status);
    DeleteObject(f_small);
    DeleteObject(f_ver);
    SetRect(&g_exit_button, SPLASH_EXIT_X0, SPLASH_EXIT_Y0, SPLASH_EXIT_X1, SPLASH_EXIT_Y1);
    all.x0 = 0; all.y0 = 0; all.x1 = g_width; all.y1 = g_height;
    blit_box(&all);
    LeaveCriticalSection(&g_fb_lock);
}

/* Waiting screen, drawn locally while no host is connected (GDI-only fallback
 * for panels that are not 800x480). */
static void draw_splash(void)
{
    RECT r;
    if (g_art) {
        draw_art_splash();
        return;
    }
    HFONT font_big, font_small, old;
    LOGFONTW lf;
    HBRUSH bg, accent, button;
    fsp_box all;
    int w = g_width, h = g_height;
    EnterCriticalSection(&g_fb_lock);
    bg = CreateSolidBrush(RGB(16, 20, 28));
    accent = CreateSolidBrush(RGB(53, 132, 228));
    button = CreateSolidBrush(RGB(48, 56, 70));
    SetRect(&r, 0, 0, w, h);
    FillRect(g_memdc, &r, bg);
    SetRect(&r, 0, 0, w, h / 80 + 4);
    FillRect(g_memdc, &r, accent);
    memset(&lf, 0, sizeof(lf));
    lf.lfHeight = -(h / 10);
    lf.lfWeight = FW_BOLD;
    lf.lfQuality = 5; /* CLEARTYPE_QUALITY where available */
    wcscpy(lf.lfFaceName, L"Tahoma");
    font_big = CreateFontIndirectW(&lf);
    lf.lfHeight = -(h / 22);
    lf.lfWeight = FW_NORMAL;
    font_small = CreateFontIndirectW(&lf);
    SetBkMode(g_memdc, TRANSPARENT);
    SetTextColor(g_memdc, RGB(240, 244, 250));
    old = (HFONT)SelectObject(g_memdc, font_big);
    SetRect(&r, 0, h / 6, w, h / 6 + h / 7);
    DrawTextW(g_memdc, L"Big Screen Monitor", -1, &r, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
    SelectObject(g_memdc, font_small);
    SetTextColor(g_memdc, RGB(150, 190, 240));
    SetRect(&r, 0, h / 6 + h / 7, w, h / 6 + h / 7 + h / 12);
    DrawTextW(g_memdc, L"FOSTON FS-707DC Touch Display", -1, &r, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
    SetTextColor(g_memdc, RGB(220, 224, 230));
    SetRect(&r, w / 12, h * 45 / 100, w - w / 12, h * 61 / 100);
    DrawTextW(g_memdc, g_status, -1, &r, DT_CENTER | DT_WORDBREAK);
    {
        HFONT font_diag;
        int line;
        lf.lfHeight = -(h / 34);
        lf.lfWeight = FW_NORMAL;
        font_diag = CreateFontIndirectW(&lf);
        SelectObject(g_memdc, font_diag);
        SetTextColor(g_memdc, RGB(140, 200, 160));
        for (line = 0; line < DIAG_LINES; line++) {
            SetRect(&r, w / 40, h * 62 / 100 + line * (h / 30 + 2), w - w / 40, h * 62 / 100 + (line + 1) * (h / 30 + 2));
            DrawTextW(g_memdc, g_diag[line], -1, &r, DT_LEFT | DT_SINGLELINE | DT_VCENTER);   /* CE DrawText has no DT_END_ELLIPSIS */
        }
        SelectObject(g_memdc, font_small);
        DeleteObject(font_diag);
    }
    SetTextColor(g_memdc, RGB(90, 100, 115));
    SetRect(&r, w / 2, h / 80 + 6, w - w / 40, h / 80 + 6 + h / 20);
    DrawTextW(g_memdc, L"" CLIENT_VERSION_W, -1, &r, DT_RIGHT | DT_SINGLELINE | DT_VCENTER);
    /* exit button */
    SetRect(&g_exit_button, w - w / 4, h - h / 6, w - w / 40, h - h / 30);
    FillRect(g_memdc, &g_exit_button, button);
    SetTextColor(g_memdc, RGB(255, 255, 255));
    DrawTextW(g_memdc, L"Sair", -1, &g_exit_button, DT_CENTER | DT_SINGLELINE | DT_VCENTER);
    SetTextColor(g_memdc, RGB(120, 130, 145));
    SetRect(&r, w / 40, h - h / 6, w - w / 4 - w / 40, h - h / 30);
    DrawTextW(g_memdc, L"Conecte o cabo USB ao computador com o BigLinux", -1, &r,
              DT_LEFT | DT_SINGLELINE | DT_VCENTER);
    SelectObject(g_memdc, old);
    DeleteObject(font_big);
    DeleteObject(font_small);
    DeleteObject(bg);
    DeleteObject(accent);
    DeleteObject(button);
    all.x0 = 0; all.y0 = 0; all.x1 = w; all.y1 = h;
    blit_box(&all);
    LeaveCriticalSection(&g_fb_lock);
}

static void set_status(const WCHAR *text)
{
    wcsncpy(g_status, text, 159);
    g_status[159] = 0;
    if (g_hwnd)
        PostMessageW(g_hwnd, WM_APP_STATUS, 0, 0);
}

static int create_surface(void)
{
    struct {
        BITMAPINFOHEADER h;
        DWORD masks[3];
    } bmi;
    void *bits = NULL;
    HDC dc = GetDC(NULL);
    memset(&bmi, 0, sizeof(bmi));
    bmi.h.biSize = sizeof(BITMAPINFOHEADER);
    bmi.h.biWidth = g_width;
    bmi.h.biHeight = -g_height;            /* top-down */
    bmi.h.biPlanes = 1;
    bmi.h.biBitCount = 16;
    bmi.h.biCompression = BI_BITFIELDS;
    bmi.masks[0] = 0xF800;
    bmi.masks[1] = 0x07E0;
    bmi.masks[2] = 0x001F;
    g_dib = CreateDIBSection(dc, (BITMAPINFO *)&bmi, DIB_RGB_COLORS, &bits, NULL, 0);
    g_surface.width = g_width;
    g_surface.height = g_height;
    if (g_dib) {
        g_surface.pixels = (uint16_t *)bits;
        g_surface.stride = ((g_width * 2 + 3) & ~3) / 2;
    } else {
        bmi.h.biHeight = g_height;         /* bottom-up fallback */
        g_dib = CreateDIBSection(dc, (BITMAPINFO *)&bmi, DIB_RGB_COLORS, &bits, NULL, 0);
        if (!g_dib) {
            ReleaseDC(NULL, dc);
            return 0;
        }
        g_surface.stride = -(((g_width * 2 + 3) & ~3) / 2);
        g_surface.pixels = (uint16_t *)bits + (long)(g_height - 1) * -g_surface.stride;
    }
    g_memdc = CreateCompatibleDC(dc);
    g_olddib = (HBITMAP)SelectObject(g_memdc, g_dib);
    ReleaseDC(NULL, dc);
    log_line("surface %dx%d %s", g_width, g_height, g_surface.stride > 0 ? "top-down" : "bottom-up");
    return 1;
}

/* -------------------------------------------------------- comm thread */

static void kill_activesync(void)
{
    /* ActiveSync (repllog.exe) grabs the USB serial port when it appears. */
    typedef HANDLE (WINAPI *Snap_t)(DWORD, DWORD);
    typedef BOOL (WINAPI *Walk_t)(HANDLE, void *);
    typedef BOOL (WINAPI *Close_t)(HANDLE);
    struct {
        DWORD dwSize, cntUsage, th32ProcessID, th32DefaultHeapID, th32ModuleID, cntThreads, th32ParentProcessID;
        LONG pcPriClassBase;
        DWORD dwFlags;
        WCHAR szExeFile[MAX_PATH];
        DWORD th32MemoryBase, th32AccessKey;
    } pe;
    HMODULE th = LoadLibraryW(L"toolhelp.dll");
    Snap_t snap;
    Walk_t first, next;
    Close_t close_snap;
    HANDLE s;
    BOOL more;
    if (!th)
        return;
    snap = (Snap_t)GetProcAddressW(th, L"CreateToolhelp32Snapshot");
    first = (Walk_t)GetProcAddressW(th, L"Process32First");
    next = (Walk_t)GetProcAddressW(th, L"Process32Next");
    close_snap = (Close_t)GetProcAddressW(th, L"CloseToolhelp32Snapshot");
    if (!snap || !first || !next)
        goto done;
    s = snap(2 /* TH32CS_SNAPPROCESS */, 0);
    if (s == INVALID_HANDLE_VALUE)
        goto done;
    pe.dwSize = sizeof(pe);
    for (more = first(s, &pe); more; more = next(s, &pe)) {
        if (!_wcsicmp(pe.szExeFile, L"repllog.exe") || !_wcsicmp(pe.szExeFile, L"rapiclnt.exe")) {
            HANDLE p = OpenProcess(0, FALSE, pe.th32ProcessID);
            if (p) {
                log_line("terminating %ls (holds the USB serial port)", pe.szExeFile);
                TerminateProcess(p, 0);
                CloseHandle(p);
            }
        }
        pe.dwSize = sizeof(pe);
    }
    if (close_snap)
        close_snap(s);
done:
    FreeLibrary(th);
}

static HANDLE open_port(const WCHAR *name)
{
    HANDLE h = CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
    DCB dcb;
    COMMTIMEOUTS t;
    if (h == INVALID_HANDLE_VALUE)
        return h;
    memset(&dcb, 0, sizeof(dcb));
    dcb.DCBlength = sizeof(dcb);
    if (GetCommState(h, &dcb)) {
        dcb.BaudRate = 115200;          /* meaningless on USB, set for drivers that check it */
        dcb.ByteSize = 8;
        dcb.Parity = NOPARITY;
        dcb.StopBits = ONESTOPBIT;
        dcb.fOutxCtsFlow = FALSE;
        dcb.fOutxDsrFlow = FALSE;
        dcb.fDtrControl = DTR_CONTROL_ENABLE;
        dcb.fRtsControl = RTS_CONTROL_ENABLE;
        dcb.fOutX = dcb.fInX = FALSE;
        SetCommState(h, &dcb);
    }
    /* Return at once with whatever arrived: the Serial_Class driver of the
     * FS-707DC only completes a blocking read at its timeout and drops what
     * does not fit its small internal buffer meanwhile (measured: messages
     * above ~1 KB were lost with a 250 ms read timeout). */
    t.ReadIntervalTimeout = MAXDWORD;
    t.ReadTotalTimeoutMultiplier = 0;
    t.ReadTotalTimeoutConstant = 0;
    t.WriteTotalTimeoutMultiplier = 0;
    t.WriteTotalTimeoutConstant = 2000;
    SetCommTimeouts(h, &t);
    SetupComm(h, 64 * 1024, 64 * 1024);
    return h;
}

static void handle_message(const fsp_msg *m, fsp_box *dirty, DWORD *decode_ms)
{
    uint8_t reply[12];
    switch (m->type) {
    case FSP_HELLO: {
        int i, n = 0;
        if (m->len > 4) {
            n = MultiByteToWideChar(CP_UTF8, 0, (const char *)m->payload + 4, (int)m->len - 4, g_host, 63);
        }
        g_host[n > 0 ? n : 0] = 0;
        for (i = 0; g_host[i]; i++)
            if (g_host[i] < 32)
                g_host[i] = L'?';
        dirty->x0 = dirty->x1 = dirty->y0 = dirty->y1 = 0;
        InterlockedExchange(&g_connected, 1);
        send_hello_ack();
        log_line("host hello: %ls", g_host);
        break;
    }
    case FSP_PING:
        if (m->len >= 4) {
            memcpy(reply, m->payload, 4);
            fsp_put32(reply + 4, GetTickCount());
            send_msg(FSP_PONG, reply, 8);
        }
        break;
    case FSP_RECT:
    case FSP_FILL: {
        DWORD start = GetTickCount();
        int err;
        EnterCriticalSection(&g_fb_lock);
        err = fsp_apply(&g_surface, m->type, m->payload, m->len, g_scratch, g_scratch_len, dirty);
        LeaveCriticalSection(&g_fb_lock);
        *decode_ms += GetTickCount() - start;
        if (err) {
            fsp_put16(reply, m->seq);
            reply[2] = (uint8_t)err;
            send_msg(FSP_NAK, reply, 3);
        }
        break;
    }
    case FSP_PRESENT: {
        DWORD start = GetTickCount();
        if (m->len < 4)
            break;
        EnterCriticalSection(&g_fb_lock);
        blit_box(dirty);
        LeaveCriticalSection(&g_fb_lock);
        dirty->x0 = dirty->x1 = dirty->y0 = dirty->y1 = 0;
        memcpy(reply, m->payload, 4);
        fsp_put32(reply + 4, *decode_ms);
        fsp_put32(reply + 8, GetTickCount() - start);
        *decode_ms = 0;
        send_msg(FSP_PRESENTED, reply, 12);
        break;
    }
    case FSP_BRIGHTNESS:
        if (m->len >= 1)
            backlight_set(m->payload[0]);
        break;
    case FSP_CALIBRATE:
        PostMessageW(g_hwnd, WM_APP_CALIBRATE, 0, 0);
        break;
    case FSP_TOUCHCFG:
        if (m->len >= 1)
            InterlockedExchange(&g_touch_enabled, m->payload[0] ? 1 : 0);
        if (m->len >= 2 && m->payload[1])
            g_move_interval = m->payload[1];
        break;
    case FSP_BYE:
        InterlockedExchange(&g_connected, 0);
        if (m->len >= 1 && m->payload[0] == 1) {
            PostMessageW(g_hwnd, WM_CLOSE, 0, 0);
        } else {
            set_status(L"O computador desconectou. Aguardando...");
        }
        break;
    default:
        fsp_put16(reply, m->seq);
        reply[2] = FSP_NAK_UNKNOWN;
        send_msg(FSP_NAK, reply, 3);
        break;
    }
}

/* Reader thread: drains the port continuously into a ring buffer so the
 * driver never overflows while the main comm thread decodes frames. */
#define RING_SIZE (2u * 1024u * 1024u)
#define READ_REQUEST 512
static uint8_t *g_ring;
static volatile DWORD g_ring_head, g_ring_tail;   /* head: written by reader, tail: by decoder */
static HANDLE g_ring_event;
static volatile LONG g_reader_alive;

static DWORD WINAPI reader_thread(LPVOID arg)
{
    HANDLE port = (HANDLE)arg;
    uint8_t tmp[READ_REQUEST];
    DWORD idle = 0;
    while (!g_quit && !g_quit_reader) {
        DWORD got = 0, i;
        if (!ReadFile(port, tmp, sizeof(tmp), &got, NULL)) {
            log_line("read failed: %lu", GetLastError());
            break;
        }
        if (!got) {
            Sleep(idle++ > 2000 ? 5 : 1);
            continue;
        }
        idle = 0;
        for (i = 0; i < got;) {
            DWORD head = g_ring_head, tail = g_ring_tail;
            DWORD room = (tail + RING_SIZE - head - 1) % RING_SIZE, n;
            if (!room) {                   /* host ignored the credit window: wait, never drop */
                Sleep(1);
                continue;
            }
            n = got - i;
            if (n > room)
                n = room;
            if (n > RING_SIZE - head)
                n = RING_SIZE - head;
            memcpy(g_ring + head, tmp + i, n);
            g_ring_head = (head + n) % RING_SIZE;
            i += n;
        }
        SetEvent(g_ring_event);
    }
    InterlockedExchange(&g_reader_alive, 0);
    SetEvent(g_ring_event);
    return 0;
}

#define CREDIT_STEP (8u * 1024u)
#define STALL_MS 1000
/* The host sends a frame or a PING at least every 15 s while it drives the
 * panel; after this much silence the frame on the glass is stale (service
 * stopped, computer suspended, process killed): show the waiting screen. */
#define HOST_SILENCE_MS 30000

static void send_credit(uint32_t consumed)
{
    uint8_t p[4];
    fsp_put32(p, consumed);
    send_msg(FSP_CREDIT, p, 4);
}

static void comm_session(void)
{
    fsp_parser parser;
    fsp_box dirty = {0, 0, 0, 0};
    DWORD decode_ms = 0, last_data = GetTickCount(), last_msg = GetTickCount();
    uint32_t consumed = 0, credited = 0;     /* bytes of whole messages handled since HELLO */
    HANDLE reader;
    g_ring_head = g_ring_tail = 0;
    InterlockedExchange(&g_reader_alive, 1);
    reader = CreateThread(NULL, 0, reader_thread, (LPVOID)g_port, 0, NULL);
    if (!reader)
        return;
    CeSetThreadPriority_t set_prio = (CeSetThreadPriority_t)core_proc(L"CeSetThreadPriority");
    if (set_prio)
        set_prio(reader, 200);             /* well above applications (251) and GDI work: the Serial_Class
                                              driver drops bytes when nobody drains it (it sleeps when idle) */
    fsp_parser_init(&parser, g_rx_buf, FSP_HEADER + FSP_MAX_PAYLOAD);
    while (!g_quit && g_reader_alive) {
        DWORD head = g_ring_head, tail = g_ring_tail;
        if (head == tail) {
            if (g_connected && GetTickCount() - last_msg > HOST_SILENCE_MS) {
                log_line("host silent for %u ms: back to the waiting screen", (unsigned)HOST_SILENCE_MS);
                InterlockedExchange(&g_connected, 0);
                set_status(L"O computador parou de enviar dados.\nAguardando o Big Screen Monitor...");
            }
            if (parser.used && GetTickCount() - last_data > STALL_MS) {
                /* a partial message that will never complete: resynchronise */
                uint8_t nak[3];
                log_line("stalled partial message (%u bytes): resync", (unsigned)parser.used);
                fsp_put16(nak, 0xFFFF);
                nak[2] = FSP_NAK_RESYNC;
                send_msg(FSP_NAK, nak, 3);
                parser.used = 0;
            }
            WaitForSingleObject(g_ring_event, 200);
            continue;
        }
        last_data = GetTickCount();
        while (tail != head) {
            DWORD n = head > tail ? head - tail : RING_SIZE - tail;
            fsp_msg m;
            int r;
            n = (DWORD)fsp_feed(&parser, g_ring + tail, n);
            tail = (tail + n) % RING_SIZE;
            g_ring_tail = tail;
            while ((r = fsp_next(&parser, &m)) != FSP_NEED_MORE) {
                if (r == FSP_BAD_CRC) {
                    uint8_t nak[3];
                    fsp_put16(nak, m.seq);
                    nak[2] = FSP_NAK_CRC;
                    send_msg(FSP_NAK, nak, 3);
                    continue;
                }
                last_msg = GetTickCount();
                if (m.type == FSP_HELLO) {
                    consumed = credited = 0;
                } else {
                    consumed += FSP_HEADER + m.len;
                }
                handle_message(&m, &dirty, &decode_ms);
                fsp_consume(&parser);
                if (consumed - credited >= CREDIT_STEP || (m.type == FSP_PRESENT && consumed != credited)) {
                    credited = consumed;
                    send_credit(consumed);
                }
            }
        }
    }
    InterlockedExchange(&g_quit_reader, 1);
    WaitForSingleObject(reader, 1000);
    CloseHandle(reader);
}

static DWORD WINAPI comm_thread(LPVOID unused)
{
    (void)unused;
    g_ring = (uint8_t *)malloc(RING_SIZE);
    g_ring_event = CreateEventW(NULL, FALSE, FALSE, NULL);
    if (!g_ring || !g_ring_event) {
        set_status(L"Sem memoria para o buffer de recepcao.");
        return 1;
    }
    while (!g_quit) {
        WCHAR status[160];
        if (!ensure_serial_client())
            log_line("usb function switching unavailable; waiting for a serial port anyway");
        if (!find_usb_serial_port(g_port_name, 16)) {
            set_status(L"Aguardando a porta USB serial...\nConecte o cabo USB.");
            Sleep(1500);
            continue;
        }
        g_port = open_port(g_port_name);
        if (g_port == INVALID_HANDLE_VALUE) {
            DWORD err = GetLastError();
            log_line("open %ls failed: %lu", g_port_name, err);
            kill_activesync();
            _snwprintf(status, 159, L"Porta %ls ocupada (erro %lu). Tentando novamente...", g_port_name, err);
            status[159] = 0;
            set_status(status);
            Sleep(1500);
            continue;
        }
        log_line("port %ls open", g_port_name);
        _snwprintf(status, 159, L"Conectado via USB (%ls).\nAguardando o Big Screen Monitor no computador...",
                   g_port_name);
        status[159] = 0;
        set_status(status);
        InterlockedExchange(&g_quit_reader, 0);
        comm_session();
        EnterCriticalSection(&g_write_lock);
        CloseHandle(g_port);
        g_port = INVALID_HANDLE_VALUE;
        LeaveCriticalSection(&g_write_lock);
        if (g_connected) {
            InterlockedExchange(&g_connected, 0);
            set_status(L"Conexão perdida. Reconectando...");
        }
        Sleep(500);
    }
    return 0;
}

/* ------------------------------------------------------------- window */

static void quit_client(void)
{
    InterlockedExchange(&g_quit, 1);
    DestroyWindow(g_hwnd);
}

static LRESULT CALLBACK wnd_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    int x = (short)LOWORD(lp), y = (short)HIWORD(lp);
    switch (msg) {
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        EnterCriticalSection(&g_fb_lock);
        BitBlt(dc, ps.rcPaint.left, ps.rcPaint.top, ps.rcPaint.right - ps.rcPaint.left,
               ps.rcPaint.bottom - ps.rcPaint.top, g_memdc, ps.rcPaint.left, ps.rcPaint.top, SRCCOPY);
        LeaveCriticalSection(&g_fb_lock);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_ERASEBKGND:
        return 1;
    case WM_LBUTTONDOWN:
        SetCapture(hwnd);
        if (!g_connected) {
            POINT pt;
            pt.x = x; pt.y = y;
            if (PtInRect(&g_exit_button, pt)) {
                quit_client();
                return 0;
            }
        }
        if (x < CORNER && y < CORNER)
            g_corner_since = GetTickCount();
        g_last_move = GetTickCount();
        g_last_x = x;
        g_last_y = y;
        send_touch(FSP_TOUCH_DOWN, x, y);
        return 0;
    case WM_MOUSEMOVE:
        if (wp & MK_LBUTTON) {
            DWORD now = GetTickCount();
            if (!(x < CORNER && y < CORNER))
                g_corner_since = 0;
            if (now - g_last_move >= g_move_interval && (abs(x - g_last_x) > 1 || abs(y - g_last_y) > 1)) {
                g_last_move = now;
                g_last_x = x;
                g_last_y = y;
                send_touch(FSP_TOUCH_MOVE, x, y);
            }
        }
        return 0;
    case WM_LBUTTONUP:
        ReleaseCapture();
        g_corner_since = 0;
        send_touch(FSP_TOUCH_UP, x, y);
        return 0;
    case WM_KEYDOWN:
    case WM_KEYUP: {
        uint8_t p[3];
        if (g_connected) {
            fsp_put16(p, (uint16_t)wp);
            p[2] = msg == WM_KEYDOWN;
            send_msg(FSP_KEY, p, 3);
        }
        return 0;
    }
    case WM_TIMER:
        if (wp == TIMER_KEEPALIVE && p_idle_reset)
            p_idle_reset();
        if (wp == TIMER_CORNER && g_corner_since && GetTickCount() - g_corner_since >= CORNER_HOLD_MS) {
            log_line("exit gesture");
            quit_client();
        }
        return 0;
    case WM_APP_STATUS:
        if (!g_connected)
            draw_splash();
        return 0;
    case WM_APP_CALIBRATE: {
        TouchCalibrate_t calibrate = (TouchCalibrate_t)core_proc(L"TouchCalibrate");
        log_line("touch calibration: %s", calibrate ? "starting" : "not available");
        if (calibrate)
            calibrate();
        SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, g_width, g_height, SWP_SHOWWINDOW);
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;
    }
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

/* Run from RAM so the storage card / USB storage can go away under us. */
static int relocate(const WCHAR *self)
{
    WCHAR target[MAX_PATH], args[MAX_PATH + 16];
    PROCESS_INFORMATION pi;
    if (!_wcsnicmp(self, L"\\Temp\\", 6))
        return 0;
    CreateDirectoryW(L"\\Temp", NULL);
    wcscpy(target, L"\\Temp\\bsmd-ce.exe");
    if (!CopyFileW(self, target, FALSE))
        return 0;
    _snwprintf(args, MAX_PATH + 15, L"/from \"%ls\"", g_origin_dir);
    args[MAX_PATH + 15] = 0;
    if (!CreateProcessW(target, args, NULL, NULL, FALSE, 0, NULL, NULL, NULL, &pi))
        return 0;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 1;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPWSTR cmd, int show)
{
    WCHAR self[MAX_PATH], *slash, *from;
    WNDCLASSW wc;
    MSG msg;
    HWND taskbar, other;
    HANDLE thread;
    (void)prev;
    (void)show;
    g_inst = inst;

    other = FindWindowW(L"BSMDClient", NULL);
    if (other) {                         /* single instance */
        SetForegroundWindow(other);
        return 0;
    }

    GetModuleFileNameW(NULL, self, MAX_PATH);
    wcscpy(g_origin_dir, self);
    slash = wcsrchr(g_origin_dir, L'\\');
    if (slash)
        *slash = 0;
    from = cmd ? wcsstr(cmd, L"/from \"") : NULL;
    if (from) {
        WCHAR *end;
        wcsncpy(g_origin_dir, from + 7, MAX_PATH - 1);
        g_origin_dir[MAX_PATH - 1] = 0;
        end = wcschr(g_origin_dir, L'"');
        if (end)
            *end = 0;
    } else if (!(cmd && wcsstr(cmd, L"/norelocate")) && relocate(self)) {
        return 0;
    }

    g_log = _wfopen(L"\\Temp\\bsmd-ce.log", L"w");
    log_line("%s starting from %ls (origin %ls)", CLIENT_VERSION, self, g_origin_dir);

    InitializeCriticalSection(&g_fb_lock);
    InitializeCriticalSection(&g_write_lock);
    g_width = GetSystemMetrics(SM_CXSCREEN);
    g_height = GetSystemMetrics(SM_CYSCREEN);
    g_scratch_len = (size_t)g_width * g_height * 2;
    g_scratch = (uint8_t *)malloc(g_scratch_len);
    g_rx_buf = (uint8_t *)malloc(FSP_HEADER + FSP_MAX_PAYLOAD);
    if (!g_scratch || !g_rx_buf || !create_surface()) {
        log_line("out of memory");
        return 1;
    }
    load_art();
    backlight_probe();
    write_report();
    keep_awake_init();

    memset(&wc, 0, sizeof(wc));
    wc.lpfnWndProc = wnd_proc;
    wc.hInstance = inst;
    wc.lpszClassName = L"BSMDClient";
    RegisterClassW(&wc);
    g_hwnd = CreateWindowExW(WS_EX_TOPMOST, L"BSMDClient", L"Big Screen Monitor", WS_VISIBLE | WS_POPUP,
                             0, 0, g_width, g_height, NULL, NULL, inst, NULL);
    if (!g_hwnd)
        return 1;
    taskbar = FindWindowW(L"HHTaskBar", NULL);
    if (taskbar)
        ShowWindow(taskbar, SW_HIDE);
    SetForegroundWindow(g_hwnd);
    draw_splash();
    SetTimer(g_hwnd, TIMER_KEEPALIVE, 4000, NULL);
    SetTimer(g_hwnd, TIMER_CORNER, 250, NULL);

    thread = CreateThread(NULL, 0, comm_thread, NULL, 0, NULL);
    while (GetMessageW(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    InterlockedExchange(&g_quit, 1);
    if (g_port != INVALID_HANDLE_VALUE) {
        uint8_t mode = 1;
        send_msg(FSP_BYE, &mode, 1);
        /* unblock ReadFile */
        EnterCriticalSection(&g_write_lock);
        CloseHandle(g_port);
        g_port = INVALID_HANDLE_VALUE;
        LeaveCriticalSection(&g_write_lock);
    }
    if (thread) {
        WaitForSingleObject(thread, 2000);
        CloseHandle(thread);
    }
    restore_usb_client();
    keep_awake_done();
    if (taskbar)
        ShowWindow(taskbar, SW_SHOW);
    log_line("bye");
    if (g_log)
        fclose(g_log);
    return 0;
}
