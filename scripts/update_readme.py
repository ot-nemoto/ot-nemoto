import base64
import json
import os
import re
import requests
import tomllib
from urllib.parse import quote
from datetime import datetime, timezone, timedelta

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
USERNAME = "ot-nemoto"
README_PATH = "README.md"
TOP_LANGS = 8
TOP_FRAMEWORKS = 8
OTHER_COLOR = "9E9E9E"
# ブランドカラーが他と重複した場合に使う代替色
FALLBACK_COLORS = ["6E7781", "B08800", "8250DF", "BF3989", "0969DA", "1A7F37", "CF222E", "953800"]

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

LANGUAGE_BADGE_MAP = {
    "TypeScript": ("TypeScript", "3178C6", "typescript",   "white"),
    "Python":     ("Python",     "3776AB", "python",       "white"),
    "JavaScript": ("JavaScript", "F7DF1E", "javascript",   "black"),
    "HTML":       ("HTML",       "E34F26", "html5",        "white"),
    "CSS":        ("CSS",        "1572B6", "css3",         "white"),
    "Go":         ("Go",         "00ADD8", "go",           "white"),
    "Rust":       ("Rust",       "000000", "rust",         "white"),
    "Java":       ("Java",       "007396", "openjdk",      "white"),
    "Shell":      ("Shell",      "4EAA25", "gnubash",      "white"),
    "Dockerfile": ("Docker",     "2496ED", "docker",       "white"),
}

# GitHub の言語集計に含まれるが、言語ではなくフレームワークとして扱うもの
NON_LANGUAGES = {"Vue", "Svelte", "Astro"}

FRAMEWORK_BADGE_MAP = {
    "Next.js":      ("Next.js",      "000000", "nextdotjs",   "white"),
    "Nuxt":         ("Nuxt",         "00DC82", "nuxt",        "white"),
    "Angular":      ("Angular",      "DD0031", "angular",     "white"),
    "Svelte":       ("Svelte",       "FF3E00", "svelte",      "white"),
    "Astro":        ("Astro",        "BC52EE", "astro",       "white"),
    "Express":      ("Express",      "000000", "express",     "white"),
    "NestJS":       ("NestJS",       "E0234E", "nestjs",      "white"),
    "Hono":         ("Hono",         "E36002", "hono",        "white"),
    "Electron":     ("Electron",     "47848F", "electron",    "white"),
    "Django":       ("Django",       "092E20", "django",      "white"),
    "Flask":        ("Flask",        "000000", "flask",       "white"),
    "FastAPI":      ("FastAPI",      "009688", "fastapi",     "white"),
    "Streamlit":    ("Streamlit",    "FF4B4B", "streamlit",   "white"),
    "Spring Boot":  ("Spring Boot",  "6DB33F", "springboot",  "white"),
    "Rails":        ("Rails",        "D30001", "rubyonrails", "white"),
    "Laravel":      ("Laravel",      "FF2D20", "laravel",     "white"),
    "Gin":          ("Gin",          "00ADD8", "go",          "white"),
}

# package.json の依存名 -> フレームワーク名
NPM_FRAMEWORKS = {
    "next": "Next.js",
    "nuxt": "Nuxt",
    "@angular/core": "Angular",
    "svelte": "Svelte",
    "astro": "Astro",
    "express": "Express",
    "@nestjs/core": "NestJS",
    "hono": "Hono",
    "electron": "Electron",
}
# Python のパッケージ名（正規化済み） -> フレームワーク名
PYTHON_FRAMEWORKS = {
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "streamlit": "Streamlit",
}
COMPOSER_FRAMEWORKS = {"laravel/framework": "Laravel"}
SPRING_BOOT_PATTERN = r"spring-boot-starter|org\.springframework\.boot"
# 行単位で判定するマニフェスト: ファイル名 -> [(正規表現, フレームワーク名)]
LINE_MANIFEST_FRAMEWORKS = {
    "pom.xml":          [(SPRING_BOOT_PATTERN, "Spring Boot")],
    "build.gradle":     [(SPRING_BOOT_PATTERN, "Spring Boot")],
    "build.gradle.kts": [(SPRING_BOOT_PATTERN, "Spring Boot")],
    "Gemfile":          [(r"^\s*gem\s+[\"']rails[\"']", "Rails")],
    "go.mod":           [(r"^\s*(require\s+)?github\.com/gin-gonic/gin\s", "Gin")],
}
MANIFEST_NAMES = (
    {"package.json", "requirements.txt", "Pipfile", "pyproject.toml", "composer.json"}
    | set(LINE_MANIFEST_FRAMEWORKS)
)
# 依存パッケージやサンプル・テスト用のディレクトリは集計しない
IGNORED_DIRS = {
    "node_modules", "vendor", ".venv", "venv", "dist", "build",
    "example", "examples", "test", "tests", "__tests__", "fixtures", "templates", "docs",
}


def api_get(url, params=None, allowed_statuses=()):
    """GitHub API を呼ぶ。allowed_statuses のときは None、それ以外のエラーは例外にする。

    レート制限などで途中のデータが欠けたまま README を更新しないよう、想定外のエラーでは処理を止める。
    """
    r = requests.get(url, headers=HEADERS, params=params)
    if r.status_code in allowed_statuses:
        return None
    r.raise_for_status()
    return r.json()


def get_all_repos():
    repos, page = [], 1
    while True:
        data = api_get(
            f"https://api.github.com/users/{USERNAME}/repos",
            params={"per_page": 100, "page": page, "type": "owner"},
        )
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return repos


def get_languages(repo_name):
    return api_get(
        f"https://api.github.com/repos/{USERNAME}/{quote(repo_name)}/languages",
        allowed_statuses=(404,),
    ) or {}


def get_manifests(repo):
    """リポジトリ内のマニフェストファイルを [(ファイル名, blob の SHA)] で返す"""
    branch = repo.get("default_branch")
    if not branch:
        return []
    # 空のリポジトリは 409 になる
    data = api_get(
        f"https://api.github.com/repos/{USERNAME}/{quote(repo['name'])}/git/trees/{quote(branch, safe='')}",
        params={"recursive": "1"},
        allowed_statuses=(404, 409),
    )
    if not data:
        return []
    if data.get("truncated"):
        print(f"warning: tree of {repo['name']} is truncated; some manifests may be missed")
    manifests = []
    for item in data.get("tree", []):
        if item.get("type") != "blob":
            continue
        parts = item["path"].split("/")
        if parts[-1] in MANIFEST_NAMES and not IGNORED_DIRS & set(parts[:-1]):
            manifests.append((parts[-1], item["sha"]))
    return manifests


def get_blob_text(repo_name, sha):
    data = api_get(f"https://api.github.com/repos/{USERNAME}/{quote(repo_name)}/git/blobs/{sha}")
    if data.get("encoding") != "base64":
        return ""
    return base64.b64decode(data["content"]).decode("utf-8-sig", errors="ignore")


def normalize_python_name(requirement):
    """'Flask[async]>=3.0' のような依存指定からパッケージ名を取り出す"""
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return re.sub(r"[-_.]+", "-", m.group(1)).lower() if m else ""


def get_pyproject_dependencies(data):
    names = []
    project = data.get("project", {})
    names += project.get("dependencies", [])
    for group in project.get("optional-dependencies", {}).values():
        names += group
    for group in data.get("dependency-groups", {}).values():
        names += [d for d in group if isinstance(d, str)]
    poetry = data.get("tool", {}).get("poetry", {})
    names += list(poetry.get("dependencies", {}))
    names += list(poetry.get("dev-dependencies", {}))
    for group in poetry.get("group", {}).values():
        names += list(group.get("dependencies", {}))
    return {normalize_python_name(n) for n in names if isinstance(n, str)}


def get_python_dependencies(filename, text):
    if filename == "pyproject.toml":
        try:
            return get_pyproject_dependencies(tomllib.loads(text))
        except (tomllib.TOMLDecodeError, AttributeError, TypeError):
            return set()
    if filename == "Pipfile":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return set()
        names = list(data.get("packages", {})) + list(data.get("dev-packages", {}))
        return {normalize_python_name(n) for n in names}
    # requirements.txt: コメントとオプション行（-r, -e など）を除いた各行の先頭がパッケージ名
    names = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.add(normalize_python_name(line))
    return names


def load_json_object(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def get_json_dependencies(data, keys):
    deps = set()
    for key in keys:
        if isinstance(data.get(key), dict):
            deps |= set(data[key])
    return deps


def detect_frameworks_in_manifest(filename, text):
    if filename == "package.json":
        deps = get_json_dependencies(
            load_json_object(text), ("dependencies", "devDependencies", "peerDependencies")
        )
        return {fw for dep, fw in NPM_FRAMEWORKS.items() if dep in deps}

    if filename == "composer.json":
        deps = get_json_dependencies(load_json_object(text), ("require", "require-dev"))
        return {fw for dep, fw in COMPOSER_FRAMEWORKS.items() if dep in deps}

    if filename in ("requirements.txt", "Pipfile", "pyproject.toml"):
        deps = get_python_dependencies(filename, text)
        return {fw for dep, fw in PYTHON_FRAMEWORKS.items() if dep in deps}

    found = set()
    for line in text.splitlines():
        # コメント行と、go.mod の間接依存は除く
        stripped = line.strip()
        if stripped.startswith(("#", "//", "<!--")) or stripped.endswith("// indirect"):
            continue
        for pattern, fw in LINE_MANIFEST_FRAMEWORKS.get(filename, []):
            if re.search(pattern, line):
                found.add(fw)
    return found


def get_frameworks(repo):
    found = set()
    for filename, sha in get_manifests(repo):
        found |= detect_frameworks_in_manifest(filename, get_blob_text(repo["name"], sha))
    return found


def get_pick_repos():
    return api_get(
        "https://api.github.com/search/repositories",
        params={"q": f"user:{USERNAME} topic:pick", "per_page": 100, "sort": "updated"},
    ).get("items", [])


def make_badge(name, badge_map):
    if name not in badge_map:
        return None
    label, color, logo, font_color = badge_map[name]
    return f"![{label}](https://img.shields.io/badge/{label.replace(' ', '_')}-{color}?style=flat-square&logo={logo}&logoColor={font_color})"


def make_pie_chart(title, items, badge_map):
    """items: [(name, value)] を値の降順で Mermaid の円グラフにする"""
    items = sorted(items, key=lambda x: x[1], reverse=True)
    colors, used = {}, set()
    fallbacks = iter(c for c in FALLBACK_COLORS if c != OTHER_COLOR)
    for i, (name, _) in enumerate(items, start=1):
        color = badge_map[name][1] if name in badge_map else OTHER_COLOR
        while color in used:
            color = next(fallbacks)
        used.add(color)
        colors[f"pie{i}"] = f"#{color}"
    init = json.dumps({"theme": "base", "themeVariables": colors})
    lines = [
        "```mermaid",
        f"%%{{init: {init}}}%%",
        f"pie showData title {title}",
    ]
    lines += [f'    "{name}" : {value}' for name, value in items]
    lines.append("```")
    return "\n".join(lines)


def top_with_other(counts, badge_map, limit):
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    top = [(n, v) for n, v in sorted_items if n in badge_map][:limit]
    other = sum(counts.values()) - sum(v for _, v in top)
    return top, other


def build_languages(repos):
    lang_bytes: dict[str, int] = {}
    for repo in repos:
        for lang, b in get_languages(repo["name"]).items():
            if lang in NON_LANGUAGES:
                continue
            lang_bytes[lang] = lang_bytes.get(lang, 0) + b

    total = sum(lang_bytes.values())
    if total == 0:
        return "_言語データがありません。_"

    top, other = top_with_other(lang_bytes, LANGUAGE_BADGE_MAP, TOP_LANGS)
    badges = " ".join(make_badge(l, LANGUAGE_BADGE_MAP) for l, _ in top)

    items = [(l, round(b / total * 100, 1)) for l, b in top]
    if round(other / total * 100, 1) > 0:
        items.append(("Other", round(other / total * 100, 1)))
    chart = make_pie_chart("Languages (%)", items, LANGUAGE_BADGE_MAP)
    return f"{badges}\n\n{chart}"


def build_frameworks(repos):
    fw_repos: dict[str, int] = {}
    # フォークは他人のコードなのでフレームワークの集計から除く
    for repo in repos:
        if repo.get("fork"):
            continue
        for fw in get_frameworks(repo):
            fw_repos[fw] = fw_repos.get(fw, 0) + 1

    if not fw_repos:
        return "_フレームワークは検出されませんでした。_"

    top, _ = top_with_other(fw_repos, FRAMEWORK_BADGE_MAP, TOP_FRAMEWORKS)
    badges = " ".join(make_badge(f, FRAMEWORK_BADGE_MAP) for f, _ in top)
    chart = make_pie_chart("Frameworks (repositories)", top, FRAMEWORK_BADGE_MAP)
    return f"{badges}\n\n{chart}"


def build_tech_stack():
    repos = get_all_repos()
    return (
        "### Languages\n\n"
        f"{build_languages(repos)}\n\n"
        "### Frameworks\n\n"
        f"{build_frameworks(repos)}"
    )


def get_writing_repos():
    return api_get(
        "https://api.github.com/search/repositories",
        params={"q": f"user:{USERNAME} topic:writing", "per_page": 100, "sort": "updated"},
    ).get("items", [])


def build_projects():
    repos = get_pick_repos()
    if not repos:
        return "_`pick` トピックが付いたリポジトリはありません。_"

    rows = []
    for repo in repos:
        name = repo["name"]
        desc = repo.get("description") or ""
        url = repo["html_url"]
        homepage = repo.get("homepage") or ""
        web = f"[🌐]({homepage})" if homepage else ""
        rows.append(f"| [{name}]({url}) | {desc} | {web} |")

    return "| Project | Description | |\n|---|---|---|\n" + "\n".join(rows)


def build_writing():
    repos = get_writing_repos()
    if not repos:
        return "_`writing` トピックが付いたリポジトリはありません。_"

    rows = []
    for repo in repos:
        name = repo["name"]
        desc = repo.get("description") or ""
        url = repo["html_url"]
        rows.append(f"| [{name}]({url}) | {desc} |")

    return "| Project | Description |\n|---|---|\n" + "\n".join(rows)


def update_section(content, marker, new_content):
    pattern = rf"(<!-- {marker}_START -->).*?(<!-- {marker}_END -->)"
    replacement = rf"\1\n{new_content}\n\2"
    return re.sub(pattern, replacement, content, flags=re.DOTALL)


def build_last_updated():
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")
    return f"_Last updated: {now}_"


def main():
    with open(README_PATH, encoding="utf-8") as f:
        content = f.read()

    content = update_section(content, "TECH_STACK", build_tech_stack())
    content = update_section(content, "PROJECTS", build_projects())
    content = update_section(content, "WRITING", build_writing())
    content = update_section(content, "LAST_UPDATED", build_last_updated())

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("README updated.")


if __name__ == "__main__":
    main()
