"""README の Tech Stack 用 SVG（言語の積み上げバー + フレームワークの横棒）を生成する"""
from html import escape

WIDTH = 460
CARD_GAP = 16
PADDING_X = 20
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"

# 色覚多様性を考慮して検証したカテゴリ色（この順で割り当てる）。ダークはダーク背景向けに明るさを調整した同じ色相
THEMES = {
    "light": {
        "bg": "#ffffff", "border": "#d1d9e0", "ink": "#1f2328", "ink2": "#59636e", "track": "#eff2f5",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"],
        "other": "#afb8c1",
    },
    "dark": {
        "bg": "#0d1117", "border": "#3d444d", "ink": "#f0f6fc", "ink2": "#9198a1", "track": "#151b23",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"],
        "other": "#59636e",
    },
}
MAX_SERIES = len(THEMES["light"]["series"])


def _style(c, animate):
    motion = "" if animate else ".grow,.fade{animation:none!important;opacity:1}"
    return f"""<style>
text{{font-family:{FONT}}}
.t{{font-size:14px;font-weight:600;fill:{c["ink"]}}}
.s{{font-size:11px;fill:{c["ink2"]}}}
.n{{font-size:12px;fill:{c["ink"]}}}
.v{{font-size:12px;fill:{c["ink2"]};font-variant-numeric:tabular-nums}}
.grow{{transform-box:fill-box;transform-origin:left;animation:grow .9s cubic-bezier(.2,.8,.2,1) both}}
.fade{{opacity:0;animation:fade .5s ease-out forwards}}
@keyframes grow{{from{{transform:scaleX(0)}}}}
@keyframes fade{{to{{opacity:1}}}}
@media (prefers-reduced-motion: reduce){{.grow,.fade{{animation:none;opacity:1}}}}
{motion}
</style>"""


def _card(c, y, height, title, subtitle):
    return (
        f'<rect x="0.5" y="{y + 0.5}" width="{WIDTH - 1}" height="{height - 1}" rx="10" '
        f'fill="{c["bg"]}" stroke="{c["border"]}"/>'
        f'<text class="t" x="{PADDING_X}" y="{y + 30}">{escape(title)}</text>'
        f'<text class="s" x="{PADDING_X}" y="{y + 47}">{escape(subtitle)}</text>'
    )


def _empty(y, message):
    return f'<text class="s" x="{PADDING_X}" y="{y + 80}">{escape(message)}</text>'


def _languages_card(c, theme, y, items):
    """items: [(name, percent)]。最後の要素が "Other" のときはグレーにする"""
    legend_rows = (len(items) + 1) // 2
    height = 106 + max(legend_rows, 1) * 24 if items else 110
    parts = [_card(c, y, height, "Languages", "Share of code across public repositories")]
    if not items:
        return parts + [_empty(y, "No language data")], height

    colors = [c["other"] if name == "Other" else c["series"][i] for i, (name, _) in enumerate(items)]
    bar_x, bar_y, bar_w, bar_h, gap = PADDING_X, y + 64, WIDTH - PADDING_X * 2, 12, 2
    total = sum(v for _, v in items)
    x, segments = bar_x, []
    for (_, value), color in zip(items, colors):
        w = bar_w * value / total
        segments.append(f'<rect x="{x:.2f}" y="{bar_y}" width="{max(w - gap, 1):.2f}" height="{bar_h}" fill="{color}"/>')
        x += w
    clip_id = f"lang-bar-{theme}"
    parts.append(
        f'<clipPath id="{clip_id}"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="6"/></clipPath>'
        f'<g clip-path="url(#{clip_id})" class="grow">{"".join(segments)}</g>'
    )

    col_w = bar_w // 2
    for i, ((name, value), color) in enumerate(zip(items, colors)):
        lx = bar_x + (i % 2) * (col_w + 10)
        ly = y + 110 + (i // 2) * 24
        parts.append(
            f'<g class="fade" style="animation-delay:{0.4 + i * 0.05:.2f}s">'
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>'
            f'<text class="n" x="{lx + 17}" y="{ly}">{escape(name)}</text>'
            f'<text class="v" x="{lx + col_w - 10}" y="{ly}" text-anchor="end">{value:.1f}%</text></g>'
        )
    return parts, height


def _frameworks_card(c, y, items):
    """items: [(name, repository count)]"""
    row_h, top = 26, 72
    height = top + len(items) * row_h + 8 if items else 110
    parts = [_card(c, y, height, "Frameworks", "Public repositories using each framework")]
    if not items:
        return parts + [_empty(y, "No frameworks detected")], height

    bar_x, bar_w, bar_h, r = 118, 280, 12, 4
    max_value = max(v for _, v in items)
    for i, (name, value) in enumerate(items):
        by = y + top + i * row_h
        w = max(bar_w * value / max_value, r * 2)
        # 値側の端だけ角丸にした横棒
        path = (
            f"M{bar_x},{by} h{w - r:.2f} a{r},{r} 0 0 1 {r},{r} v{bar_h - 2 * r} "
            f"a{r},{r} 0 0 1 -{r},{r} h-{w - r:.2f} z"
        )
        parts.append(
            f'<text class="n" x="{PADDING_X}" y="{by + 10}">{escape(name)}</text>'
            f'<rect x="{bar_x}" y="{by}" width="{bar_w}" height="{bar_h}" rx="{r}" fill="{c["track"]}"/>'
            f'<path d="{path}" fill="{c["series"][0]}" class="grow" style="animation-delay:{i * 0.06:.2f}s"/>'
            f'<text class="v" x="{bar_x + w + 8:.2f}" y="{by + 10}">{value}</text>'
        )
    return parts, height


def render(theme, languages, frameworks, animate=True):
    c = THEMES[theme]
    lang_parts, lang_h = _languages_card(c, theme, 0, languages)
    fw_y = lang_h + CARD_GAP
    fw_parts, fw_h = _frameworks_card(c, fw_y, frameworks)
    height = fw_y + fw_h
    body = "\n".join(lang_parts + fw_parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-label="Languages and frameworks">\n'
        f"{_style(c, animate)}\n{body}\n</svg>\n"
    )
