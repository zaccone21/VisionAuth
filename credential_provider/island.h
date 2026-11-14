// The VisionAuth "island": a pill at the top of the sign-in screen that shows
// what the face check is doing, with animated transitions.
//
// IslandRenderer draws one frame for a given time; it has no window, so the
// preview tool can render frames to images. IslandWindow hosts it in a
// layered, click-through window inside LogonUI, driven by a timer.

#pragma once

#include <windows.h>

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

struct IslandState;

class IslandRenderer {
  public:
    IslandRenderer();
    ~IslandRenderer();
    IslandRenderer(const IslandRenderer&) = delete;
    IslandRenderer& operator=(const IslandRenderer&) = delete;

    void SetPhase(LONG phase, double now);
    void SetVisible(bool visible, double now);
    // True while something is still moving (the window keeps its timer running).
    bool Animating(double now) const;
    // Draws the frame for time `now` (seconds) on a 32bpp premultiplied ARGB
    // surface of width x height pixels, at the given DPI scale.
    void Render(void* bits, int width, int height, int stride, double now, float scale);

  private:
    IslandState* state_;
};

class IslandWindow {
  public:
    IslandWindow() = default;
    ~IslandWindow() { Destroy(); }
    IslandWindow(const IslandWindow&) = delete;
    IslandWindow& operator=(const IslandWindow&) = delete;

    // Creates the window over the monitor of `owner` (or the primary one).
    bool Create(HWND owner, HINSTANCE module);
    bool Created() const { return window_ != nullptr; }
    void SetPhase(LONG phase);
    void SetVisible(bool visible);
    void Destroy();

  private:
    static LRESULT CALLBACK WindowProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam);
    void Tick();
    void EnsureTimer();

    HWND window_ = nullptr;
    HINSTANCE module_ = nullptr;
    HDC memoryDc_ = nullptr;
    HBITMAP surface_ = nullptr;
    HGDIOBJ previousBitmap_ = nullptr;
    void* bits_ = nullptr;
    int width_ = 0;
    int height_ = 0;
    POINT position_ = {};
    float scale_ = 1.0f;
    bool timerRunning_ = false;
    ULONG_PTR gdiplusToken_ = 0;
    IslandRenderer* renderer_ = nullptr;
};

// Seconds on a monotonic clock.
double IslandNow();

// GDI+ must be started before rendering; IslandWindow does it itself.
ULONG_PTR IslandStartGdiplus();
void IslandStopGdiplus(ULONG_PTR token);
