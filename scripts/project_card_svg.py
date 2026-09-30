"""README の Projects 用に、リポジトリごとのカード SVG を生成する"""
import unicodedata
from html import escape

WIDTH = 400
HEIGHT = 150
PADDING_X = 20
DESC_FONT_SIZE = 12
DESC_MAX_WIDTH = WIDTH - PADDING_X * 2
DESC_MAX_LINES = 3
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"

THEMES = {
    "light": {
        "bg": "#ffffff", "border": "#d1d9e0", "title": "#0969da", "ink2": "#59636e", "muted": "#818b98",
    },
    "dark": {
        "bg": "#0d1117", "border": "#3d444d", "title": "#4493f8", "ink2": "#9198a1", "muted": "#8b949e",
    },
}

# GitHub（linguist）の言語色。カード下部の言語名の横に付ける点に使う
LANGUAGE_COLORS = {
    "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572a5", "HTML": "#e34c26",
    "CSS": "#663399", "Shell": "#89e051", "Ruby": "#701516", "PHP": "#4f5d95", "Go": "#00add8",
    "Java": "#b07219", "Vue": "#41b883", "Rust": "#dea584", "Dockerfile": "#384d54", "HCL": "#844fba",
}
DEFAULT_LANGUAGE_COLOR = "#8c959f"


def _char_width(ch):
    """12px のシステムフォントでのおおよその文字幅（SVG を <img> で表示すると実測できないため概算する）"""
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 12.0
    if ch == " ":
        return 3.4
    if ch in "ilj.,:;'|!()[]":
        return 3.4
    if ch in "MW@":
        return 11.2
    if ch in "mw":
        return 9.6
    if ch.isupper():
        return 8.2
    if ch.isdigit():
        return 7.0
    return 6.3


def _text_width(text):
    return sum(_char_width(ch) for ch in text) * DESC_FONT_SIZE / 12


def truncate(text, max_width):
    """1 行に収まらない分を「…」で省略する"""
    if _text_width(text) <= max_width:
        return text
    while text and _text_width(text + "…") > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap_text(text, max_width=DESC_MAX_WIDTH, max_lines=DESC_MAX_LINES):
    """単語単位で折り返す（日本語などの全角文字は文字単位）。収まらない分は最後の行を「…」で省略する"""
    tokens, buf = [], ""
    for ch in text:
        if ch == " " or unicodedata.east_asian_width(ch) in ("W", "F"):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)

    lines, line = [], ""
    # 1 行に収まらないほど長い単語（URL など）は、その行の残りに入る分だけ省略して載せる
    tokens = [truncate(t, max_width) for t in tokens]
    for token in tokens:
        if _text_width(line + token) <= max_width:
            line += token
            continue
        if line.strip():
            lines.append(line.rstrip())
        line = "" if token == " " else token
    if line.strip():
        lines.append(line.rstrip())

    if len(lines) <= max_lines:
        return lines
    last = lines[max_lines - 1]
    if not last.endswith("…"):
        last = truncate(last + " …", max_width).removesuffix(" …").rstrip()
        last = last if last.endswith("…") else last + "…"
    return lines[: max_lines - 1] + [last]


def render(theme, name, description, language=None, stars=0, has_demo=False):
    c = THEMES[theme]
    # リポジトリ名は 15px の太字なので、12px 換算の幅を狭めて 1 行に収める
    title = truncate(name, DESC_MAX_WIDTH * 12 / 16)
    lines = wrap_text(description or "No description")
    desc = "".join(
        f'<text class="d" x="{PADDING_X}" y="{64 + i * 18}">{escape(line)}</text>' for i, line in enumerate(lines)
    )

    # 下部のメタ情報（言語・スター数・デモの有無）を左から並べる
    meta, x, y = [], PADDING_X, HEIGHT - 20
    if language:
        color = LANGUAGE_COLORS.get(language, DEFAULT_LANGUAGE_COLOR)
        meta.append(f'<circle cx="{x + 5}" cy="{y - 4}" r="5" fill="{color}"/>')
        meta.append(f'<text class="m" x="{x + 15}" y="{y}">{escape(language)}</text>')
        x += 15 + _text_width(language) + 18
    if stars:
        meta.append(f'<text class="m" x="{x}" y="{y}">★ {stars}</text>')
        x += _text_width(f"* {stars}") + 22
    if has_demo:
        meta.append(f'<text class="m" x="{x}" y="{y}">Live demo ↗</text>')

    summary = f"{name}: {description}" if description else name
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img">
<title>{escape(summary)}</title>
<style>
text{{font-family:{FONT}}}
.n{{font-size:15px;font-weight:600;fill:{c["title"]}}}
.d{{font-size:{DESC_FONT_SIZE}px;fill:{c["ink2"]}}}
.m{{font-size:12px;fill:{c["muted"]}}}
</style>
<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="10" fill="{c["bg"]}" stroke="{c["border"]}"/>
<text class="n" x="{PADDING_X}" y="36">{escape(title)}</text>
{desc}
{"".join(meta)}
</svg>
"""
