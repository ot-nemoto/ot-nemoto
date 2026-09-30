"""README の Projects 用に、リポジトリごとのカード SVG を生成する"""
import re
import unicodedata
from html import escape

# README の幅（約 845px）に最大 4 枚並ぶ幅。カードの間には改行ぶんの隙間（約 4.5px）が入るので、
# 4 枚で約 814px になり、少し狭い画面でも 4 枚並ぶ余裕を残す
WIDTH = 200
HEIGHT = 172
PADDING_X = 14
TITLE_FONT_SIZE = 12
DESC_FONT_SIZE = 11
DESC_LINE_HEIGHT = 15
META_FONT_SIZE = 11
DESC_MAX_WIDTH = WIDTH - PADDING_X * 2
DESC_MAX_LINES = 5
# 太字は同じサイズの通常の文字より少し幅が広い
BOLD_WIDTH_RATIO = 1.08
# 文字幅は概算なので、実際のフォント（macOS の SF Pro など）で広めに出ても収まるよう余裕を持たせる
WIDTH_SAFETY = 1.08
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

# XML に書けない制御文字
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 直前の文字とつなげて 1 文字として扱う文字（異体字セレクタ・ゼロ幅接合子）
_JOINERS = {"‍", "︎", "️"}


def clean(text):
    return _CONTROL_CHARS.sub("", text or "").strip()


def _graphemes(text):
    """見た目の 1 文字ごとに分ける（絵文字の ZWJ 連結や結合文字を途中で切らないため）"""
    clusters = []
    for ch in text:
        joins_previous = clusters and (
            ch in _JOINERS
            or unicodedata.combining(ch)
            or 0x1F3FB <= ord(ch) <= 0x1F3FF  # 肌の色
            or clusters[-1].endswith("‍")
        )
        if joins_previous:
            clusters[-1] += ch
        else:
            clusters.append(ch)
    return clusters


def _is_emoji(cluster):
    return any(ord(ch) >= 0x1F000 or unicodedata.category(ch) == "So" for ch in cluster)


def _is_wide(cluster):
    return unicodedata.east_asian_width(cluster[0]) in ("W", "F")


def _cluster_width(cluster):
    """12px のシステムフォントでのおおよその文字幅（SVG を <img> で表示すると実測できないため概算する）"""
    if _is_emoji(cluster):
        return 16.0
    ch = cluster[0]
    if _is_wide(cluster) or ch in "…—%":
        return 12.0
    if ch == " ":
        return 3.4
    if ch in "ilj.,:;'|!()[]":
        return 3.4
    if ch in "rtf-/":
        return 4.4
    if ch in "csz":
        return 6.0
    if ch in "MW@":
        return 11.2
    if ch in "mw&":
        return 9.6
    if ch.isupper():
        return 8.2
    if ch.isdigit():
        return 7.0
    return 6.6


def _text_width(text, font_size=DESC_FONT_SIZE):
    return sum(_cluster_width(c) for c in _graphemes(text)) * font_size / 12 * WIDTH_SAFETY


def truncate(text, max_width, font_size=DESC_FONT_SIZE):
    """1 行に収まらない分を「…」で省略する"""
    if _text_width(text, font_size) <= max_width:
        return text
    clusters = _graphemes(text)
    while clusters and _text_width("".join(clusters) + "…", font_size) > max_width:
        clusters.pop()
    return "".join(clusters).rstrip() + "…"


def wrap_text(text, max_width=DESC_MAX_WIDTH, max_lines=DESC_MAX_LINES):
    """単語単位で折り返す（日本語などの全角文字や絵文字は文字単位）。収まらない分は最後の行を「…」で省略する"""
    tokens, buf = [], ""
    for cluster in _graphemes(text):
        if cluster == " " or _is_wide(cluster) or _is_emoji(cluster):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(cluster)
        else:
            buf += cluster
    if buf:
        tokens.append(buf)

    lines, line = [], ""
    # 1 行に収まらないほど長い単語（URL など）は省略して載せる
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
    name, description, language = clean(name), clean(description), clean(language)
    title = truncate(name, DESC_MAX_WIDTH, TITLE_FONT_SIZE * BOLD_WIDTH_RATIO)
    lines = wrap_text(description or "No description")
    desc = "".join(
        f'<text class="d" x="{PADDING_X}" y="{54 + i * DESC_LINE_HEIGHT}">{escape(line)}</text>'
        for i, line in enumerate(lines)
    )

    # 下部のメタ情報（言語・スター数・デモの有無）を左から並べる。入りきらない項目は出さない。
    # 「Demo」はデモページがあることを示すだけ（画像の中にはリンクを置けないので、デモへはリポジトリから移動する）
    meta, x, y = [], PADDING_X, HEIGHT - 16
    right = WIDTH - PADDING_X
    if language:
        color = LANGUAGE_COLORS.get(language, DEFAULT_LANGUAGE_COLOR)
        label = truncate(language, right - x - 13, META_FONT_SIZE)
        meta.append(f'<circle cx="{x + 4}" cy="{y - 4}" r="4" fill="{color}"/>')
        meta.append(f'<text class="m" x="{x + 13}" y="{y}">{escape(label)}</text>')
        x += 13 + _text_width(label, META_FONT_SIZE) + 12
    for text in ([f"★ {stars}"] if stars else []) + (["Demo"] if has_demo else []):
        w = _text_width(text, META_FONT_SIZE)
        if x + w > right:
            break
        meta.append(f'<text class="m" x="{x:.1f}" y="{y}">{text}</text>')
        x += w + 12

    summary = f"{name}: {description}" if description else name
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img">
<title>{escape(summary)}</title>
<style>
text{{font-family:{FONT}}}
.n{{font-size:{TITLE_FONT_SIZE}px;font-weight:600;fill:{c["title"]}}}
.d{{font-size:{DESC_FONT_SIZE}px;fill:{c["ink2"]}}}
.m{{font-size:{META_FONT_SIZE}px;fill:{c["muted"]}}}
</style>
<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="8" fill="{c["bg"]}" stroke="{c["border"]}"/>
<text class="n" x="{PADDING_X}" y="30">{escape(title)}</text>
{desc}
{"".join(meta)}
</svg>
"""
