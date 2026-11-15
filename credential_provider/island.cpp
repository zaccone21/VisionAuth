// Drawing, animation and hosting of the VisionAuth island (see island.h).

#define _WIN32_WINNT 0x0A00
#include "island.h"

#include <d2d1.h>
#include <dwmapi.h>
#include <dwrite.h>
#include <math.h>
#include <string.h>
#include <wchar.h>

#include <initializer_list>

namespace {

const float kPi = 3.14159265f;

// Palette: Apple's pure black island with Claude's warm cream and coral
struct Rgb {
    float r, g, b;
};
const Rgb kCream = {0.961f, 0.953f, 0.925f};
const Rgb kWarmGray = {0.651f, 0.631f, 0.596f};
const Rgb kDimGray = {0.455f, 0.443f, 0.42f};
const Rgb kCoral = {0.851f, 0.467f, 0.341f};
const Rgb kAmber = {0.961f, 0.643f, 0.231f};
const Rgb kGreen = {0.188f, 0.820f, 0.345f};
const Rgb kRed = {0.898f, 0.329f, 0.294f};

Rgb PhaseAccent(LONG phase) {
    switch (phase) {
        case ISLAND_STARTING: return kWarmGray;
        case ISLAND_SEARCHING: return kCream;
        case ISLAND_FACE: return kAmber;
        case ISLAND_UNRECOGNIZED: return kRed;
        case ISLAND_MATCH: return kGreen;
        case ISLAND_AWAY: return kDimGray;
        default: return kRed;
    }
}

double PhaseGlow(LONG phase) {
    switch (phase) {
        case ISLAND_FACE: return 0.55;
        case ISLAND_MATCH: return 1.0;
        case ISLAND_UNRECOGNIZED: return 0.5;
        default: return 0.0;
    }
}

// Layout at 100% scale, in pixels
const float kCompactHeight = 84.0f;
const float kSuccessHeight = 104.0f;
const float kGlyph = 50.0f;
const float kSuccessGlyph = 64.0f;
const float kTextGap = 18.0f;
const float kPadRight = 40.0f;
const float kLineGap = 3.0f;  // between the label and the status line
// Waiting with nobody in view, the label grows into the only line
const float kBrandScale = 1.85f;
const Rgb kBrandGray = {0.56f, 0.548f, 0.525f};
const float kTopMargin = 22.0f;

float Clamp01(double x) { return static_cast<float>(x < 0 ? 0 : (x > 1 ? 1 : x)); }
float EaseOutCubic(double t) {
    float c = Clamp01(t);
    return 1 - (1 - c) * (1 - c) * (1 - c);
}
float SmoothStep(double t) {
    float c = Clamp01(t);
    return c * c * (3 - 2 * c);
}

// A damped spring: x follows target with the feel set by stiffness and damping.
struct Spring {
    double x = 0, v = 0, target = 0;
    void Step(double dt, double stiffness, double damping) {
        // Small substeps keep it stable whatever the frame rate
        while (dt > 0) {
            double h = dt > 1.0 / 240 ? 1.0 / 240 : dt;
            double a = -stiffness * (x - target) - damping * v;
            v += a * h;
            x += v * h;
            dt -= h;
        }
    }
    bool Resting() const { return fabs(x - target) < 0.001 && fabs(v) < 0.01; }
    void Snap(double value) {
        x = target = value;
        v = 0;
    }
};

IDWriteFactory* WriteFactory() {
    static IDWriteFactory* factory = nullptr;
    if (!factory) {
        DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory),
                            reinterpret_cast<IUnknown**>(&factory));
    }
    return factory;
}

template <typename T>
void SafeRelease(T*& p) {
    if (p) {
        p->Release();
        p = nullptr;
    }
}

D2D1_COLOR_F ColorOf(Rgb c, float alpha) { return D2D1::ColorF(c.r, c.g, c.b, alpha); }

// The Face ID style glyph: four viewfinder corners and a simple face.
// look moves the face inside the frame, mouth goes from -1 (frown) to 1 (smile),
// angry adds brows slanting down toward the nose.
void DrawFace(ID2D1RenderTarget* target, ID2D1Factory* factory, ID2D1StrokeStyle* round, ID2D1Brush* brush,
              float cx, float cy, float size, float lookX, float lookY, float mouth, bool angry = false) {
    float half = size / 2, corner = size * 0.30f, radius = size * 0.17f, stroke = size * 0.072f;
    float x0 = cx - half, y0 = cy - half, x1 = cx + half, y1 = cy + half;

    ID2D1PathGeometry* path = nullptr;
    if (FAILED(factory->CreatePathGeometry(&path))) return;
    ID2D1GeometrySink* sink = nullptr;
    if (SUCCEEDED(path->Open(&sink))) {
        auto cornerPath = [&](D2D1_POINT_2F a, D2D1_POINT_2F b, D2D1_POINT_2F c, D2D1_POINT_2F d) {
            sink->BeginFigure(a, D2D1_FIGURE_BEGIN_HOLLOW);
            sink->AddLine(b);
            sink->AddArc(D2D1::ArcSegment(c, D2D1::SizeF(radius, radius), 0, D2D1_SWEEP_DIRECTION_CLOCKWISE,
                                          D2D1_ARC_SIZE_SMALL));
            sink->AddLine(d);
            sink->EndFigure(D2D1_FIGURE_END_OPEN);
        };
        cornerPath({x0, y0 + corner}, {x0, y0 + radius}, {x0 + radius, y0}, {x0 + corner, y0});
        cornerPath({x1 - corner, y0}, {x1 - radius, y0}, {x1, y0 + radius}, {x1, y0 + corner});
        cornerPath({x1, y1 - corner}, {x1, y1 - radius}, {x1 - radius, y1}, {x1 - corner, y1});
        cornerPath({x0 + corner, y1}, {x0 + radius, y1}, {x0, y1 - radius}, {x0, y1 - corner});

        float fx = cx + lookX, fy = cy + lookY;
        // Eyes
        for (float side : {-1.0f, 1.0f}) {
            sink->BeginFigure({fx + side * size * 0.155f, fy - size * 0.155f}, D2D1_FIGURE_BEGIN_HOLLOW);
            sink->AddLine({fx + side * size * 0.155f, fy - size * 0.065f});
            sink->EndFigure(D2D1_FIGURE_END_OPEN);
        }
        if (angry) {
            for (float side : {-1.0f, 1.0f}) {
                sink->BeginFigure({fx + side * size * 0.25f, fy - size * 0.255f}, D2D1_FIGURE_BEGIN_HOLLOW);
                sink->AddLine({fx + side * size * 0.085f, fy - size * 0.195f});
                sink->EndFigure(D2D1_FIGURE_END_OPEN);
            }
        }
        // Nose
        sink->BeginFigure({fx + size * 0.02f, fy - size * 0.135f}, D2D1_FIGURE_BEGIN_HOLLOW);
        sink->AddLine({fx + size * 0.02f, fy + size * 0.045f});
        sink->AddLine({fx - size * 0.045f, fy + size * 0.045f});
        sink->EndFigure(D2D1_FIGURE_END_OPEN);
        // Mouth: a frown hangs from the line instead of rising toward the nose
        float mouthY = fy + size * (0.165f + (mouth < 0 ? -mouth * 0.065f : 0));
        sink->BeginFigure({fx - size * 0.155f, mouthY}, D2D1_FIGURE_BEGIN_HOLLOW);
        sink->AddQuadraticBezier(
            D2D1::QuadraticBezierSegment({fx, mouthY + size * 0.13f * mouth}, {fx + size * 0.155f, mouthY}));
        sink->EndFigure(D2D1_FIGURE_END_OPEN);
        sink->Close();
        sink->Release();
        target->DrawGeometry(path, brush, stroke, round);
    }
    path->Release();
}

}  // namespace

// ---------------------------------------------------------------------------

struct IslandRenderer::Impl {
    LONG phase = ISLAND_STARTING;
    LONG previousPhase = ISLAND_STARTING;
    bool visible = false;
    double time = 0;       // total animation time
    double phaseTime = 0;  // time in the current phase
    wchar_t name[64] = L"";

    Spring presence;  // 0 hidden .. 1 shown (overshoots a little)
    Spring width, height, shake, glow, textIn, success;
    Spring brand;  // 0 small label above the status .. 1 large and alone
    Spring r, g, b;
    bool sized = false;

    // Text formats, created for the scale they were last used at
    float formatScale = 0;
    IDWriteTextFormat* label = nullptr;
    IDWriteTextFormat* status = nullptr;
    IDWriteTextFormat* greeting = nullptr;

    ~Impl() { ReleaseFormats(); }
    void ReleaseFormats() {
        SafeRelease(label);
        SafeRelease(status);
        SafeRelease(greeting);
    }

    void EnsureFormats(float scale) {
        if (formatScale == scale && label) return;
        ReleaseFormats();
        formatScale = scale;
        IDWriteFactory* write = WriteFactory();
        if (!write) return;
        write->CreateTextFormat(L"Segoe UI Variable Text", nullptr, DWRITE_FONT_WEIGHT_SEMI_BOLD,
                                DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 14.5f * scale, L"es-ar", &label);
        write->CreateTextFormat(L"Segoe UI Variable Display", nullptr, DWRITE_FONT_WEIGHT_SEMI_BOLD,
                                DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 24.0f * scale, L"es-ar", &status);
        write->CreateTextFormat(L"Segoe UI Variable Display", nullptr, DWRITE_FONT_WEIGHT_SEMI_BOLD,
                                DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 31.0f * scale, L"es-ar",
                                &greeting);
        for (IDWriteTextFormat* format : {label, status, greeting}) {
            if (format) format->SetWordWrapping(DWRITE_WORD_WRAPPING_NO_WRAP);
        }
    }

    void Text(LONG forPhase, wchar_t* out, size_t capacity) const {
        const wchar_t* text;
        switch (forPhase) {
            case ISLAND_STARTING: text = L"Preparando la cámara"; break;
            case ISLAND_SEARCHING: text = L"Mirá a la cámara"; break;
            case ISLAND_FACE: text = L"Verificando…"; break;
            case ISLAND_UNRECOGNIZED: text = L"No te reconozco"; break;
            case ISLAND_BLOCKED: text = L"Entrá con tu PIN"; break;
            case ISLAND_AWAY: text = L""; break;  // the label takes the line
            case ISLAND_MATCH:
                if (name[0]) {
                    swprintf(out, capacity, L"Hola, %ls", name);
                    return;
                }
                text = L"¡Hola!";
                break;
            default: text = L"VisionAuth no está activo"; break;
        }
        wcsncpy(out, text, capacity - 1);
        out[capacity - 1] = L'\0';
    }

    IDWriteTextLayout* Layout(LONG forPhase) {
        wchar_t text[96];
        Text(forPhase, text, 96);
        IDWriteTextFormat* format = forPhase == ISLAND_MATCH ? greeting : status;
        IDWriteTextLayout* layout = nullptr;
        if (format) WriteFactory()->CreateTextLayout(text, static_cast<UINT32>(wcslen(text)), format, 2000, 200, &layout);
        return layout;
    }
};

IslandRenderer::IslandRenderer() : impl_(new Impl()) {
    Rgb accent = PhaseAccent(impl_->phase);
    impl_->r.Snap(accent.r);
    impl_->g.Snap(accent.g);
    impl_->b.Snap(accent.b);
    impl_->textIn.Snap(1);
    impl_->height.Snap(kCompactHeight);
}

IslandRenderer::~IslandRenderer() { delete impl_; }

void IslandRenderer::SetName(const wchar_t* name) {
    wcsncpy(impl_->name, name ? name : L"", 63);
    impl_->name[63] = L'\0';
}

void IslandRenderer::SetPhase(LONG phase) {
    Impl& s = *impl_;
    if (phase == s.phase) return;
    s.previousPhase = s.phase;
    s.phase = phase;
    s.phaseTime = 0;
    Rgb accent = PhaseAccent(phase);
    s.r.target = accent.r;
    s.g.target = accent.g;
    s.b.target = accent.b;
    s.glow.target = PhaseGlow(phase);
    s.textIn.x = 0;
    s.textIn.v = 0;
    s.textIn.target = 1;
    s.success.target = phase == ISLAND_MATCH ? 1 : 0;
    s.height.target = phase == ISLAND_MATCH ? kSuccessHeight : kCompactHeight;
    if (phase == ISLAND_UNRECOGNIZED) s.shake.v = 1100;  // a quick "no" shake
    s.brand.target = phase == ISLAND_AWAY ? 1 : 0;
}

void IslandRenderer::SetVisible(bool visible) {
    impl_->visible = visible;
    impl_->presence.target = visible ? 1 : 0;
}

bool IslandRenderer::Settled() const { return !impl_->visible && impl_->presence.x < 0.002 && fabs(impl_->presence.v) < 0.01; }

void IslandRenderer::Advance(double dt) {
    Impl& s = *impl_;
    s.time += dt;
    s.phaseTime += dt;
    s.presence.Step(dt, 210, 19);
    s.width.Step(dt, 320, 28);
    s.height.Step(dt, 320, 26);
    s.shake.Step(dt, 900, 13);
    s.glow.Step(dt, 110, 22);
    s.textIn.Step(dt, 240, 31);
    s.success.Step(dt, 260, 19);
    s.brand.Step(dt, 170, 24);
    s.r.Step(dt, 150, 25);
    s.g.Step(dt, 150, 25);
    s.b.Step(dt, 150, 25);
}

void IslandRenderer::Draw(ID2D1RenderTarget* target, float areaWidth, float, float scale) {
    Impl& s = *impl_;
    float presence = static_cast<float>(s.presence.x);
    if (presence <= 0.002f) return;
    s.EnsureFormats(scale);
    if (!s.label || !s.status || !s.greeting) return;

    ID2D1Factory* factory = nullptr;
    target->GetFactory(&factory);
    ID2D1StrokeStyle* round = nullptr;
    factory->CreateStrokeStyle(D2D1::StrokeStyleProperties(D2D1_CAP_STYLE_ROUND, D2D1_CAP_STYLE_ROUND,
                                                           D2D1_CAP_STYLE_ROUND, D2D1_LINE_JOIN_ROUND),
                               nullptr, 0, &round);
    target->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
    target->SetAntialiasMode(D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);

    // Measure the texts to size the pill
    IDWriteTextLayout* labelLayout = nullptr;
    WriteFactory()->CreateTextLayout(L"VisionAuth", 10, s.label, 2000, 200, &labelLayout);
    IDWriteTextLayout* lineLayout = nullptr;
    WriteFactory()->CreateTextLayout(L"VisionAuth", 10, s.status, 2000, 200, &lineLayout);
    IDWriteTextLayout* current = s.Layout(s.phase);
    IDWriteTextLayout* previous = s.previousPhase != s.phase ? s.Layout(s.previousPhase) : nullptr;
    DWRITE_TEXT_METRICS labelMetrics = {}, currentMetrics = {}, previousMetrics = {}, lineMetrics = {};
    if (labelLayout) labelLayout->GetMetrics(&labelMetrics);
    if (lineLayout) lineLayout->GetMetrics(&lineMetrics);
    SafeRelease(lineLayout);
    bool away = s.phase == ISLAND_AWAY;
    if (away) currentMetrics.height = lineMetrics.height;
    if (current) current->GetMetrics(&currentMetrics);
    if (previous) previous->GetMetrics(&previousMetrics);

    float successAmount = Clamp01(s.success.x);
    float compactHeight = static_cast<float>(s.height.x);
    float glyphUnscaled = kGlyph + (kSuccessGlyph - kGlyph) * successAmount;
    float inset = (compactHeight - glyphUnscaled) / 2;
    float labelWidth = labelMetrics.width * (away ? kBrandScale : 1);
    float textWidth = (currentMetrics.widthIncludingTrailingWhitespace > labelWidth
                           ? currentMetrics.widthIncludingTrailingWhitespace
                           : labelWidth) /
                      scale;
    float targetWidth = inset + glyphUnscaled + kTextGap + textWidth + kPadRight;
    if (!s.sized) {
        s.width.Snap(targetWidth);
        s.sized = true;
    } else {
        s.width.target = targetWidth;
    }

    // Pill: opens from a circle, scales in with a little overshoot
    float h = compactHeight * scale;
    float fullWidth = static_cast<float>(s.width.x) * scale;
    float open = SmoothStep((presence - 0.12) / 0.8);
    float w = h + (fullWidth - h) * open;
    float grow = 0.55f + 0.45f * presence;
    float pillW = w * grow, pillH = h * grow;
    float alpha = Clamp01(presence * 1.8);
    float cx = areaWidth / 2 + static_cast<float>(s.shake.x) * scale * 0.012f;
    float top = kTopMargin * scale + (h - pillH) / 2;
    D2D1_RECT_F pill = D2D1::RectF(cx - pillW / 2, top, cx + pillW / 2, top + pillH);
    float radius = pillH / 2;
    Rgb accent = {static_cast<float>(s.r.x), static_cast<float>(s.g.x), static_cast<float>(s.b.x)};

    ID2D1SolidColorBrush* brush = nullptr;
    target->CreateSolidColorBrush(D2D1::ColorF(0, 0, 0, 0), &brush);
    if (!brush) {
        SafeRelease(round);
        factory->Release();
        return;
    }

    // Soft shadow
    for (int i = 6; i >= 1; --i) {
        float spread = i * 2.2f * scale;
        brush->SetColor(D2D1::ColorF(0, 0, 0, 0.045f * alpha));
        D2D1_RECT_F r = D2D1::RectF(pill.left - spread, pill.top - spread + 5 * scale, pill.right + spread,
                                    pill.bottom + spread + 5 * scale);
        target->FillRoundedRectangle(D2D1::RoundedRect(r, radius + spread, radius + spread), brush);
    }

    // Colored glow beneath the pill
    float glow = Clamp01(s.glow.x) * alpha;
    if (s.phase == ISLAND_FACE) glow *= 0.8f + 0.2f * sinf(static_cast<float>(s.phaseTime) * 4.0f);
    if (glow > 0.01f) {
        D2D1_GRADIENT_STOP stops[2] = {{0.0f, ColorOf(accent, 0.55f * glow)}, {1.0f, ColorOf(accent, 0.0f)}};
        ID2D1GradientStopCollection* collection = nullptr;
        target->CreateGradientStopCollection(stops, 2, &collection);
        if (collection) {
            ID2D1RadialGradientBrush* halo = nullptr;
            D2D1_POINT_2F center = D2D1::Point2F(cx, pill.top + pillH * 0.62f);
            target->CreateRadialGradientBrush(
                D2D1::RadialGradientBrushProperties(center, D2D1::Point2F(0, 0), pillW * 0.62f, pillH * 1.25f),
                collection, &halo);
            if (halo) {
                target->FillEllipse(D2D1::Ellipse(center, pillW * 0.62f, pillH * 1.25f), halo);
                halo->Release();
            }
            collection->Release();
        }
    }

    // Body: smoked glass. The sign-in screen behind it is already blurred, so
    // a translucent tint reads as frosted glass without capturing the screen.
    D2D1_ROUNDED_RECT body = D2D1::RoundedRect(pill, radius, radius);
    // Tint: a touch lighter at the top, like a dark material lit from above
    {
        D2D1_GRADIENT_STOP stops[2] = {{0.0f, D2D1::ColorF(0.165f, 0.16f, 0.155f, 0.64f * alpha)},
                                       {1.0f, D2D1::ColorF(0.06f, 0.058f, 0.055f, 0.74f * alpha)}};
        ID2D1GradientStopCollection* collection = nullptr;
        target->CreateGradientStopCollection(stops, 2, &collection);
        ID2D1LinearGradientBrush* tint = nullptr;
        if (collection) {
            target->CreateLinearGradientBrush(
                D2D1::LinearGradientBrushProperties({0, pill.top}, {0, pill.bottom}), collection, &tint);
        }
        if (tint) target->FillRoundedRectangle(body, tint);
        SafeRelease(tint);
        SafeRelease(collection);
    }
    // A faint wash of the current accent, like light caught in the glass
    brush->SetColor(ColorOf(accent, 0.05f * alpha));
    target->FillRoundedRectangle(body, brush);
    // Soft highlight across the top third
    {
        D2D1_GRADIENT_STOP stops[2] = {{0.0f, D2D1::ColorF(1, 1, 1, 0.09f * alpha)},
                                       {1.0f, D2D1::ColorF(1, 1, 1, 0.0f)}};
        ID2D1GradientStopCollection* collection = nullptr;
        target->CreateGradientStopCollection(stops, 2, &collection);
        ID2D1LinearGradientBrush* sheen = nullptr;
        if (collection) {
            target->CreateLinearGradientBrush(
                D2D1::LinearGradientBrushProperties({0, pill.top}, {0, pill.top + pillH * 0.4f}), collection,
                &sheen);
        }
        if (sheen) {
            D2D1_RECT_F band = D2D1::RectF(pill.left, pill.top, pill.right, pill.top + pillH * 0.4f);
            ID2D1RoundedRectangleGeometry* shape = nullptr;
            factory->CreateRoundedRectangleGeometry(body, &shape);
            ID2D1RectangleGeometry* bandShape = nullptr;
            factory->CreateRectangleGeometry(band, &bandShape);
            if (shape && bandShape) {
                ID2D1PathGeometry* top = nullptr;
                factory->CreatePathGeometry(&top);
                ID2D1GeometrySink* sink = nullptr;
                if (top && SUCCEEDED(top->Open(&sink))) {
                    shape->CombineWithGeometry(bandShape, D2D1_COMBINE_MODE_INTERSECT, nullptr, sink);
                    sink->Close();
                    sink->Release();
                    target->FillGeometry(top, sheen);
                }
                SafeRelease(top);
            }
            SafeRelease(bandShape);
            SafeRelease(shape);
        }
        SafeRelease(sheen);
        SafeRelease(collection);
    }
    // Rim: a bright hairline on top fading to a dim one at the bottom
    {
        D2D1_GRADIENT_STOP stops[2] = {{0.0f, D2D1::ColorF(1, 1, 1, 0.24f * alpha)},
                                       {1.0f, D2D1::ColorF(1, 1, 1, 0.05f * alpha)}};
        ID2D1GradientStopCollection* collection = nullptr;
        target->CreateGradientStopCollection(stops, 2, &collection);
        ID2D1LinearGradientBrush* rim = nullptr;
        if (collection) {
            target->CreateLinearGradientBrush(
                D2D1::LinearGradientBrushProperties({0, pill.top}, {0, pill.bottom}), collection, &rim);
        }
        if (rim) {
            target->DrawRoundedRectangle(D2D1::RoundedRect(pill, radius - 0.5f, radius - 0.5f), rim,
                                         1.2f * scale);
        }
        SafeRelease(rim);
        SafeRelease(collection);
    }

    ID2D1RoundedRectangleGeometry* clip = nullptr;
    factory->CreateRoundedRectangleGeometry(D2D1::RoundedRect(pill, radius, radius), &clip);
    ID2D1Layer* layer = nullptr;
    target->CreateLayer(&layer);
    if (clip && layer) {
        target->PushLayer(D2D1::LayerParameters(D2D1::InfiniteRect(), clip), layer);
    }

    float content = Clamp01((presence - 0.55) / 0.4) * alpha;
    float glyph = glyphUnscaled * scale * grow;
    float glyphInset = (pillH - glyph) / 2;
    float gx = pill.left + glyphInset + glyph / 2;
    float gy = pill.top + pillH / 2;
    float t = static_cast<float>(s.time);
    float pt = static_cast<float>(s.phaseTime);

    // Face glyph, fading out as the success disc comes in
    float faceAlpha = content * (1 - Clamp01(successAmount * 1.7));
    if (faceAlpha > 0.01f) {
        // The face stays still: waiting states only pulse in brightness
        float breathe = 1, lookX = 0, lookY = 0, mouth = 0.35f;
        float faceAlphaScale = 1;
        switch (s.phase) {
            case ISLAND_STARTING: faceAlphaScale = 0.55f + 0.3f * sinf(t * 3.2f); break;
            case ISLAND_SEARCHING: faceAlphaScale = 0.8f + 0.2f * sinf(t * 2.2f); break;
            case ISLAND_FACE: mouth = 1; break;
            case ISLAND_UNRECOGNIZED: mouth = -0.85f; break;
            case ISLAND_MATCH: mouth = 1; break;
            case ISLAND_AWAY:
                // Greyed out and still, like a disabled control
                mouth = 0;
                faceAlphaScale = 0.75f;
                break;
            default: mouth = -0.6f; break;
        }
        float size = glyph * breathe * (1 - 0.3f * successAmount);
        brush->SetColor(ColorOf(accent, faceAlpha * faceAlphaScale));
        DrawFace(target, factory, round, brush, gx, gy, size, lookX * size, lookY * size, mouth,
                 s.phase == ISLAND_UNRECOGNIZED);

        if (s.phase == ISLAND_FACE) {
            // Scan line sweeping down the frame
            float sweep = fmodf(pt * 0.85f, 1.0f);
            float y = gy - size * 0.42f + sweep * size * 0.84f;
            float fade = sinf(sweep * kPi);
            brush->SetColor(ColorOf(accent, 0.75f * fade * faceAlpha));
            target->DrawLine({gx - size * 0.36f, y}, {gx + size * 0.36f, y}, brush, size * 0.045f, round);
        }
    }

    // Success: a green disc pops in and the check draws itself
    if (successAmount > 0.01f || s.success.x > 0.01) {
        float pop = static_cast<float>(s.success.x);
        float discR = glyph / 2 * (pop < 0 ? 0 : pop);
        brush->SetColor(ColorOf(kGreen, content * Clamp01(pop * 2)));
        target->FillEllipse(D2D1::Ellipse({gx, gy}, discR, discR), brush);
        float draw = s.phase == ISLAND_MATCH ? EaseOutCubic((pt - 0.14) / 0.3) : 1;
        if (draw > 0 && discR > 1) {
            D2D1_POINT_2F a = {gx - 0.42f * discR, gy + 0.02f * discR};
            D2D1_POINT_2F b = {gx - 0.12f * discR, gy + 0.31f * discR};
            D2D1_POINT_2F c = {gx + 0.44f * discR, gy - 0.30f * discR};
            float first = hypotf(b.x - a.x, b.y - a.y), second = hypotf(c.x - b.x, c.y - b.y);
            float drawn = draw * (first + second);
            brush->SetColor(D2D1::ColorF(1, 1, 1, content * Clamp01(pop * 2)));
            float stroke = discR * 0.19f;
            if (drawn <= first) {
                float k = drawn / first;
                target->DrawLine(a, {a.x + (b.x - a.x) * k, a.y + (b.y - a.y) * k}, brush, stroke, round);
            } else {
                float k = (drawn - first) / second;
                target->DrawLine(a, b, brush, stroke, round);
                target->DrawLine(b, {b.x + (c.x - b.x) * k, b.y + (c.y - b.y) * k}, brush, stroke, round);
            }
        }
    }

    // Text: brand label above, status below, cross-fading and sliding on change
    float textX = gx + glyph / 2 + kTextGap * scale;
    float in = Clamp01(s.textIn.x);
    float labelH = labelMetrics.height;
    auto drawStatus = [&](IDWriteTextLayout* layout, const DWRITE_TEXT_METRICS& metrics, float opacity, float dy) {
        if (!layout || opacity <= 0.01f) return;
        float blockH = labelH + kLineGap * scale + metrics.height;
        float y = gy - blockH / 2 + labelH + kLineGap * scale + dy;
        brush->SetColor(ColorOf(kCream, opacity));
        target->DrawTextLayout({textX, y}, layout, brush, D2D1_DRAW_TEXT_OPTIONS_NONE);
    };
    if (labelLayout) {
        // Above the status line, or grown and centered alone while waiting
        float b = static_cast<float>(s.brand.x);
        float k = 1 + (kBrandScale - 1) * b;
        float blockH = labelH + kLineGap * scale + currentMetrics.height;
        float y = gy - blockH / 2 + (blockH / 2 - labelH * kBrandScale / 2) * b;
        float g = Clamp01(b);
        Rgb color = {kWarmGray.r + (kBrandGray.r - kWarmGray.r) * g, kWarmGray.g + (kBrandGray.g - kWarmGray.g) * g,
                     kWarmGray.b + (kBrandGray.b - kWarmGray.b) * g};
        brush->SetColor(ColorOf(color, content));
        D2D1_MATRIX_3X2_F base;
        target->GetTransform(&base);
        target->SetTransform(D2D1::Matrix3x2F::Scale(k, k, {textX, y}) * base);
        target->DrawTextLayout({textX, y}, labelLayout, brush, D2D1_DRAW_TEXT_OPTIONS_NONE);
        target->SetTransform(base);
    }
    // One after the other, never on top of each other: the old text leaves in
    // the first part of the transition, the new one arrives after it
    drawStatus(previous, previousMetrics, content * (1 - Clamp01(in * 2.4)), -10 * scale * in);
    drawStatus(current, currentMetrics, content * Clamp01((in - 0.32) / 0.68), 10 * scale * (1 - in));

    if (clip && layer) target->PopLayer();
    SafeRelease(layer);
    SafeRelease(clip);
    SafeRelease(labelLayout);
    SafeRelease(current);
    SafeRelease(previous);
    brush->Release();
    SafeRelease(round);
    factory->Release();
}

// ---------------------------------------------------------------------------

void DrawVisionAuthLogo(ID2D1RenderTarget* target, float left, float top, float size) {
    ID2D1Factory* factory = nullptr;
    target->GetFactory(&factory);
    ID2D1StrokeStyle* round = nullptr;
    factory->CreateStrokeStyle(D2D1::StrokeStyleProperties(D2D1_CAP_STYLE_ROUND, D2D1_CAP_STYLE_ROUND,
                                                           D2D1_CAP_STYLE_ROUND, D2D1_LINE_JOIN_ROUND),
                               nullptr, 0, &round);
    target->SetAntialiasMode(D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);

    D2D1_RECT_F box = D2D1::RectF(left, top, left + size, top + size);
    D2D1_GRADIENT_STOP stops[2] = {{0.0f, D2D1::ColorF(0.17f, 0.16f, 0.15f, 1)},
                                   {1.0f, D2D1::ColorF(0.05f, 0.05f, 0.045f, 1)}};
    ID2D1GradientStopCollection* collection = nullptr;
    target->CreateGradientStopCollection(stops, 2, &collection);
    ID2D1LinearGradientBrush* background = nullptr;
    if (collection) {
        target->CreateLinearGradientBrush(
            D2D1::LinearGradientBrushProperties({left, top}, {left, top + size}), collection, &background);
    }
    float corner = size * 0.225f;
    if (background) target->FillRoundedRectangle(D2D1::RoundedRect(box, corner, corner), background);

    ID2D1SolidColorBrush* brush = nullptr;
    target->CreateSolidColorBrush(ColorOf(kCoral, 1), &brush);
    if (brush) {
        DrawFace(target, factory, round, brush, left + size / 2, top + size / 2, size * 0.56f, 0, 0, 1);
        brush->Release();
    }
    SafeRelease(background);
    SafeRelease(collection);
    SafeRelease(round);
    factory->Release();
}

HBITMAP CreateVisionAuthLogoBitmap(int size) {
    BITMAPINFO info = {};
    info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    info.bmiHeader.biWidth = size;
    info.bmiHeader.biHeight = -size;
    info.bmiHeader.biPlanes = 1;
    info.bmiHeader.biBitCount = 32;
    info.bmiHeader.biCompression = BI_RGB;
    void* bits = nullptr;
    HBITMAP bitmap = CreateDIBSection(nullptr, &info, DIB_RGB_COLORS, &bits, nullptr, 0);
    if (!bitmap) return nullptr;
    memset(bits, 0, static_cast<size_t>(size) * size * 4);

    ID2D1Factory* factory = nullptr;
    D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, &factory);
    HDC dc = CreateCompatibleDC(nullptr);
    if (factory && dc) {
        HGDIOBJ old = SelectObject(dc, bitmap);
        ID2D1DCRenderTarget* target = nullptr;
        D2D1_RENDER_TARGET_PROPERTIES properties = D2D1::RenderTargetProperties(
            D2D1_RENDER_TARGET_TYPE_SOFTWARE,
            D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED), 96, 96);
        if (SUCCEEDED(factory->CreateDCRenderTarget(&properties, &target))) {
            RECT rect = {0, 0, size, size};
            target->BindDC(dc, &rect);
            target->BeginDraw();
            target->Clear(D2D1::ColorF(0, 0, 0, 0));
            DrawVisionAuthLogo(target, 0, 0, static_cast<float>(size));
            target->EndDraw();
            target->Release();
        }
        SelectObject(dc, old);
    }
    if (dc) DeleteDC(dc);
    SafeRelease(factory);
    return bitmap;
}

// ---------------------------------------------------------------------------

double IslandNow() {
    static LARGE_INTEGER frequency = {};
    if (frequency.QuadPart == 0) QueryPerformanceFrequency(&frequency);
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    return static_cast<double>(counter.QuadPart) / static_cast<double>(frequency.QuadPart);
}

namespace {
const wchar_t kIslandClass[] = L"VisionAuthIsland";
}

bool IslandWindow::Create(HWND owner, HINSTANCE module) {
    if (window_) return true;
    module_ = module;
    InitializeCriticalSection(&lock_);
    lockReady_ = true;

    HMONITOR monitor = owner ? MonitorFromWindow(owner, MONITOR_DEFAULTTOPRIMARY)
                             : MonitorFromPoint(POINT{0, 0}, MONITOR_DEFAULTTOPRIMARY);
    MONITORINFO info = {};
    info.cbSize = sizeof(info);
    GetMonitorInfoW(monitor, &info);
    UINT dpi = owner ? GetDpiForWindow(owner) : GetDpiForSystem();
    scale_ = dpi ? dpi / 96.0f : 1.0f;

    width_ = static_cast<int>(960 * scale_);
    height_ = static_cast<int>(220 * scale_);
    const RECT& screen = info.rcMonitor;
    POINT position = {screen.left + ((screen.right - screen.left) - width_) / 2,
                      screen.top + static_cast<int>((screen.bottom - screen.top) * 0.05)};

    WNDCLASSEXW windowClass = {};
    windowClass.cbSize = sizeof(windowClass);
    windowClass.lpfnWndProc = &WindowProc;
    windowClass.hInstance = module_;
    windowClass.lpszClassName = kIslandClass;
    RegisterClassExW(&windowClass);

    window_ = CreateWindowExW(WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
                              kIslandClass, L"VisionAuth", WS_POPUP, position.x, position.y, width_, height_, owner,
                              nullptr, module_, nullptr);
    if (!window_) {
        Destroy();
        return false;
    }

    BITMAPINFO bitmapInfo = {};
    bitmapInfo.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bitmapInfo.bmiHeader.biWidth = width_;
    bitmapInfo.bmiHeader.biHeight = -height_;
    bitmapInfo.bmiHeader.biPlanes = 1;
    bitmapInfo.bmiHeader.biBitCount = 32;
    bitmapInfo.bmiHeader.biCompression = BI_RGB;
    memoryDc_ = CreateCompatibleDC(nullptr);
    surface_ = CreateDIBSection(nullptr, &bitmapInfo, DIB_RGB_COLORS, &bits_, nullptr, 0);
    if (!memoryDc_ || !surface_ || !bits_) {
        Destroy();
        return false;
    }
    previousBitmap_ = SelectObject(memoryDc_, surface_);
    memset(bits_, 0, static_cast<size_t>(width_) * height_ * 4);

    // Place it with an empty frame; the render thread only updates the pixels
    SIZE size = {width_, height_};
    POINT source = {0, 0};
    BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
    UpdateLayeredWindow(window_, nullptr, &position, &size, memoryDc_, &source, 0, &blend, ULW_ALPHA);
    ShowWindow(window_, SW_SHOWNOACTIVATE);

    renderer_ = new IslandRenderer();
    stop_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    wake_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    thread_ = CreateThread(nullptr, 0, &RenderThread, this, 0, nullptr);
    if (!thread_) {
        Destroy();
        return false;
    }
    return true;
}

void IslandWindow::Wake() {
    if (wake_) SetEvent(wake_);
}

void IslandWindow::SetPhase(LONG phase) {
    if (!renderer_) return;
    EnterCriticalSection(&lock_);
    renderer_->SetPhase(phase);
    LeaveCriticalSection(&lock_);
    // Stay above LogonUI's own windows (done here, on the window's thread)
    SetWindowPos(window_, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    Wake();
}

void IslandWindow::SetVisible(bool visible) {
    if (!renderer_) return;
    EnterCriticalSection(&lock_);
    renderer_->SetVisible(visible);
    LeaveCriticalSection(&lock_);
    Wake();
}

void IslandWindow::SetName(const wchar_t* name) {
    if (!renderer_) return;
    EnterCriticalSection(&lock_);
    renderer_->SetName(name);
    LeaveCriticalSection(&lock_);
}

DWORD WINAPI IslandWindow::RenderThread(LPVOID parameter) {
    static_cast<IslandWindow*>(parameter)->RenderLoop();
    return 0;
}

void IslandWindow::RenderLoop() {
    ID2D1Factory* factory = nullptr;
    if (FAILED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, &factory))) return;
    ID2D1DCRenderTarget* target = nullptr;
    RECT rect = {0, 0, width_, height_};
    SIZE size = {width_, height_};
    POINT source = {0, 0};
    BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
    double last = IslandNow();

    while (WaitForSingleObject(stop_, 0) == WAIT_TIMEOUT) {
        if (!target) {
            D2D1_RENDER_TARGET_PROPERTIES properties = D2D1::RenderTargetProperties(
                D2D1_RENDER_TARGET_TYPE_DEFAULT,
                D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED), 96, 96);
            if (FAILED(factory->CreateDCRenderTarget(&properties, &target))) break;
        }
        double now = IslandNow();
        double dt = now - last;
        if (dt > 0.05) dt = 0.05;
        last = now;

        EnterCriticalSection(&lock_);
        renderer_->Advance(dt);
        bool settled = renderer_->Settled();
        target->BindDC(memoryDc_, &rect);
        target->BeginDraw();
        target->Clear(D2D1::ColorF(0, 0, 0, 0));
        renderer_->Draw(target, static_cast<float>(width_), static_cast<float>(height_), scale_);
        HRESULT hr = target->EndDraw();
        LeaveCriticalSection(&lock_);
        if (hr == static_cast<HRESULT>(D2DERR_RECREATE_TARGET)) SafeRelease(target);

        // Same position and size: only the pixels change, no messages to the owner thread
        UpdateLayeredWindow(window_, nullptr, nullptr, &size, memoryDc_, &source, 0, &blend, ULW_ALPHA);

        if (settled) {
            HANDLE events[2] = {stop_, wake_};
            if (WaitForMultipleObjects(2, events, FALSE, INFINITE) == WAIT_OBJECT_0) break;
            last = IslandNow();
            continue;
        }
        // Next frame in step with the display
        if (FAILED(DwmFlush())) Sleep(8);
    }
    SafeRelease(target);
    factory->Release();
}

LRESULT CALLBACK IslandWindow::WindowProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_MOUSEACTIVATE) return MA_NOACTIVATE;
    return DefWindowProcW(window, message, wparam, lparam);
}

void IslandWindow::Destroy() {
    if (thread_) {
        SetEvent(stop_);
        // Pump messages the render thread might send to this thread while it finishes
        while (MsgWaitForMultipleObjects(1, &thread_, FALSE, 3000, QS_SENDMESSAGE) == WAIT_OBJECT_0 + 1) {
            MSG message;
            PeekMessageW(&message, nullptr, 0, 0, PM_NOREMOVE);
        }
        CloseHandle(thread_);
        thread_ = nullptr;
    }
    if (stop_) {
        CloseHandle(stop_);
        stop_ = nullptr;
    }
    if (wake_) {
        CloseHandle(wake_);
        wake_ = nullptr;
    }
    if (window_) {
        DestroyWindow(window_);
        window_ = nullptr;
        UnregisterClassW(kIslandClass, module_);
    }
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
    if (lockReady_) {
        DeleteCriticalSection(&lock_);
        lockReady_ = false;
    }
}
