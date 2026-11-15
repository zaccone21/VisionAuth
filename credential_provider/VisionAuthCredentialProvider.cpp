// VisionAuth credential provider.
//
// Loaded by LogonUI.exe (as SYSTEM) on the sign-in and lock screens. A
// background thread asks the VisionAuth service, over the \\.\pipe\VisionAuth
// named pipe, whether it has just verified the owner's face. When it has, the
// provider tells LogonUI that its credential wants to log on automatically, and
// GetSerialization hands LogonUI the owner's stored Windows credentials.
//
// The credentials live in an LSA private data object ("L$VisionAuthCredential",
// readable only by SYSTEM and administrators) written by scripts/set_password.py,
// as UTF-16 text: "<user SID>\n<domain>\n<user name>\n<password>".
//
// Safety rules for code running inside LogonUI: no C++ exceptions, every COM
// method returns an HRESULT, and the polling thread is always stopped before
// the provider goes away.

#define WIN32_LEAN_AND_MEAN
#define SECURITY_WIN32
#define _WIN32_WINNT 0x0A00
#define NTDDI_VERSION 0x0A000000
#include <windows.h>
#include <initguid.h>
#include <credentialprovider.h>
#include <ntsecapi.h>
#include <powersetting.h>
#include <powrprof.h>
#include <security.h>
#include <shlguid.h>
#include <shlwapi.h>
#include <wchar.h>

#include <new>

#include "island.h"

#ifndef STATUS_SUCCESS
#define STATUS_SUCCESS ((NTSTATUS)0x00000000L)
#endif

// {AF1032B6-3657-4B4C-B230-7237F0183A6C}
DEFINE_GUID(CLSID_VisionAuthProvider, 0xaf1032b6, 0x3657, 0x4b4c, 0xb2, 0x30, 0x72, 0x37, 0xf0, 0x18, 0x3a, 0x6c);

#ifdef VISIONAUTH_TEST_PIPE
// Test builds talk to the harness, never to an installed service
static const wchar_t kPipeName[] = L"\\\\.\\pipe\\VisionAuthHarness";
#else
static const wchar_t kPipeName[] = L"\\\\.\\pipe\\VisionAuth";
#endif
static const wchar_t kSecretName[] = L"L$VisionAuthCredential";
static const DWORD kPollIntervalMs = 200;
static const UINT WM_VISIONAUTH_PHASE = WM_APP + 1;
static const UINT_PTR kLogonTimer = 7;
static const UINT kMatchDelayMs = 450;
static const UINT kDisplayRecheckMs = 100;
// After the PC wakes up or the screen turns on, an external monitor takes a
// few seconds to show the picture. A verified face waits this long after
// either, so the sign-in screen is seen before it goes away. It can be
// changed with the DWORD DisplaySettleMs under HKLM\SOFTWARE\VisionAuth.
static const DWORD kDefaultDisplaySettleMs = 4000;
static const wchar_t kSettingsKey[] = L"SOFTWARE\\VisionAuth";
static const wchar_t kWindowClass[] = L"VisionAuthCredentialProviderWindow";

static LONG g_dllRefs = 0;
static HINSTANCE g_module = nullptr;

static void DllAddRef() { InterlockedIncrement(&g_dllRefs); }
static void DllRelease() { InterlockedDecrement(&g_dllRefs); }

// ---------------------------------------------------------------------------
// Fields shown on the tile

enum FieldId { FI_LOGO = 0, FI_LABEL, FI_STATUS, FI_COUNT };

static const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR kFields[FI_COUNT] = {
    {FI_LOGO, CPFT_TILE_IMAGE, const_cast<LPWSTR>(L"VisionAuth"), CPFG_CREDENTIAL_PROVIDER_LOGO},
    {FI_LABEL, CPFT_LARGE_TEXT, const_cast<LPWSTR>(L"VisionAuth"), CPFG_CREDENTIAL_PROVIDER_LABEL},
    {FI_STATUS, CPFT_SMALL_TEXT, const_cast<LPWSTR>(L"Estado"), {}},
};

static const CREDENTIAL_PROVIDER_FIELD_STATE kFieldStates[FI_COUNT] = {
    CPFS_DISPLAY_IN_BOTH,
    CPFS_DISPLAY_IN_BOTH,
    CPFS_DISPLAY_IN_SELECTED_TILE,
};

// ---------------------------------------------------------------------------
// State shared between the provider, its credential and the polling thread

// What the service is doing, shown on the tile
enum Phase : LONG {
    PH_OFFLINE = 0,   // the service does not answer
    PH_STARTING,      // opening the camera
    PH_SEARCHING,     // no face in view
    PH_FACE,          // a face is in view, verifying
    PH_UNRECOGNIZED,  // a face was in view but did not match
    PH_MATCH,         // verified: logging on
    PH_AWAY = 7,      // nobody in view for a while: waiting, greyed out (6 is the island's "blocked")
};

struct SharedState {
    LONG refs = 1;
    LONG pending = 0;   // the service verified the owner; log on at the next chance
    LONG blocked = 0;   // a logon with the stored password failed: stop until the next lock
    LONG phase = PH_STARTING;
    wchar_t name[64] = L"";  // greeting name sent with MATCH
    CREDENTIAL_PROVIDER_USAGE_SCENARIO scenario = CPUS_INVALID;

    void AddRef() { InterlockedIncrement(&refs); }
    void Release() {
        if (InterlockedDecrement(&refs) == 0) delete this;
    }
};

// ---------------------------------------------------------------------------
// Talking to the service

// True when the pipe server process runs as LocalSystem, so a program run by
// a normal user cannot pretend to be the service.
static bool PipeServerIsSystem(HANDLE pipe) {
#ifdef VISIONAUTH_ALLOW_ANY_PIPE_SERVER
    (void)pipe;
    return true;
#else
    ULONG pid = 0;
    if (!GetNamedPipeServerProcessId(pipe, &pid)) return false;
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!process) return false;
    bool isSystem = false;
    HANDLE token = nullptr;
    if (OpenProcessToken(process, TOKEN_QUERY, &token)) {
        BYTE buffer[256];
        DWORD size = 0;
        if (GetTokenInformation(token, TokenUser, buffer, sizeof(buffer), &size)) {
            isSystem = IsWellKnownSid(reinterpret_cast<TOKEN_USER*>(buffer)->User.Sid, WinLocalSystemSid) != FALSE;
        }
        CloseHandle(token);
    }
    CloseHandle(process);
    return isSystem;
#endif
}

// Maps a service reply ("MATCH <user>" or "STATE <phase>") to a Phase.
static Phase ParseReply(const char* reply) {
    if (strncmp(reply, "MATCH", 5) == 0) return PH_MATCH;
    if (strncmp(reply, "STATE ", 6) != 0) return PH_SEARCHING;
    const char* phase = reply + 6;
    if (strncmp(phase, "starting", 8) == 0) return PH_STARTING;
    if (strncmp(phase, "face", 4) == 0 || strncmp(phase, "verified", 8) == 0) return PH_FACE;
    if (strncmp(phase, "unrecognized", 12) == 0) return PH_UNRECOGNIZED;
    if (strncmp(phase, "away", 4) == 0) return PH_AWAY;
    return PH_SEARCHING;
}

// Asks the service once. On MATCH, copies the greeting name into name.
static Phase AskService(wchar_t* name, int capacity) {
    HANDLE pipe = INVALID_HANDLE_VALUE;
    for (int attempt = 0; attempt < 3 && pipe == INVALID_HANDLE_VALUE; ++attempt) {
        pipe = CreateFileW(kPipeName, GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING,
                           SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) {
            DWORD error = GetLastError();
            if (error == ERROR_PIPE_BUSY) {
                WaitNamedPipeW(kPipeName, 200);
            } else if (error == ERROR_FILE_NOT_FOUND) {
                Sleep(20);  // the single instance is being recreated
            } else {
                return PH_OFFLINE;
            }
        }
    }
    if (pipe == INVALID_HANDLE_VALUE) return PH_OFFLINE;

    Phase phase = PH_OFFLINE;
    if (PipeServerIsSystem(pipe)) {
        static const char request[] = "STATUS\n";
        DWORD written = 0;
        if (WriteFile(pipe, request, sizeof(request) - 1, &written, nullptr)) {
            char reply[256] = {};
            DWORD read = 0;
            if (ReadFile(pipe, reply, sizeof(reply) - 1, &read, nullptr) && read >= 5) {
                phase = ParseReply(reply);
                if (phase == PH_MATCH && name) {
                    // "MATCH <name>" followed by a newline, in UTF-8
                    char* text = reply + 5;
                    while (*text == ' ') ++text;
                    char* stop = text;
                    while (*stop && *stop != '\r' && *stop != '\n') ++stop;
                    int length = MultiByteToWideChar(CP_UTF8, 0, text, static_cast<int>(stop - text), name,
                                                     capacity - 1);
                    name[length > 0 ? length : 0] = L'\0';
                }
            }
        }
    }
    CloseHandle(pipe);
    return phase;
}

// ---------------------------------------------------------------------------
// Stored credentials

struct StoredCredential {
    wchar_t sid[192];
    wchar_t domain[256];
    wchar_t user[256];
    wchar_t password[256];

    void Wipe() { SecureZeroMemory(this, sizeof(*this)); }
};

static void InitLsaString(LSA_UNICODE_STRING* target, const wchar_t* text) {
    USHORT bytes = static_cast<USHORT>(wcslen(text) * sizeof(wchar_t));
    target->Buffer = const_cast<PWSTR>(text);
    target->Length = bytes;
    target->MaximumLength = static_cast<USHORT>(bytes + sizeof(wchar_t));
}

// Copies the next '\n'-terminated field of [cursor, end) into out.
static bool NextField(const wchar_t*& cursor, const wchar_t* end, wchar_t* out, size_t capacity, bool last) {
    const wchar_t* stop = cursor;
    while (stop < end && *stop != L'\n') ++stop;
    if (!last && stop == end) return false;
    if (last) stop = end;
    size_t length = static_cast<size_t>(stop - cursor);
    if (length == 0 || length >= capacity) return false;
    wmemcpy(out, cursor, length);
    out[length] = L'\0';
    cursor = (stop < end) ? stop + 1 : end;
    return true;
}

static bool ReadStoredCredential(StoredCredential* out) {
    ZeroMemory(out, sizeof(*out));
    LSA_OBJECT_ATTRIBUTES attributes = {};
    LSA_HANDLE policy = nullptr;
    if (LsaOpenPolicy(nullptr, &attributes, POLICY_GET_PRIVATE_INFORMATION, &policy) != STATUS_SUCCESS) return false;

    LSA_UNICODE_STRING key;
    InitLsaString(&key, kSecretName);
    PLSA_UNICODE_STRING data = nullptr;
    NTSTATUS status = LsaRetrievePrivateData(policy, &key, &data);
    LsaClose(policy);
    if (status != STATUS_SUCCESS || data == nullptr) return false;

    const wchar_t* cursor = data->Buffer;
    const wchar_t* end = data->Buffer + data->Length / sizeof(wchar_t);
    bool ok = NextField(cursor, end, out->sid, ARRAYSIZE(out->sid), false) &&
              NextField(cursor, end, out->domain, ARRAYSIZE(out->domain), false) &&
              NextField(cursor, end, out->user, ARRAYSIZE(out->user), false) &&
              NextField(cursor, end, out->password, ARRAYSIZE(out->password), true);

    SecureZeroMemory(data->Buffer, data->Length);
    LsaFreeMemory(data);
    if (!ok) out->Wipe();
    return ok;
}

// Builds the KERB_INTERACTIVE_UNLOCK_LOGON that LogonUI hands to LSA: the
// structure followed by its strings, with each Buffer pointer replaced by its
// offset from the start of the block.
static HRESULT PackLogon(const StoredCredential& credential, CREDENTIAL_PROVIDER_USAGE_SCENARIO scenario,
                         BYTE** packed, ULONG* packedSize) {
    const wchar_t* texts[3] = {credential.domain, credential.user, credential.password};
    USHORT lengths[3];
    ULONG size = sizeof(KERB_INTERACTIVE_UNLOCK_LOGON);
    for (int i = 0; i < 3; ++i) {
        lengths[i] = static_cast<USHORT>(wcslen(texts[i]) * sizeof(wchar_t));
        size += lengths[i];
    }

    BYTE* block = static_cast<BYTE*>(CoTaskMemAlloc(size));
    if (!block) return E_OUTOFMEMORY;
    ZeroMemory(block, size);

    auto* logon = reinterpret_cast<KERB_INTERACTIVE_UNLOCK_LOGON*>(block);
    logon->Logon.MessageType =
        (scenario == CPUS_UNLOCK_WORKSTATION) ? KerbWorkstationUnlockLogon : KerbInteractiveLogon;
    UNICODE_STRING* targets[3] = {&logon->Logon.LogonDomainName, &logon->Logon.UserName, &logon->Logon.Password};

    BYTE* cursor = block + sizeof(KERB_INTERACTIVE_UNLOCK_LOGON);
    for (int i = 0; i < 3; ++i) {
        targets[i]->Length = lengths[i];
        targets[i]->MaximumLength = lengths[i];
        targets[i]->Buffer = reinterpret_cast<PWSTR>(cursor - block);
        CopyMemory(cursor, texts[i], lengths[i]);
        cursor += lengths[i];
    }
    *packed = block;
    *packedSize = size;
    return S_OK;
}

static HRESULT LookupNegotiatePackage(ULONG* package) {
    HANDLE lsa = nullptr;
    if (LsaConnectUntrusted(&lsa) != STATUS_SUCCESS) return E_FAIL;
    LSA_STRING name;
    name.Buffer = const_cast<PCHAR>(NEGOSSP_NAME_A);
    name.Length = static_cast<USHORT>(strlen(NEGOSSP_NAME_A));
    name.MaximumLength = static_cast<USHORT>(name.Length + 1);
    NTSTATUS status = LsaLookupAuthenticationPackage(lsa, &name, package);
    LsaDeregisterLogonProcess(lsa);
    return status == STATUS_SUCCESS ? S_OK : E_FAIL;
}

// Status line for each phase.
static const wchar_t* PhaseText(LONG phase, bool blocked) {
    if (blocked) return L"No se pudo entrar con la contraseña guardada. Usá tu PIN.";
    switch (phase) {
        case PH_OFFLINE: return L"VisionAuth no está activo. Usá tu PIN.";
        case PH_STARTING: return L"Preparando la cámara";
        case PH_FACE: return L"Verificando…";
        case PH_UNRECOGNIZED: return L"No te reconozco. Probá de nuevo o usá tu PIN.";
        case PH_MATCH: return L"¡Hola! Entrando…";
        case PH_AWAY: return L"En espera";
        default: return L"Mirá a la cámara";
    }
}

// ---------------------------------------------------------------------------
// Credential (the tile)

class Credential final : public ICredentialProviderCredential2 {
  public:
    explicit Credential(SharedState* state) : state_(state) {
        state_->AddRef();
        DllAddRef();
    }

    // IUnknown
    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override {
        LONG refs = InterlockedDecrement(&refs_);
        if (refs == 0) delete this;
        return refs;
    }
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_ICredentialProviderCredential) ||
            IsEqualIID(riid, IID_ICredentialProviderCredential2)) {
            *ppv = static_cast<ICredentialProviderCredential2*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }

    // ICredentialProviderCredential
    IFACEMETHODIMP Advise(ICredentialProviderCredentialEvents* events) override {
        if (events_) events_->Release();
        events_ = events;
        if (events_) events_->AddRef();
        return S_OK;
    }
    IFACEMETHODIMP UnAdvise() override {
        if (events_) events_->Release();
        events_ = nullptr;
        return S_OK;
    }
    IFACEMETHODIMP SetSelected(BOOL* autoLogon) override {
        if (!autoLogon) return E_POINTER;
        *autoLogon = (state_->pending && !state_->blocked) ? TRUE : FALSE;
        return S_OK;
    }
    IFACEMETHODIMP SetDeselected() override { return S_OK; }
    IFACEMETHODIMP GetFieldState(DWORD field, CREDENTIAL_PROVIDER_FIELD_STATE* state,
                                 CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE* interactive) override {
        if (field >= FI_COUNT || !state || !interactive) return E_INVALIDARG;
        *state = kFieldStates[field];
        *interactive = CPFIS_NONE;
        return S_OK;
    }
    IFACEMETHODIMP GetStringValue(DWORD field, LPWSTR* value) override {
        if (!value) return E_POINTER;
        *value = nullptr;
        if (field == FI_LABEL) return SHStrDupW(L"VisionAuth", value);
        if (field == FI_STATUS) return SHStrDupW(PhaseText(state_->phase, state_->blocked != 0), value);
        return E_INVALIDARG;
    }
    IFACEMETHODIMP GetBitmapValue(DWORD field, HBITMAP* bitmap) override {
        if (!bitmap) return E_POINTER;
        *bitmap = nullptr;
        if (field != FI_LOGO) return E_INVALIDARG;
        *bitmap = CreateVisionAuthLogoBitmap(64);
        return *bitmap ? S_OK : E_OUTOFMEMORY;
    }

    // Shows a new phase on the tile. Called on LogonUI's thread only.
    void ShowPhase(LONG phase) {
        InterlockedExchange(&state_->phase, phase);
        if (!events_) return;
        events_->SetFieldString(this, FI_STATUS, PhaseText(phase, state_->blocked != 0));
    }

    // LogonUI's window, to own the island. Null until LogonUI advises the tile.
    HWND OwnerWindow() {
        HWND window = nullptr;
        if (events_) events_->OnCreatingWindow(&window);
        return window;
    }
    IFACEMETHODIMP GetCheckboxValue(DWORD, BOOL*, LPWSTR*) override { return E_NOTIMPL; }
    IFACEMETHODIMP GetSubmitButtonValue(DWORD, DWORD*) override { return E_NOTIMPL; }
    IFACEMETHODIMP GetComboBoxValueCount(DWORD, DWORD*, DWORD*) override { return E_NOTIMPL; }
    IFACEMETHODIMP GetComboBoxValueAt(DWORD, DWORD, LPWSTR*) override { return E_NOTIMPL; }
    IFACEMETHODIMP SetStringValue(DWORD, LPCWSTR) override { return E_NOTIMPL; }
    IFACEMETHODIMP SetCheckboxValue(DWORD, BOOL) override { return E_NOTIMPL; }
    IFACEMETHODIMP SetComboBoxSelectedValue(DWORD, DWORD) override { return E_NOTIMPL; }
    IFACEMETHODIMP CommandLinkClicked(DWORD) override { return E_NOTIMPL; }

    IFACEMETHODIMP GetSerialization(CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE* response,
                                    CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* serialization,
                                    LPWSTR* statusText, CREDENTIAL_PROVIDER_STATUS_ICON* statusIcon) override {
        if (!response || !serialization || !statusText || !statusIcon) return E_POINTER;
        *response = CPGSR_NO_CREDENTIAL_NOT_FINISHED;
        ZeroMemory(serialization, sizeof(*serialization));
        *statusText = nullptr;
        *statusIcon = CPSI_NONE;

        // Only a fresh verification from the service lets this tile log on
        if (state_->blocked || InterlockedExchange(&state_->pending, 0) == 0) {
            SHStrDupW(PhaseText(state_->phase, state_->blocked != 0), statusText);
            return S_OK;
        }

        StoredCredential credential;
        if (!ReadStoredCredential(&credential)) {
            InterlockedExchange(&state_->blocked, 1);
            SHStrDupW(L"VisionAuth no tiene una contraseña guardada. Usá tu PIN.", statusText);
            *statusIcon = CPSI_ERROR;
            *response = CPGSR_NO_CREDENTIAL_FINISHED;
            return S_OK;
        }

        ULONG package = 0;
        HRESULT hr = LookupNegotiatePackage(&package);
        if (SUCCEEDED(hr)) {
            hr = PackLogon(credential, state_->scenario, &serialization->rgbSerialization,
                           &serialization->cbSerialization);
        }
        credential.Wipe();
        if (FAILED(hr)) return hr;

        serialization->ulAuthenticationPackage = package;
        serialization->clsidCredentialProvider = CLSID_VisionAuthProvider;
        *response = CPGSR_RETURN_CREDENTIAL_FINISHED;
        return S_OK;
    }

    IFACEMETHODIMP ReportResult(NTSTATUS status, NTSTATUS, LPWSTR* statusText,
                                CREDENTIAL_PROVIDER_STATUS_ICON* statusIcon) override {
        if (statusText) *statusText = nullptr;
        if (statusIcon) *statusIcon = CPSI_NONE;
        // A wrong stored password must not be retried on every verification
        if (status != STATUS_SUCCESS) InterlockedExchange(&state_->blocked, 1);
        return S_OK;
    }

    // ICredentialProviderCredential2: show the tile under the owner's account
    IFACEMETHODIMP GetUserSid(LPWSTR* sid) override {
        if (!sid) return E_POINTER;
        *sid = nullptr;
        StoredCredential credential;
        if (!ReadStoredCredential(&credential)) return S_FALSE;
        HRESULT hr = SHStrDupW(credential.sid, sid);
        credential.Wipe();
        return hr;
    }

  private:
    ~Credential() {
        if (events_) events_->Release();
        state_->Release();
        DllRelease();
    }

    LONG refs_ = 1;
    SharedState* state_;
    ICredentialProviderCredentialEvents* events_ = nullptr;
};

// ---------------------------------------------------------------------------
// Whether the screen can be seen

#ifndef DEVICE_NOTIFY_CALLBACK
// From the Windows SDK; the MinGW headers leave them out
#define DEVICE_NOTIFY_CALLBACK 2
typedef ULONG CALLBACK DEVICE_NOTIFY_CALLBACK_ROUTINE(PVOID context, ULONG type, PVOID setting);
struct DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS {
    DEVICE_NOTIFY_CALLBACK_ROUTINE* Callback;
    PVOID Context;
};
#endif

// Times are in milliseconds of GetTickCount64, which keeps counting during
// sleep, like the interrupt time the system gives for the last wake (in
// 100 ns units).
static ULONGLONG LastWakeTickMs() {
    ULONGLONG wake = 0;
    if (CallNtPowerInformation(LastWakeTime, nullptr, 0, &wake, sizeof(wake)) != 0) return 0;
    return wake / 10000;
}

class DisplayWatch {
  public:
    void Start() {
        DWORD value = 0, size = sizeof(value);
        if (RegGetValueW(HKEY_LOCAL_MACHINE, kSettingsKey, L"DisplaySettleMs", RRF_RT_REG_DWORD, nullptr, &value,
                         &size) == ERROR_SUCCESS) {
            settle_ = value;
        }
        // Windows reports the current state right away, then every change
        DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS parameters = {&OnChange, this};
        if (PowerSettingRegisterNotification(&GUID_CONSOLE_DISPLAY_STATE, DEVICE_NOTIFY_CALLBACK, &parameters,
                                             &registration_) != ERROR_SUCCESS) {
            registration_ = nullptr;
        }
    }

    void Stop() {
        if (registration_) PowerSettingUnregisterNotification(registration_);
        registration_ = nullptr;
    }

    // True once the screen has been on for the settle time, counted from when
    // it turned on or the PC woke up, whichever was last.
    bool Ready() const {
        if (!on_) return false;
        ULONGLONG since = static_cast<ULONGLONG>(onSince_);
        ULONGLONG wake = LastWakeTickMs();
        if (wake > since) since = wake;
        ULONGLONG now = GetTickCount64();
        return now < since || now - since >= settle_;
    }

  private:
    static ULONG CALLBACK OnChange(PVOID context, ULONG type, PVOID setting) {
        auto* self = static_cast<DisplayWatch*>(context);
        auto* change = static_cast<POWERBROADCAST_SETTING*>(setting);
        if (type != PBT_POWERSETTINGCHANGE || !change || change->DataLength < sizeof(DWORD)) return ERROR_SUCCESS;
        // 0 off, 1 on, 2 dimmed (still visible)
        bool on = *reinterpret_cast<DWORD*>(change->Data) != 0;
        // A first report of "on" says nothing about when it turned on: the
        // wake time covers the PC coming back from sleep
        if (on && !self->on_) InterlockedExchange64(&self->onSince_, static_cast<LONG64>(GetTickCount64()));
        InterlockedExchange(&self->on_, on ? 1 : 0);
        return ERROR_SUCCESS;
    }

    HPOWERNOTIFY registration_ = nullptr;
    ULONGLONG settle_ = kDefaultDisplaySettleMs;
    volatile LONG on_ = 1;  // assumed on until Windows reports otherwise
    volatile LONG64 onSince_ = 0;
};

// ---------------------------------------------------------------------------
// Provider

class Provider final : public ICredentialProvider {
  public:
    Provider() {
        DllAddRef();
        // Started early, so a lock right before sleep still sees the screen
        // turn back on
        display_.Start();
    }

    // IUnknown
    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override {
        LONG refs = InterlockedDecrement(&refs_);
        if (refs == 0) delete this;
        return refs;
    }
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_ICredentialProvider)) {
            *ppv = static_cast<ICredentialProvider*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }

    // ICredentialProvider
    IFACEMETHODIMP SetUsageScenario(CREDENTIAL_PROVIDER_USAGE_SCENARIO scenario, DWORD) override {
        if (scenario != CPUS_LOGON && scenario != CPUS_UNLOCK_WORKSTATION) return E_NOTIMPL;
        state_->scenario = scenario;
        if (!credential_) credential_ = new (std::nothrow) Credential(state_);
        return credential_ ? S_OK : E_OUTOFMEMORY;
    }
    IFACEMETHODIMP SetSerialization(const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION*) override {
        return E_NOTIMPL;
    }
    // LogonUI calls Advise and UnAdvise on its UI thread. The window created
    // here receives the phases found by the polling thread, so every call back
    // into LogonUI happens on that same thread.
    IFACEMETHODIMP Advise(ICredentialProviderEvents* events, UINT_PTR context) override {
        if (events_) events_->Release();
        events_ = events;
        if (events_) events_->AddRef();
        context_ = context;
        CreateMessageWindow();
        StartPolling();
        return S_OK;
    }
    IFACEMETHODIMP UnAdvise() override {
        StopPolling();
        island_.Destroy();
        DestroyMessageWindow();
        if (events_) events_->Release();
        events_ = nullptr;
        return S_OK;
    }
    IFACEMETHODIMP GetFieldDescriptorCount(DWORD* count) override {
        if (!count) return E_POINTER;
        *count = FI_COUNT;
        return S_OK;
    }
    IFACEMETHODIMP GetFieldDescriptorAt(DWORD index, CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** descriptor) override {
        if (!descriptor) return E_POINTER;
        *descriptor = nullptr;
        if (index >= FI_COUNT) return E_INVALIDARG;
        auto* copy = static_cast<CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR*>(CoTaskMemAlloc(sizeof(**descriptor)));
        if (!copy) return E_OUTOFMEMORY;
        *copy = kFields[index];
        HRESULT hr = SHStrDupW(kFields[index].pszLabel, &copy->pszLabel);
        if (FAILED(hr)) {
            CoTaskMemFree(copy);
            return hr;
        }
        *descriptor = copy;
        return S_OK;
    }
    IFACEMETHODIMP GetCredentialCount(DWORD* count, DWORD* defaultIndex, BOOL* autoLogon) override {
        if (!count || !defaultIndex || !autoLogon) return E_POINTER;
        bool ready = state_->pending && !state_->blocked;
        *count = credential_ ? 1 : 0;
        // Selected by default, like Windows Hello face, so its status shows;
        // the PIN stays one click away under the sign-in options
        *defaultIndex = credential_ ? 0 : CREDENTIAL_PROVIDER_NO_DEFAULT;
        *autoLogon = (ready && credential_) ? TRUE : FALSE;
        return S_OK;
    }
    IFACEMETHODIMP GetCredentialAt(DWORD index, ICredentialProviderCredential** credential) override {
        if (!credential) return E_POINTER;
        *credential = nullptr;
        if (index != 0 || !credential_) return E_INVALIDARG;
        return credential_->QueryInterface(IID_ICredentialProviderCredential, reinterpret_cast<void**>(credential));
    }

  private:
    ~Provider() {
        display_.Stop();
        StopPolling();
        island_.Destroy();
        DestroyMessageWindow();
        if (events_) events_->Release();
        if (credential_) credential_->Release();
        state_->Release();
        DllRelease();
    }

    void StartPolling() {
        if (thread_) return;
        stop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        if (!stop_) return;
        // The thread keeps the DLL loaded until it has fully exited
        HMODULE self = nullptr;
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS, reinterpret_cast<LPCWSTR>(&PollThread), &self);
        AddRef();
        thread_ = CreateThread(nullptr, 0, &PollThread, this, 0, nullptr);
        if (!thread_) {
            Release();
            if (self) FreeLibrary(self);
            CloseHandle(stop_);
            stop_ = nullptr;
        }
    }

    void StopPolling() {
        if (!thread_) return;
        SetEvent(stop_);
        // The polling thread may itself drop the last reference
        if (GetThreadId(thread_) != GetCurrentThreadId()) WaitForSingleObject(thread_, 5000);
        CloseHandle(thread_);
        CloseHandle(stop_);
        thread_ = nullptr;
        stop_ = nullptr;
    }

    static DWORD WINAPI PollThread(LPVOID parameter) {
        auto* self = static_cast<Provider*>(parameter);
        self->Poll();
        self->Release();
        FreeLibraryAndExitThread(g_module, 0);
        return 0;
    }

    void Poll() {
        LONG shown = -1;
        DWORD wait = 0;  // ask right away: the tile shows the real state sooner
        while (WaitForSingleObject(stop_, wait) == WAIT_TIMEOUT) {
            wait = kPollIntervalMs;
            LONG phase;
            if (state_->blocked) {
                phase = ISLAND_BLOCKED;
            } else if (state_->pending) {
                continue;  // verified: waiting for LogonUI to log on
            } else {
                phase = AskService(state_->name, 64);
                if (phase == PH_MATCH) InterlockedExchange(&state_->pending, 1);
            }
            if (phase != shown) {
                shown = phase;
                PostMessageW(window_, WM_VISIONAUTH_PHASE, static_cast<WPARAM>(phase), 0);
            }
        }
    }

    // Runs on LogonUI's thread.
    void OnPhase(LONG phase) {
        if (credential_) credential_->ShowPhase(phase);
        if (!island_.Created() && credential_) {
            // Best effort: without the island the tile still shows the status
            if (island_.Create(credential_->OwnerWindow(), g_module)) island_.SetVisible(true);
        }
        if (phase == PH_MATCH) island_.SetName(state_->name);
        island_.SetPhase(phase);
        // Give the check mark a moment on screen before logging on
        if (phase == PH_MATCH) SetTimer(window_, kLogonTimer, kMatchDelayMs, nullptr);
    }

    void OnLogonTimer() {
        if (!display_.Ready()) {
            // Keep the check mark up until the screen shows it
            SetTimer(window_, kLogonTimer, kDisplayRecheckMs, nullptr);
            return;
        }
        KillTimer(window_, kLogonTimer);
        if (events_) events_->CredentialsChanged(context_);
    }

    static LRESULT CALLBACK WindowProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
        auto* self = reinterpret_cast<Provider*>(GetWindowLongPtrW(window, GWLP_USERDATA));
        if (message == WM_VISIONAUTH_PHASE) {
            if (self) self->OnPhase(static_cast<LONG>(wparam));
            return 0;
        }
        if (message == WM_TIMER && wparam == kLogonTimer) {
            if (self) self->OnLogonTimer();
            return 0;
        }
        return DefWindowProcW(window, message, wparam, lparam);
    }

    void CreateMessageWindow() {
        if (window_) return;
        WNDCLASSEXW windowClass = {};
        windowClass.cbSize = sizeof(windowClass);
        windowClass.lpfnWndProc = &WindowProc;
        windowClass.hInstance = g_module;
        windowClass.lpszClassName = kWindowClass;
        RegisterClassExW(&windowClass);  // fails harmlessly if already registered
        window_ = CreateWindowExW(0, kWindowClass, L"", 0, 0, 0, 0, 0, HWND_MESSAGE, nullptr, g_module, nullptr);
        if (window_) SetWindowLongPtrW(window_, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(this));
    }

    void DestroyMessageWindow() {
        if (!window_) return;
        SetWindowLongPtrW(window_, GWLP_USERDATA, 0);
        DestroyWindow(window_);
        window_ = nullptr;
        UnregisterClassW(kWindowClass, g_module);
    }

    LONG refs_ = 1;
    SharedState* state_ = new (std::nothrow) SharedState();
    Credential* credential_ = nullptr;
    ICredentialProviderEvents* events_ = nullptr;
    UINT_PTR context_ = 0;
    HANDLE thread_ = nullptr;
    HANDLE stop_ = nullptr;
    HWND window_ = nullptr;
    IslandWindow island_;
    DisplayWatch display_;
};

// ---------------------------------------------------------------------------
// Class factory and DLL exports

class ClassFactory final : public IClassFactory {
  public:
    IFACEMETHODIMP_(ULONG) AddRef() override { return 2; }
    IFACEMETHODIMP_(ULONG) Release() override { return 1; }
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_IClassFactory)) {
            *ppv = static_cast<IClassFactory*>(this);
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    IFACEMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        auto* provider = new (std::nothrow) Provider();
        if (!provider) return E_OUTOFMEMORY;
        HRESULT hr = provider->QueryInterface(riid, ppv);
        provider->Release();
        return hr;
    }
    IFACEMETHODIMP LockServer(BOOL lock) override {
        lock ? DllAddRef() : DllRelease();
        return S_OK;
    }
};

static ClassFactory g_factory;

extern "C" BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}

extern "C" HRESULT STDAPICALLTYPE DllCanUnloadNow() { return g_dllRefs > 0 ? S_FALSE : S_OK; }

extern "C" HRESULT STDAPICALLTYPE DllGetClassObject(REFCLSID clsid, REFIID riid, void** ppv) {
    if (!ppv) return E_POINTER;
    *ppv = nullptr;
    if (!IsEqualCLSID(clsid, CLSID_VisionAuthProvider)) return CLASS_E_CLASSNOTAVAILABLE;
    return g_factory.QueryInterface(riid, ppv);
}
