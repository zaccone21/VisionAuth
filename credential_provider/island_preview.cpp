// Renders the island's animation to PNG frames, without any window, to review
// the design. Usage: island_preview.exe <output.png> [scale]
//
// Writes a contact sheet: one row per moment of a scripted sequence
// (camera starting, searching, face, not recognized, face, match), drawn over
// a blurred copy of the default Windows wallpaper like the sign-in screen.

#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <gdiplus.h>

#include <cstdio>
#include <cwchar>
#include <vector>

#include "island.h"

using namespace Gdiplus;

static bool PngEncoder(CLSID* clsid) {
    UINT count = 0, size = 0;
    GetImageEncodersSize(&count, &size);
    std::vector<BYTE> buffer(size);
    auto* encoders = reinterpret_cast<ImageCodecInfo*>(buffer.data());
    GetImageEncoders(count, size, encoders);
    for (UINT i = 0; i < count; ++i) {
        if (wcscmp(encoders[i].MimeType, L"image/png") == 0) {
            *clsid = encoders[i].Clsid;
            return true;
        }
    }
    return false;
}

static int Render(const wchar_t* output, float scale);

struct Step {
    double at;
    LONG phase;
};

int wmain(int argc, wchar_t** argv) {
    if (argc < 2) {
        std::fwprintf(stderr, L"usage: island_preview <output.png> [scale]\n");
        return 2;
    }
    float scale = argc >= 3 ? static_cast<float>(_wtof(argv[2])) : 1.25f;
    ULONG_PTR token = IslandStartGdiplus();
    int result = Render(argv[1], scale);
    // Every GDI+ object lives inside Render, so none outlives the shutdown
    IslandStopGdiplus(token);
    return result;
}

static int Render(const wchar_t* output, float scale) {

    const Step script[] = {{0.0, ISLAND_STARTING}, {0.9, ISLAND_SEARCHING}, {2.2, ISLAND_FACE},
                           {3.4, ISLAND_UNRECOGNIZED}, {4.8, ISLAND_FACE}, {5.8, ISLAND_MATCH}};
    const double moments[] = {0.08, 0.22, 0.6, 1.3, 2.6, 3.47, 4.2, 5.86, 6.0, 6.25, 6.9};
    const int frames = sizeof(moments) / sizeof(moments[0]);

    int islandWidth = static_cast<int>(620 * scale), islandHeight = static_cast<int>(130 * scale);
    int labelWidth = static_cast<int>(70 * scale);
    int sheetWidth = islandWidth + labelWidth, sheetHeight = islandHeight * frames;

    Bitmap sheet(sheetWidth, sheetHeight, PixelFormat32bppARGB);
    Graphics canvas(&sheet);
    canvas.SetInterpolationMode(InterpolationModeHighQualityBicubic);

    // Background: the default wallpaper, shrunk and blown up again to blur it
    Bitmap wallpaper(L"C:\\Windows\\Web\\Wallpaper\\Windows\\img0.jpg");
    if (wallpaper.GetLastStatus() == Ok) {
        Bitmap tiny(32, 18, PixelFormat32bppARGB);
        Graphics shrink(&tiny);
        shrink.SetInterpolationMode(InterpolationModeHighQualityBilinear);
        shrink.DrawImage(&wallpaper, 0, 0, 32, 18);
        for (int i = 0; i < frames; ++i) {
            canvas.DrawImage(&tiny, Rect(labelWidth, i * islandHeight, islandWidth, islandHeight), 4, 1 + (i % 3), 24, 3,
                             UnitPixel);
        }
    } else {
        SolidBrush fallback(Color(255, 40, 60, 90));
        canvas.FillRectangle(&fallback, labelWidth, 0, islandWidth, sheetHeight);
    }
    SolidBrush labelBackground(Color(255, 245, 245, 247));
    canvas.FillRectangle(&labelBackground, 0, 0, labelWidth, sheetHeight);

    std::vector<BYTE> pixels(static_cast<size_t>(islandWidth) * islandHeight * 4);
    FontFamily family(L"Segoe UI");
    Font labelFont(&family, 11 * scale, FontStyleRegular, UnitPixel);
    SolidBrush labelBrush(Color(255, 90, 90, 95));

    for (int f = 0; f < frames; ++f) {
        // Replay the script up to this moment on a fresh renderer
        IslandRenderer renderer;
        renderer.SetVisible(true, 0.0);
        for (const Step& step : script) {
            if (step.at <= moments[f]) renderer.SetPhase(step.phase, step.at);
        }
        renderer.Render(pixels.data(), islandWidth, islandHeight, islandWidth * 4, moments[f], scale);
        Bitmap frame(islandWidth, islandHeight, islandWidth * 4, PixelFormat32bppPARGB, pixels.data());
        canvas.DrawImage(&frame, labelWidth, f * islandHeight, islandWidth, islandHeight);

        wchar_t label[32];
        swprintf(label, 32, L"t=%.2fs", moments[f]);
        canvas.DrawString(label, -1, &labelFont, PointF(6 * scale, f * islandHeight + 8 * scale), &labelBrush);
    }

    CLSID png;
    if (PngEncoder(&png) && sheet.Save(output, &png, nullptr) == Ok) {
        std::wprintf(L"wrote %ls (%d frames)\n", output, frames);
        return 0;
    }
    return 1;
}
