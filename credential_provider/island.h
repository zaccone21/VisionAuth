// The VisionAuth island: a black pill at the top of the sign-in screen that
// shows what the face check is doing, in the spirit of the iPhone's Dynamic
// Island. Drawn with Direct2D and DirectWrite, animated with springs.
//
// IslandRenderer holds the animation state and draws a frame on any Direct2D
// render target, so the preview tool can render frames to images.
// IslandWindow hosts it in a layered, click-through window inside LogonUI,
// drawn by its own thread in step with the display (DwmFlush).

#pragma once

#include <windows.h>

struct ID2D1RenderTarget;

// Phases shown by the island. The first values match the service phases.
enum IslandPhase : LONG {
    ISLAND_OFFLINE = 0,
    ISLAND_STARTING,
    ISLAND_SEARCHING,
    ISLAND_FACE,
    ISLAND_UNRECOGNIZED,
    ISLAND_MATCH,
    ISLAND_BLOCKED,
};

class IslandRenderer {
  public:
    IslandRenderer();
    ~IslandRenderer();
    IslandRenderer(const IslandRenderer&) = delete;
    IslandRenderer& operator=(const IslandRenderer&) = delete;

    void SetPhase(LONG phase);
    void SetVisible(bool visible);
    // First name for the greeting ("Hola, <name>"); empty for a plain "¡Hola!".
    void SetName(const wchar_t* name);
    // Moves the animation forward by dt seconds.
    void Advance(double dt);
    // True when hidden and nothing is moving any more.
    bool Settled() const;
    // Draws the island centered in a width x height area (pixels) at the
    // target's current transform. Does not clear.
    void Draw(ID2D1RenderTarget* target, float width, float height, float scale);

  private:
    struct Impl;
    Impl* impl_;
};

// The VisionAuth logo: a Face ID style face in a viewfinder, coral on a black
// rounded square. Drawn into `box` (pixels).
void DrawVisionAuthLogo(ID2D1RenderTarget* target, float left, float top, float size);

// The logo as a 32bpp premultiplied DIB, for the sign-in option button.
HBITMAP CreateVisionAuthLogoBitmap(int size);

class IslandWindow {
  public:
    IslandWindow() = default;
    ~IslandWindow() { Destroy(); }
    IslandWindow(const IslandWindow&) = delete;
    IslandWindow& operator=(const IslandWindow&) = delete;

    // Creates the window at the top of the monitor of `owner` (or the primary one).
    bool Create(HWND owner, HINSTANCE module);
    bool Created() const { return window_ != nullptr; }
    void SetPhase(LONG phase);
    void SetVisible(bool visible);
    void SetName(const wchar_t* name);
    void Destroy();

  private:
    static DWORD WINAPI RenderThread(LPVOID parameter);
    static LRESULT CALLBACK WindowProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam);
    void RenderLoop();
    void Wake();

    HWND window_ = nullptr;
    HINSTANCE module_ = nullptr;
    HDC memoryDc_ = nullptr;
    HBITMAP surface_ = nullptr;
    HGDIOBJ previousBitmap_ = nullptr;
    void* bits_ = nullptr;
    int width_ = 0;
    int height_ = 0;
    float scale_ = 1.0f;
    CRITICAL_SECTION lock_ = {};
    bool lockReady_ = false;
    HANDLE thread_ = nullptr;
    HANDLE stop_ = nullptr;
    HANDLE wake_ = nullptr;
    IslandRenderer* renderer_ = nullptr;
};

// Seconds on a monotonic clock.
double IslandNow();
