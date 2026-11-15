// Renders the island's animation and the VisionAuth logo to PNG files, with
// no window, to review the design.
//
// Usage: island_preview.exe <sheet.png> [scale] [logo.png]
//
// The sheet has one row per moment of a scripted sequence (camera starting,
// searching, nobody in view, face, not recognized, face, match), simulated at 120 Hz and
// drawn over a blurred copy of the default wallpaper, like the sign-in screen.

#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <d2d1.h>
#include <dwrite.h>
#include <wincodec.h>

#include <cstdio>
#include <cwchar>

#include "island.h"

template <typename T>
static void SafeRelease(T*& p) {
    if (p) {
        p->Release();
        p = nullptr;
    }
}

static HRESULT SavePng(IWICImagingFactory* wic, IWICBitmap* bitmap, const wchar_t* path) {
    IWICStream* stream = nullptr;
    IWICBitmapEncoder* encoder = nullptr;
    IWICBitmapFrameEncode* frame = nullptr;
    HRESULT hr = wic->CreateStream(&stream);
    if (SUCCEEDED(hr)) hr = stream->InitializeFromFilename(path, GENERIC_WRITE);
    if (SUCCEEDED(hr)) hr = wic->CreateEncoder(GUID_ContainerFormatPng, nullptr, &encoder);
    if (SUCCEEDED(hr)) hr = encoder->Initialize(stream, WICBitmapEncoderNoCache);
    if (SUCCEEDED(hr)) hr = encoder->CreateNewFrame(&frame, nullptr);
    if (SUCCEEDED(hr)) hr = frame->Initialize(nullptr);
    if (SUCCEEDED(hr)) hr = frame->WriteSource(bitmap, nullptr);
    if (SUCCEEDED(hr)) hr = frame->Commit();
    if (SUCCEEDED(hr)) hr = encoder->Commit();
    SafeRelease(frame);
    SafeRelease(encoder);
    SafeRelease(stream);
    return hr;
}

static ID2D1RenderTarget* TargetFor(ID2D1Factory* factory, IWICBitmap* bitmap) {
    ID2D1RenderTarget* target = nullptr;
    D2D1_RENDER_TARGET_PROPERTIES properties = D2D1::RenderTargetProperties(
        D2D1_RENDER_TARGET_TYPE_SOFTWARE, D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED),
        96, 96);
    factory->CreateWicBitmapRenderTarget(bitmap, &properties, &target);
    return target;
}

// The default wallpaper shrunk to a few pixels, to draw it back up blurred.
static IWICBitmap* BlurredWallpaper(IWICImagingFactory* wic, ID2D1Factory* factory) {
    IWICBitmapDecoder* decoder = nullptr;
    IWICBitmapFrameDecode* source = nullptr;
    IWICFormatConverter* converter = nullptr;
    IWICBitmap* tiny = nullptr;
    if (SUCCEEDED(wic->CreateDecoderFromFilename(L"C:\\Windows\\Web\\Wallpaper\\Windows\\img0.jpg", nullptr,
                                                 GENERIC_READ, WICDecodeMetadataCacheOnLoad, &decoder)) &&
        SUCCEEDED(decoder->GetFrame(0, &source)) && SUCCEEDED(wic->CreateFormatConverter(&converter)) &&
        SUCCEEDED(converter->Initialize(source, GUID_WICPixelFormat32bppPBGRA, WICBitmapDitherTypeNone, nullptr, 0,
                                        WICBitmapPaletteTypeCustom)) &&
        SUCCEEDED(wic->CreateBitmap(48, 27, GUID_WICPixelFormat32bppPBGRA, WICBitmapCacheOnLoad, &tiny))) {
        ID2D1RenderTarget* target = TargetFor(factory, tiny);
        ID2D1Bitmap* full = nullptr;
        if (target && SUCCEEDED(target->CreateBitmapFromWicBitmap(converter, &full))) {
            target->BeginDraw();
            target->DrawBitmap(full, D2D1::RectF(0, 0, 48, 27));
            target->EndDraw();
        }
        SafeRelease(full);
        SafeRelease(target);
    }
    SafeRelease(converter);
    SafeRelease(source);
    SafeRelease(decoder);
    return tiny;
}

struct Step {
    double at;
    LONG phase;
};

static int RenderSheet(IWICImagingFactory* wic, ID2D1Factory* factory, const wchar_t* output, float scale) {
    const Step script[] = {{0.0, ISLAND_STARTING}, {0.9, ISLAND_SEARCHING}, {1.6, ISLAND_AWAY}, {2.4, ISLAND_FACE},
                           {3.4, ISLAND_UNRECOGNIZED}, {4.8, ISLAND_FACE}, {5.8, ISLAND_MATCH}};
    const double moments[] = {0.10, 0.25, 0.7, 1.4, 2.2, 2.9, 3.46, 4.3, 5.92, 6.05, 7.2};
    const int frames = sizeof(moments) / sizeof(moments[0]);
    float rowW = 960 * scale, rowH = 190 * scale, labelW = 70 * scale;
    UINT sheetW = static_cast<UINT>(rowW + labelW), sheetH = static_cast<UINT>(rowH * frames);

    IWICBitmap* sheet = nullptr;
    if (FAILED(wic->CreateBitmap(sheetW, sheetH, GUID_WICPixelFormat32bppPBGRA, WICBitmapCacheOnLoad, &sheet))) return 1;
    ID2D1RenderTarget* target = TargetFor(factory, sheet);
    IWICBitmap* wallpaper = BlurredWallpaper(wic, factory);
    ID2D1Bitmap* background = nullptr;
    if (wallpaper) target->CreateBitmapFromWicBitmap(wallpaper, &background);

    IDWriteFactory* write = nullptr;
    DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory), reinterpret_cast<IUnknown**>(&write));
    IDWriteTextFormat* labelFormat = nullptr;
    write->CreateTextFormat(L"Segoe UI", nullptr, DWRITE_FONT_WEIGHT_NORMAL, DWRITE_FONT_STYLE_NORMAL,
                            DWRITE_FONT_STRETCH_NORMAL, 11 * scale, L"en-us", &labelFormat);
    ID2D1SolidColorBrush* brush = nullptr;
    target->CreateSolidColorBrush(D2D1::ColorF(0.35f, 0.35f, 0.37f), &brush);

    target->BeginDraw();
    target->Clear(D2D1::ColorF(0.96f, 0.96f, 0.97f));
    for (int f = 0; f < frames; ++f) {
        float y = f * rowH;
        if (background) {
            target->DrawBitmap(background, D2D1::RectF(labelW, y, labelW + rowW, y + rowH), 1.0f,
                               D2D1_BITMAP_INTERPOLATION_MODE_LINEAR, D2D1::RectF(8, 2.0f + (f % 3), 40, 7.0f + (f % 3)));
        }
        wchar_t label[32];
        swprintf(label, 32, L"t=%.2fs", moments[f]);
        target->DrawText(label, static_cast<UINT32>(wcslen(label)), labelFormat,
                         D2D1::RectF(6 * scale, y + 8 * scale, labelW, y + 40 * scale), brush);

        // Simulate the sequence up to this moment at 120 Hz
        IslandRenderer renderer;
        renderer.SetName(L"Joaquin");
        renderer.SetVisible(true);
        int next = 0;
        const int steps = static_cast<int>(moments[f] * 120);
        for (int i = 0; i <= steps; ++i) {
            double t = i / 120.0;
            while (next < static_cast<int>(sizeof(script) / sizeof(script[0])) && script[next].at <= t) {
                renderer.SetPhase(script[next++].phase);
            }
            if (i < steps) renderer.Advance(1 / 120.0);
        }
        target->SetTransform(D2D1::Matrix3x2F::Translation(labelW, y));
        renderer.Draw(target, rowW, rowH, scale);
        target->SetTransform(D2D1::Matrix3x2F::Identity());
    }
    HRESULT hr = target->EndDraw();
    SafeRelease(brush);
    SafeRelease(labelFormat);
    SafeRelease(write);
    SafeRelease(background);
    SafeRelease(wallpaper);
    SafeRelease(target);
    if (SUCCEEDED(hr)) hr = SavePng(wic, sheet, output);
    SafeRelease(sheet);
    if (FAILED(hr)) return 1;
    std::wprintf(L"wrote %ls (%d frames)\n", output, frames);
    return 0;
}

static int RenderLogo(IWICImagingFactory* wic, ID2D1Factory* factory, const wchar_t* output) {
    const UINT size = 512;
    IWICBitmap* bitmap = nullptr;
    if (FAILED(wic->CreateBitmap(size, size, GUID_WICPixelFormat32bppPBGRA, WICBitmapCacheOnLoad, &bitmap))) return 1;
    ID2D1RenderTarget* target = TargetFor(factory, bitmap);
    target->BeginDraw();
    target->Clear(D2D1::ColorF(0, 0, 0, 0));
    DrawVisionAuthLogo(target, 0, 0, static_cast<float>(size));
    HRESULT hr = target->EndDraw();
    SafeRelease(target);
    if (SUCCEEDED(hr)) hr = SavePng(wic, bitmap, output);
    SafeRelease(bitmap);
    if (FAILED(hr)) return 1;
    std::wprintf(L"wrote %ls\n", output);
    return 0;
}

int wmain(int argc, wchar_t** argv) {
    if (argc < 2) {
        std::fwprintf(stderr, L"usage: island_preview <sheet.png> [scale] [logo.png]\n");
        return 2;
    }
    float scale = argc >= 3 ? static_cast<float>(_wtof(argv[2])) : 1.25f;
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    IWICImagingFactory* wic = nullptr;
    ID2D1Factory* factory = nullptr;
    int result = 1;
    if (SUCCEEDED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&wic))) &&
        SUCCEEDED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, &factory))) {
        result = RenderSheet(wic, factory, argv[1], scale);
        if (result == 0 && argc >= 4) result = RenderLogo(wic, factory, argv[3]);
    }
    SafeRelease(factory);
    SafeRelease(wic);
    CoUninitialize();
    return result;
}
