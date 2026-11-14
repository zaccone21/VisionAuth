// Test harness for the VisionAuth credential provider, run as a normal user.
//
// Part 1 compiles the provider source in, to test credential packing and
// secret parsing directly. Part 2 loads a built DLL the way LogonUI does and
// drives it against a fake service pipe served by this process.
//
// Usage: test_harness.exe <dll> <expect-match: 1|0>

#include "VisionAuthCredentialProvider.cpp"

#include <cstdio>
#include <cwchar>
#include <string_view>

static int g_failures = 0;
#define CHECK(condition)                                                     \
    do {                                                                     \
        if (!(condition)) {                                                  \
            std::printf("FAIL line %d: %s\n", __LINE__, #condition);         \
            ++g_failures;                                                    \
        }                                                                    \
    } while (0)

// --- Part 1: packing and parsing ------------------------------------------

static void TestPackLogon() {
    StoredCredential credential = {};
    wcscpy(credential.domain, L"MicrosoftAccount");
    wcscpy(credential.user, L"owner@example.com");
    wcscpy(credential.password, L"secret");

    BYTE* block = nullptr;
    ULONG size = 0;
    CHECK(SUCCEEDED(PackLogon(credential, CPUS_UNLOCK_WORKSTATION, &block, &size)));
    CHECK(size == sizeof(KERB_INTERACTIVE_UNLOCK_LOGON) + (16 + 17 + 6) * sizeof(wchar_t));

    auto* logon = reinterpret_cast<KERB_INTERACTIVE_UNLOCK_LOGON*>(block);
    CHECK(logon->Logon.MessageType == KerbWorkstationUnlockLogon);
    auto text = [&](UNICODE_STRING& s) {
        return std::wstring_view(reinterpret_cast<wchar_t*>(block + reinterpret_cast<ULONG_PTR>(s.Buffer)),
                                 s.Length / sizeof(wchar_t));
    };
    CHECK(text(logon->Logon.LogonDomainName) == L"MicrosoftAccount");
    CHECK(text(logon->Logon.UserName) == L"owner@example.com");
    CHECK(text(logon->Logon.Password) == L"secret");
    CHECK(reinterpret_cast<ULONG_PTR>(logon->Logon.Password.Buffer) + logon->Logon.Password.Length == size);
    CoTaskMemFree(block);

    CHECK(SUCCEEDED(PackLogon(credential, CPUS_LOGON, &block, &size)));
    CHECK(reinterpret_cast<KERB_INTERACTIVE_UNLOCK_LOGON*>(block)->Logon.MessageType == KerbInteractiveLogon);
    CoTaskMemFree(block);
}

static void TestParseSecret() {
    const wchar_t secret[] = L"S-1-5-21-1-2-3-1001\nMicrosoftAccount\nowner@example.com\npa\nss";
    const wchar_t* cursor = secret;
    const wchar_t* end = secret + wcslen(secret);
    StoredCredential c = {};
    CHECK(NextField(cursor, end, c.sid, ARRAYSIZE(c.sid), false));
    CHECK(NextField(cursor, end, c.domain, ARRAYSIZE(c.domain), false));
    CHECK(NextField(cursor, end, c.user, ARRAYSIZE(c.user), false));
    // The password is the rest, so it may itself contain a newline
    CHECK(NextField(cursor, end, c.password, ARRAYSIZE(c.password), true));
    CHECK(wcscmp(c.sid, L"S-1-5-21-1-2-3-1001") == 0);
    CHECK(wcscmp(c.user, L"owner@example.com") == 0);
    CHECK(wcscmp(c.password, L"pa\nss") == 0);

    const wchar_t truncated[] = L"S-1-5-21\nMicrosoftAccount";
    cursor = truncated;
    end = truncated + wcslen(truncated);
    StoredCredential d = {};
    CHECK(NextField(cursor, end, d.sid, ARRAYSIZE(d.sid), false));
    CHECK(!NextField(cursor, end, d.domain, ARRAYSIZE(d.domain), false));
}

// --- Part 2: the DLL, driven like LogonUI ---------------------------------

class Events final : public ICredentialProviderEvents {
  public:
    HANDLE changed = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    IFACEMETHODIMP_(ULONG) AddRef() override { return 2; }
    IFACEMETHODIMP_(ULONG) Release() override { return 1; }
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_ICredentialProviderEvents)) {
            *ppv = this;
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    IFACEMETHODIMP CredentialsChanged(UINT_PTR context) override {
        if (context == 42) SetEvent(changed);
        return S_OK;
    }
};

// Records what the provider shows on the tile.
class CredentialEvents final : public ICredentialProviderCredentialEvents {
  public:
    wchar_t lastStatus[256] = L"";
    int bitmaps = 0;
    IFACEMETHODIMP_(ULONG) AddRef() override { return 2; }
    IFACEMETHODIMP_(ULONG) Release() override { return 1; }
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (IsEqualIID(riid, IID_IUnknown) || IsEqualIID(riid, IID_ICredentialProviderCredentialEvents)) {
            *ppv = this;
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    IFACEMETHODIMP SetFieldState(ICredentialProviderCredential*, DWORD, CREDENTIAL_PROVIDER_FIELD_STATE) override {
        return S_OK;
    }
    IFACEMETHODIMP SetFieldInteractiveState(ICredentialProviderCredential*, DWORD,
                                            CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE) override {
        return S_OK;
    }
    IFACEMETHODIMP SetFieldString(ICredentialProviderCredential*, DWORD field, LPCWSTR text) override {
        if (field == FI_STATUS) wcsncpy(lastStatus, text, 255);
        return S_OK;
    }
    IFACEMETHODIMP SetFieldCheckbox(ICredentialProviderCredential*, DWORD, BOOL, LPCWSTR) override { return S_OK; }
    IFACEMETHODIMP SetFieldBitmap(ICredentialProviderCredential*, DWORD, HBITMAP bitmap) override {
        if (bitmap) ++bitmaps;
        return S_OK;
    }
    IFACEMETHODIMP SetFieldComboBoxSelectedItem(ICredentialProviderCredential*, DWORD, DWORD) override { return S_OK; }
    IFACEMETHODIMP DeleteFieldComboBoxItem(ICredentialProviderCredential*, DWORD, DWORD) override { return S_OK; }
    IFACEMETHODIMP AppendFieldComboBoxItem(ICredentialProviderCredential*, DWORD, LPCWSTR) override { return S_OK; }
    IFACEMETHODIMP SetFieldSubmitButton(ICredentialProviderCredential*, DWORD, DWORD) override { return S_OK; }
    IFACEMETHODIMP OnCreatingWindow(HWND* window) override {
        *window = nullptr;
        return S_OK;
    }
};

// Waits for an event while pumping window messages, as LogonUI's UI thread does.
static bool PumpUntil(HANDLE event, DWORD timeoutMs) {
    DWORD deadline = GetTickCount() + timeoutMs;
    for (;;) {
        DWORD now = GetTickCount();
        if (now >= deadline) return false;
        DWORD result = MsgWaitForMultipleObjects(1, &event, FALSE, deadline - now, QS_ALLINPUT);
        if (result == WAIT_OBJECT_0) return true;
        MSG message;
        while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) DispatchMessageW(&message);
    }
}

// Fake service: answers "STATE face" a few times, then "MATCH owner".
static DWORD WINAPI FakeService(LPVOID stopEvent) {
    int requests = 0;
    while (WaitForSingleObject(stopEvent, 0) == WAIT_TIMEOUT) {
        HANDLE pipe = CreateNamedPipeW(kPipeName, PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
                                       PIPE_TYPE_BYTE | PIPE_WAIT, 1, 512, 512, 0, nullptr);
        if (pipe == INVALID_HANDLE_VALUE) return 1;
        if (ConnectNamedPipe(pipe, nullptr) || GetLastError() == ERROR_PIPE_CONNECTED) {
            char request[64] = {};
            DWORD read = 0, written = 0;
            ReadFile(pipe, request, sizeof(request) - 1, &read, nullptr);
            const char* reply = (++requests <= 3) ? "STATE face\n" : "MATCH owner\n";
            WriteFile(pipe, reply, static_cast<DWORD>(strlen(reply)), &written, nullptr);
            FlushFileBuffers(pipe);
        }
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
    }
    return 0;
}

static void TestDll(const wchar_t* path, bool expectMatch) {
    wchar_t full[MAX_PATH];
    GetFullPathNameW(path, MAX_PATH, full, nullptr);
    for (wchar_t* c = full; *c; ++c) {
        if (*c == L'/') *c = L'\\';
    }
    HMODULE dll = LoadLibraryW(full);
    CHECK(dll != nullptr);
    if (!dll) return;
    auto getClassObject = reinterpret_cast<HRESULT(STDAPICALLTYPE*)(REFCLSID, REFIID, void**)>(
        reinterpret_cast<void*>(GetProcAddress(dll, "DllGetClassObject")));
    auto canUnload = reinterpret_cast<HRESULT(STDAPICALLTYPE*)()>(
        reinterpret_cast<void*>(GetProcAddress(dll, "DllCanUnloadNow")));
    CHECK(getClassObject && canUnload);

    IClassFactory* factory = nullptr;
    CHECK(SUCCEEDED(getClassObject(CLSID_VisionAuthProvider, IID_IClassFactory, reinterpret_cast<void**>(&factory))));
    ICredentialProvider* provider = nullptr;
    CHECK(SUCCEEDED(factory->CreateInstance(nullptr, IID_ICredentialProvider, reinterpret_cast<void**>(&provider))));
    factory->Release();

    CHECK(provider->SetUsageScenario(CPUS_CHANGE_PASSWORD, 0) == E_NOTIMPL);
    CHECK(SUCCEEDED(provider->SetUsageScenario(CPUS_UNLOCK_WORKSTATION, 0)));

    DWORD fields = 0;
    CHECK(SUCCEEDED(provider->GetFieldDescriptorCount(&fields)) && fields == FI_COUNT);
    for (DWORD i = 0; i < fields; ++i) {
        CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR* descriptor = nullptr;
        CHECK(SUCCEEDED(provider->GetFieldDescriptorAt(i, &descriptor)));
        CoTaskMemFree(descriptor->pszLabel);
        CoTaskMemFree(descriptor);
    }

    DWORD count = 0, defaultIndex = 0;
    BOOL autoLogon = TRUE;
    CHECK(SUCCEEDED(provider->GetCredentialCount(&count, &defaultIndex, &autoLogon)));
    CHECK(count == 1 && !autoLogon && defaultIndex == 0);

    ICredentialProviderCredential* tile = nullptr;
    CHECK(SUCCEEDED(provider->GetCredentialAt(0, &tile)));
    CredentialEvents tileEvents;
    CHECK(SUCCEEDED(tile->Advise(&tileEvents)));

    HANDLE stopService = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    HANDLE service = CreateThread(nullptr, 0, FakeService, stopService, 0, nullptr);
    Sleep(100);

    Events events;
    CHECK(SUCCEEDED(provider->Advise(&events, 42)));
    bool changed = PumpUntil(events.changed, 3000);
    CHECK(changed == expectMatch);
    std::wprintf(L"  tile status shown: %ls (%d logo updates)\n", tileEvents.lastStatus, tileEvents.bitmaps);
    CHECK(tileEvents.bitmaps >= 1);
    // The real DLL rejects a pipe served by a normal user, so it shows "not active"
    CHECK(wcsstr(tileEvents.lastStatus, expectMatch ? L"Hola" : L"no est") != nullptr);
    tile->UnAdvise();
    tile->Release();

    CHECK(SUCCEEDED(provider->GetCredentialCount(&count, &defaultIndex, &autoLogon)));
    CHECK((autoLogon == TRUE) == expectMatch);

    ICredentialProviderCredential* credential = nullptr;
    CHECK(SUCCEEDED(provider->GetCredentialAt(0, &credential)));
    LPWSTR status = nullptr;
    CHECK(SUCCEEDED(credential->GetStringValue(FI_STATUS, &status)));
    std::wprintf(L"  status text: %ls\n", status);
    CoTaskMemFree(status);

    HBITMAP logo = nullptr;
    CHECK(SUCCEEDED(credential->GetBitmapValue(FI_LOGO, &logo)) && logo);
    DeleteObject(logo);

    CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE response;
    CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION serialization;
    CREDENTIAL_PROVIDER_STATUS_ICON icon;
    LPWSTR message = nullptr;
    CHECK(SUCCEEDED(credential->GetSerialization(&response, &serialization, &message, &icon)));
    // A normal user cannot read the LSA secret, so even a match yields no credential
    CHECK(response != CPGSR_RETURN_CREDENTIAL_FINISHED);
    CHECK(serialization.rgbSerialization == nullptr);
    std::wprintf(L"  serialization message: %ls\n", message ? message : L"(none)");
    CoTaskMemFree(message);
    credential->Release();

    CHECK(SUCCEEDED(provider->UnAdvise()));
    provider->Release();

    SetEvent(stopService);
    HANDLE wake = CreateFileW(kPipeName, GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    if (wake != INVALID_HANDLE_VALUE) CloseHandle(wake);
    WaitForSingleObject(service, 2000);

    Sleep(100);  // let the polling thread finish FreeLibraryAndExitThread
    CHECK(canUnload() == S_OK);
    FreeLibrary(dll);
}

int wmain(int argc, wchar_t** argv) {
    TestPackLogon();
    TestParseSecret();
    std::printf("unit checks done (%d failures so far)\n", g_failures);
    if (argc >= 3) {
        bool expectMatch = wcscmp(argv[2], L"1") == 0;
        std::wprintf(L"dll: %ls, expect match: %d\n", argv[1], expectMatch);
        TestDll(argv[1], expectMatch);
    }
    std::printf(g_failures ? "FAILED: %d\n" : "ALL PASSED\n", g_failures);
    return g_failures ? 1 : 0;
}
