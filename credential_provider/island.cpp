// Drawing and hosting of the VisionAuth island (see island.h).

#define _WIN32_WINNT 0x0A00
#include "island.h"

#include <gdiplus.h>
#include <math.h>

using namespace Gdiplus;

namespace {

const double kPi = 3.14159265358979323846;

// Layout at 100% scale, in pixels
const float kPillHeight = 76.0f;
const float kIndicator = 46.0f;
const float kPadLeft = 15.0f;
const float kGap = 15.0f;
const float kPadRight = 30.0f;
const float kTitleSize = 13.5f;
const float kStatusSize = 22.0f;
const float kMinWidth = 250.0f;

// Timings, in seconds
const double kAppear = 0.55;
const double kHide = 0.25;
const double kColorBlend = 0.30;
const double kTextFadeOut = 0.14;
const double kTextFadeIn = 0.26;
const double kWidthMove = 0.40;

struct Rgb {
    float r, g, b;
};

Rgb PhaseColor(LONG phase) {
    switch (phase) {
        case ISLAND_STARTING: return {142, 142, 147};
        case ISLAND_SEARCHING: return {229, 229, 234};
        case ISLAND_FACE: return {10, 132, 255};
        case ISLAND_UNRECOGNIZED: return {255, 159, 10};
        case ISLAND_MATCH: return {48, 209, 88};
        case ISLAND_BLOCKED: return {255, 69, 58};
        default: return {255, 69, 58};
    }
}

const wchar_t* PhaseText(LONG phase) {
    switch (phase) {
        case ISLAND_STARTING: return L"Activando la cámara";
        case ISLAND_SEARCHING: return L"Mirá a la cámara";
        case ISLAND_FACE: return L"Te veo…";
        case ISLAND_UNRECOGNIZED: return L"No te reconozco";
        case ISLAND_MATCH: return L"¡Hola!";
        case ISLAND_BLOCKED: return L"Entrá con tu PIN";
        default: return L"Servicio no disponible";
    }
}

double Clamp01(double x) { return x < 0 ? 0 : (x > 1 ? 1 : x); }
double EaseOutCubic(double t) {
    t = Clamp01(t);
    return 1 - pow(1 - t, 3);
}
double EaseInOutCubic(double t) {
    t = Clamp01(t);
    return t < 0.5 ? 4 * t * t * t : 1 - pow(-2 * t + 2, 3) / 2;
}
double EaseOutBack(double t) {
    t = Clamp01(t);
    const double c1 = 1.70158, c3 = c1 + 1;
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2);
}
float Mix(float a, float b, double t) { return static_cast<float>(a + (b - a) * t); }
Rgb MixRgb(Rgb a, Rgb b, double t) { return {Mix(a.r, b.r, t), Mix(a.g, b.g, t), Mix(a.b, b.b, t)}; }
Color WithAlpha(Rgb c, double alpha) {
    return Color(static_cast<BYTE>(Clamp01(alpha) * 255), static_cast<BYTE>(c.r), static_cast<BYTE>(c.g),
                 static_cast<BYTE>(c.b));
}

void AddPill(GraphicsPath& path, float x, float y, float w, float h) {
    float d = h;
    if (w < d) w = d;
    path.AddArc(x, y, d, d, 90, 180);
    path.AddArc(x + w - d, y, d, d, 270, 180);
    path.CloseFigure();
}

const wchar_t* PickFamily(const wchar_t* const* names, int count) {
    for (int i = 0; i < count; ++i) {
        FontFamily family(names[i]);
        if (family.IsAvailable()) return names[i];
    }
    return L"Segoe UI";
}

}  // namespace

struct IslandState {
    LONG phase = ISLAND_STARTING;
    LONG previousPhase = ISLAND_STARTING;
    double phaseSince = 0;
    Rgb colorFrom = PhaseColor(ISLAND_STARTING);
    bool visible = false;
    double visibleSince = -100;
    double hiddenSince = -100;
    float widthFrom = 0;  // pill width (unscaled) when the current move started
    float widthTo = 0;
    double widthSince = -100;
    const wchar_t* statusFamily = nullptr;
    const wchar_t* titleFamily = nullptr;

    Rgb ColorAt(double now) const {
        return MixRgb(colorFrom, PhaseColor(phase), EaseInOutCubic((now - phaseSince) / kColorBlend));
    }
    float WidthAt(double now) const {
        if (widthTo == 0) return 0;
        return Mix(widthFrom, widthTo, EaseOutCubic((now - widthSince) / kWidthMove));
    }
};

// ---------------------------------------------------------------------------

IslandRenderer::IslandRenderer() : state_(new IslandState()) {}
IslandRenderer::~IslandRenderer() { delete state_; }

void IslandRenderer::SetPhase(LONG phase, double now) {
    if (phase == state_->phase) return;
    state_->colorFrom = state_->ColorAt(now);
    state_->previousPhase = state_->phase;
    state_->phase = phase;
    state_->phaseSince = now;
}

void IslandRenderer::SetVisible(bool visible, double now) {
    if (visible == state_->visible) return;
    state_->visible = visible;
    if (visible) {
        state_->visibleSince = now;
        state_->widthTo = 0;  // measured again on the next frame
    } else {
        state_->hiddenSince = now;
    }
}

bool IslandRenderer::Animating(double now) const {
    // Spinners and pulses run continuously while shown; after hiding, only the fade
    return state_->visible || now - state_->hiddenSince < kHide + 0.05;
}

void IslandRenderer::Render(void* bits, int width, int height, int stride, double now, float scale) {
    IslandState& s = *state_;
    Bitmap surface(width, height, stride, PixelFormat32bppPARGB, static_cast<BYTE*>(bits));
    Graphics g(&surface);
    g.SetCompositingMode(CompositingModeSourceCopy);
    SolidBrush clear(Color(0, 0, 0, 0));
    g.FillRectangle(&clear, 0, 0, width, height);
    g.SetCompositingMode(CompositingModeSourceOver);
    g.SetSmoothingMode(SmoothingModeAntiAlias);
    g.SetPixelOffsetMode(PixelOffsetModeHighQuality);
    g.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);

    // Overall presence: grow in with a slight overshoot, fade out when hidden
    double presence, opacity;
    if (s.visible) {
        double t = (now - s.visibleSince) / kAppear;
        presence = EaseOutBack(t);
        opacity = EaseOutCubic(t * 1.6);
    } else {
        double t = (now - s.hiddenSince) / kHide;
        presence = 1 - 0.15 * EaseOutCubic(t);
        opacity = 1 - EaseOutCubic(t);
    }
    if (opacity <= 0.001) return;

    if (!s.statusFamily) {
        static const wchar_t* const statusNames[] = {L"Segoe UI Variable Display Semib", L"Segoe UI Semibold"};
        static const wchar_t* const titleNames[] = {L"Segoe UI Variable Text Semibold", L"Segoe UI Semibold"};
        s.statusFamily = PickFamily(statusNames, 2);
        s.titleFamily = PickFamily(titleNames, 2);
    }
    FontFamily statusFamily(s.statusFamily);
    FontFamily titleFamily(s.titleFamily);
    Font statusFont(&statusFamily, kStatusSize * scale, FontStyleRegular, UnitPixel);
    Font titleFont(&titleFamily, kTitleSize * scale, FontStyleRegular, UnitPixel);
    StringFormat format(StringFormat::GenericTypographic());
    format.SetFormatFlags(format.GetFormatFlags() | StringFormatFlagsNoWrap | StringFormatFlagsMeasureTrailingSpaces);

    // Target width follows the current status text
    RectF measured;
    const wchar_t* text = PhaseText(s.phase);
    g.MeasureString(text, -1, &statusFont, PointF(0, 0), &format, &measured);
    RectF titleMeasured;
    g.MeasureString(L"VISIONAUTH", -1, &titleFont, PointF(0, 0), &format, &titleMeasured);
    float textWidth = (measured.Width > titleMeasured.Width ? measured.Width : titleMeasured.Width) / scale;
    float target = kPadLeft + kIndicator + kGap + textWidth + kPadRight;
    if (target < kMinWidth) target = kMinWidth;
    if (s.widthTo == 0) {
        s.widthFrom = s.widthTo = target;
        s.widthSince = now - kWidthMove;
    } else if (fabs(target - s.widthTo) > 0.5f) {
        s.widthFrom = s.WidthAt(now);
        s.widthTo = target;
        s.widthSince = now;
    }

    // The pill opens from a circle to its full width
    float h = kPillHeight * scale;
    float fullWidth = s.WidthAt(now) * scale;
    float w = static_cast<float>(h + (fullWidth - h) * EaseOutCubic((now - s.visibleSince) / (kAppear * 0.9)));
    if (!s.visible) w = fullWidth;
    w = static_cast<float>(h + (w - h) * (presence > 1 ? 1 : presence));
    float pillH = static_cast<float>(h * (0.86 + 0.14 * (presence > 1.0 ? 1.0 : presence)));

    // Shake sideways when the face was not recognized
    float shake = 0;
    if (s.phase == ISLAND_UNRECOGNIZED) {
        double t = now - s.phaseSince;
        if (t < 0.7) shake = static_cast<float>(sin(t * 46) * 9 * exp(-t * 6) * scale);
    }

    float x = (width - w) / 2 + shake;
    float y = 18 * scale + (h - pillH) / 2;
    Rgb accent = s.ColorAt(now);

    // Soft shadow
    for (int i = 10; i >= 1; --i) {
        GraphicsPath shadow;
        float grow = i * 1.6f * scale;
        AddPill(shadow, x - grow, y - grow + 5 * scale, w + 2 * grow, pillH + 2 * grow);
        SolidBrush brush(Color(static_cast<BYTE>(9 * opacity), 0, 0, 0));
        g.FillPath(&brush, &shadow);
    }

    // Glow around the pill while a face is in view or after a match
    double glow = 0;
    if (s.phase == ISLAND_FACE) glow = 0.35 + 0.25 * sin((now - s.phaseSince) * 5.0);
    if (s.phase == ISLAND_MATCH) glow = 0.9 * (1 - EaseOutCubic((now - s.phaseSince) / 1.2)) + 0.25;
    if (glow > 0) {
        for (int i = 6; i >= 1; --i) {
            GraphicsPath halo;
            float grow = i * 2.2f * scale;
            AddPill(halo, x - grow, y - grow, w + 2 * grow, pillH + 2 * grow);
            SolidBrush brush(WithAlpha(accent, glow * opacity * 0.06 * (7 - i)));
            g.FillPath(&brush, &halo);
        }
    }

    // Body: near-black glass with a faint top highlight and hairline border
    GraphicsPath body;
    AddPill(body, x, y, w, pillH);
    SolidBrush bodyBrush(Color(static_cast<BYTE>(236 * opacity), 16, 16, 19));
    g.FillPath(&bodyBrush, &body);
    {
        // Highlight on the top half only; the blend keeps the gradient from
        // repeating below its end, which drew a hard line across the middle
        LinearGradientBrush shine(PointF(0, y - 1), PointF(0, y + pillH + 1),
                                  Color(static_cast<BYTE>(24 * opacity), 255, 255, 255), Color(0, 255, 255, 255));
        const REAL factors[3] = {0.0f, 1.0f, 1.0f};
        const REAL positions[3] = {0.0f, 0.5f, 1.0f};
        shine.SetBlend(factors, positions, 3);
        g.FillPath(&shine, &body);
    }
    Pen border(Color(static_cast<BYTE>(38 * opacity), 255, 255, 255), 1.0f * scale);
    g.DrawPath(&border, &body);

    // Everything inside is clipped to the pill while it opens
    g.SetClip(&body);

    float r = kIndicator * scale / 2;
    float cx = x + (kPadLeft * scale) + r;
    float cy = y + pillH / 2;
    double phaseTime = now - s.phaseSince;
    // Content fades in once the pill is nearly open, so text is never cut off
    double contentAlpha = opacity * EaseOutCubic((now - s.visibleSince - 0.34) / 0.3);
    if (!s.visible) contentAlpha = opacity;

    if (s.phase == ISLAND_MATCH) {
        // Green disc pops in, then the check draws itself
        double pop = EaseOutBack(phaseTime / 0.32);
        float rr = static_cast<float>(r * pop);
        SolidBrush disc(WithAlpha(accent, contentAlpha));
        g.FillEllipse(&disc, cx - rr, cy - rr, 2 * rr, 2 * rr);
        double draw = EaseOutCubic((phaseTime - 0.18) / 0.28);
        if (draw > 0) {
            PointF a(cx - 0.36f * r, cy + 0.02f * r), b(cx - 0.10f * r, cy + 0.28f * r), c(cx + 0.38f * r, cy - 0.26f * r);
            float firstLength = static_cast<float>(hypot(b.X - a.X, b.Y - a.Y));
            float secondLength = static_cast<float>(hypot(c.X - b.X, c.Y - b.Y));
            float drawn = static_cast<float>(draw * (firstLength + secondLength));
            Pen check(Color(static_cast<BYTE>(255 * contentAlpha), 255, 255, 255), 4.2f * scale);
            check.SetStartCap(LineCapRound);
            check.SetEndCap(LineCapRound);
            check.SetLineJoin(LineJoinRound);
            if (drawn <= firstLength) {
                float k = drawn / firstLength;
                g.DrawLine(&check, a, PointF(a.X + (b.X - a.X) * k, a.Y + (b.Y - a.Y) * k));
            } else {
                float k = (drawn - firstLength) / secondLength;
                PointF points[3] = {a, b, PointF(b.X + (c.X - b.X) * k, b.Y + (c.Y - b.Y) * k)};
                g.DrawLines(&check, points, 3);
            }
        }
    } else if (s.phase == ISLAND_UNRECOGNIZED || s.phase == ISLAND_BLOCKED || s.phase == ISLAND_OFFLINE) {
        // Ring with an exclamation mark
        Pen ring(WithAlpha(accent, contentAlpha), 3.0f * scale);
        g.DrawEllipse(&ring, cx - r + 2 * scale, cy - r + 2 * scale, 2 * r - 4 * scale, 2 * r - 4 * scale);
        Pen bar(WithAlpha(accent, contentAlpha), 3.6f * scale);
        bar.SetStartCap(LineCapRound);
        bar.SetEndCap(LineCapRound);
        g.DrawLine(&bar, cx, cy - 0.42f * r, cx, cy + 0.10f * r);
        SolidBrush dot(WithAlpha(accent, contentAlpha));
        float d = 4.2f * scale;
        g.FillEllipse(&dot, cx - d / 2, cy + 0.34f * r - d / 2, d, d);
    } else {
        // Spinner: a faint track and an arc that breathes while it turns
        float inset = 3 * scale;
        RectF arcBox(cx - r + inset, cy - r + inset, 2 * (r - inset), 2 * (r - inset));
        Pen track(WithAlpha(accent, 0.16 * contentAlpha), 3.4f * scale);
        g.DrawEllipse(&track, arcBox);
        double speed = s.phase == ISLAND_FACE ? 1.9 : (s.phase == ISLAND_STARTING ? 0.8 : 1.15);
        double turn = now * speed * 360.0;
        double sweep = 70 + 160 * (0.5 + 0.5 * sin(now * 3.1));
        Pen arc(WithAlpha(accent, contentAlpha), 3.4f * scale);
        arc.SetStartCap(LineCapRound);
        arc.SetEndCap(LineCapRound);
        g.DrawArc(&arc, arcBox, static_cast<REAL>(fmod(turn, 360.0)), static_cast<REAL>(sweep));
        if (s.phase == ISLAND_FACE) {
            // Pulsing core: "I see you"
            double pulse = 0.5 + 0.5 * sin(now * 6.0);
            float core = static_cast<float>(r * (0.22 + 0.08 * pulse));
            SolidBrush coreBrush(WithAlpha(accent, contentAlpha * (0.65 + 0.35 * pulse)));
            g.FillEllipse(&coreBrush, cx - core, cy - core, 2 * core, 2 * core);
        } else {
            float core = r * 0.16f;
            SolidBrush coreBrush(WithAlpha(accent, contentAlpha * 0.55));
            g.FillEllipse(&coreBrush, cx - core, cy - core, 2 * core, 2 * core);
        }
    }

    // Text: small caps title, large status that cross-fades and slides on change
    float textX = cx + r + kGap * scale;
    float titleY = cy - 26 * scale;
    SolidBrush titleBrush(Color(static_cast<BYTE>(140 * contentAlpha), 255, 255, 255));
    g.DrawString(L"VISIONAUTH", -1, &titleFont, PointF(textX, titleY), &format, &titleBrush);

    float statusY = cy - 7 * scale;
    double outT = phaseTime / kTextFadeOut;
    if (outT < 1 && s.previousPhase != s.phase) {
        double a = 1 - EaseOutCubic(outT);
        SolidBrush oldBrush(Color(static_cast<BYTE>(255 * a * contentAlpha), 255, 255, 255));
        g.DrawString(PhaseText(s.previousPhase), -1, &statusFont,
                     PointF(textX, statusY - static_cast<float>(8 * scale * (1 - a))), &format, &oldBrush);
    }
    double inT = s.previousPhase == s.phase ? 1 : (phaseTime - kTextFadeOut * 0.6) / kTextFadeIn;
    double in = EaseOutCubic(inT);
    if (in > 0) {
        Rgb statusColor = s.phase == ISLAND_MATCH ? MixRgb({255, 255, 255}, accent, 0.55) : Rgb{255, 255, 255};
        SolidBrush brush(WithAlpha(statusColor, in * contentAlpha));
        g.DrawString(text, -1, &statusFont, PointF(textX, statusY + static_cast<float>(8 * scale * (1 - in))), &format,
                     &brush);
    }
    g.ResetClip();
}

// ---------------------------------------------------------------------------

double IslandNow() {
    static LARGE_INTEGER frequency = {};
    if (frequency.QuadPart == 0) QueryPerformanceFrequency(&frequency);
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    return static_cast<double>(counter.QuadPart) / static_cast<double>(frequency.QuadPart);
}

ULONG_PTR IslandStartGdiplus() {
    GdiplusStartupInput input;
    ULONG_PTR token = 0;
    return GdiplusStartup(&token, &input, nullptr) == Ok ? token : 0;
}

void IslandStopGdiplus(ULONG_PTR token) {
    if (token) GdiplusShutdown(token);
}

namespace {
const wchar_t kIslandClass[] = L"VisionAuthIsland";
const UINT_PTR kFrameTimer = 1;
}  // namespace

bool IslandWindow::Create(HWND owner, HINSTANCE module) {
    if (window_) return true;
    module_ = module;
    gdiplusToken_ = IslandStartGdiplus();
    if (!gdiplusToken_) return false;

    HMONITOR monitor = owner ? MonitorFromWindow(owner, MONITOR_DEFAULTTOPRIMARY)
                             : MonitorFromPoint(POINT{0, 0}, MONITOR_DEFAULTTOPRIMARY);
    MONITORINFO info = {};
    info.cbSize = sizeof(info);
    GetMonitorInfoW(monitor, &info);
    UINT dpi = owner ? GetDpiForWindow(owner) : GetDpiForSystem();
    scale_ = dpi ? dpi / 96.0f : 1.0f;

    width_ = static_cast<int>(620 * scale_);
    height_ = static_cast<int>(130 * scale_);
    const RECT& screen = info.rcMonitor;
    position_.x = screen.left + ((screen.right - screen.left) - width_) / 2;
    position_.y = screen.top + static_cast<int>((screen.bottom - screen.top) * 0.06);

    WNDCLASSEXW windowClass = {};
    windowClass.cbSize = sizeof(windowClass);
    windowClass.lpfnWndProc = &WindowProc;
    windowClass.hInstance = module_;
    windowClass.lpszClassName = kIslandClass;
    RegisterClassExW(&windowClass);

    window_ = CreateWindowExW(WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
                              kIslandClass, L"VisionAuth", WS_POPUP, position_.x, position_.y, width_, height_, owner,
                              nullptr, module_, nullptr);
    if (!window_) {
        Destroy();
        return false;
    }
    SetWindowLongPtrW(window_, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(this));

    BITMAPINFO bitmapInfo = {};
    bitmapInfo.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bitmapInfo.bmiHeader.biWidth = width_;
    bitmapInfo.bmiHeader.biHeight = -height_;
    bitmapInfo.bmiHeader.biPlanes = 1;
    bitmapInfo.bmiHeader.biBitCount = 32;
    bitmapInfo.bmiHeader.biCompression = BI_RGB;
    HDC screenDc = GetDC(nullptr);
    memoryDc_ = CreateCompatibleDC(screenDc);
    surface_ = CreateDIBSection(screenDc, &bitmapInfo, DIB_RGB_COLORS, &bits_, nullptr, 0);
    ReleaseDC(nullptr, screenDc);
    if (!memoryDc_ || !surface_ || !bits_) {
        Destroy();
        return false;
    }
    previousBitmap_ = SelectObject(memoryDc_, surface_);

    renderer_ = new IslandRenderer();
    ShowWindow(window_, SW_SHOWNOACTIVATE);
    return true;
}

void IslandWindow::SetPhase(LONG phase) {
    if (!renderer_) return;
    renderer_->SetPhase(phase, IslandNow());
    EnsureTimer();
}

void IslandWindow::SetVisible(bool visible) {
    if (!renderer_) return;
    renderer_->SetVisible(visible, IslandNow());
    EnsureTimer();
}

void IslandWindow::EnsureTimer() {
    if (window_ && !timerRunning_) {
        SetTimer(window_, kFrameTimer, 16, nullptr);
        timerRunning_ = true;
    }
}

void IslandWindow::Tick() {
    if (!renderer_ || !window_) return;
    double now = IslandNow();
    renderer_->Render(bits_, width_, height_, width_ * 4, now, scale_);

    SIZE size = {width_, height_};
    POINT source = {0, 0};
    BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
    UpdateLayeredWindow(window_, nullptr, &position_, &size, memoryDc_, &source, 0, &blend, ULW_ALPHA);
    // Stay above LogonUI's own windows
    SetWindowPos(window_, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);

    if (!renderer_->Animating(now)) {
        KillTimer(window_, kFrameTimer);
        timerRunning_ = false;
    }
}

LRESULT CALLBACK IslandWindow::WindowProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_TIMER && wparam == kFrameTimer) {
        auto* self = reinterpret_cast<IslandWindow*>(GetWindowLongPtrW(window, GWLP_USERDATA));
        if (self) self->Tick();
        return 0;
    }
    if (message == WM_MOUSEACTIVATE) return MA_NOACTIVATE;
    return DefWindowProcW(window, message, wparam, lparam);
}

void IslandWindow::Destroy() {
    if (window_) {
        KillTimer(window_, kFrameTimer);
        SetWindowLongPtrW(window_, GWLP_USERDATA, 0);
        DestroyWindow(window_);
        window_ = nullptr;
        UnregisterClassW(kIslandClass, module_);
    }
    timerRunning_ = false;
    delete renderer_;
    renderer_ = nullptr;
    if (memoryDc_) {
        if (previousBitmap_) SelectObject(memoryDc_, previousBitmap_);
        DeleteDC(memoryDc_);
        memoryDc_ = nullptr;
    }
    if (surface_) {
        DeleteObject(surface_);
        surface_ = nullptr;
    }
    bits_ = nullptr;
    previousBitmap_ = nullptr;
    IslandStopGdiplus(gdiplusToken_);
    gdiplusToken_ = 0;
}
