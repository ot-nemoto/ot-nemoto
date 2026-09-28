import base64
import json
import os
import re
import requests
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
    "React":        ("React",        "61DAFB", "react",       "black"),
    "Vue.js":       ("Vue.js",       "4FC08D", "vuedotjs",    "white"),
    "Nuxt":         ("Nuxt",         "00DC82", "nuxt",        "white"),
    "Angular":      ("Angular",      "DD0031", "angular",     "white"),
    "Svelte":       ("Svelte",       "FF3E00", "svelte",      "white"),
    "Astro":        ("Astro",        "BC52EE", "astro",       "white"),
    "Express":      ("Express",      "000000", "express",     "white"),
    "NestJS":       ("NestJS",       "E0234E", "nestjs",      "white"),
    "Hono":         ("Hono",         "E36002", "hono",        "white"),
    "Electron":     ("Electron",     "47848F", "electron",    "white"),
    "Tailwind CSS": ("Tailwind CSS", "06B6D4", "tailwindcss", "white"),
    "Bootstrap":    ("Bootstrap",    "7952B3", "bootstrap",   "white"),
    "Django":       ("Django",       "092E20", "django",      "white"),
    "Flask":        ("Flask",        "000000", "flask",       "white"),
    "FastAPI":      ("FastAPI",      "009688", "fastapi",     "white"),
    "Streamlit":    ("Streamlit",    "FF4B4B", "streamlit",   "white"),
    "Spring Boot":  ("Spring Boot",  "6DB33F", "springboot",  "white"),
    "Rails":        ("Rails",        "D30001", "rubyonrails", "white"),
    "Laravel":      ("Laravel",      "FF2D20", "laravel",     "white"),
    "Gin":          ("Gin",          "00ADD8", "go",          "white"),
}

# マニフェストファイル名 -> {依存パッケージ名: フレームワーク名}
NPM_FRAMEWORKS = {
    "next": "Next.js",
    "react": "React",
    "vue": "Vue.js",
    "nuxt": "Nuxt",
    "@angular/core": "Angular",
    "svelte": "Svelte",
    "astro": "Astro",
    "express": "Express",
    "@nestjs/core": "NestJS",
    "hono": "Hono",
    "electron": "Electron",
    "tailwindcss": "Tailwind CSS",
    "bootstrap": "Bootstrap",
}
PYTHON_FRAMEWORKS = {
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "streamlit": "Streamlit",
}
TEXT_MANIFEST_FRAMEWORKS = {
    "requirements.txt": PYTHON_FRAMEWORKS,
    "pyproject.toml":   PYTHON_FRAMEWORKS,
    "Pipfile":          PYTHON_FRAMEWORKS,
    "pom.xml":          {"spring-boot": "Spring Boot"},
    "build.gradle":     {"spring-boot": "Spring Boot"},
    "build.gradle.kts": {"spring-boot": "Spring Boot"},
    "Gemfile":          {"rails": "Rails"},
    "composer.json":    {"laravel/framework": "Laravel"},
    "go.mod":           {"github.com/gin-gonic/gin": "Gin"},
}
MANIFEST_NAMES = {"package.json"} | set(TEXT_MANIFEST_FRAMEWORKS)
IGNORED_DIRS = {"node_modules", "vendor", ".venv", "venv", "dist", "build"}


def get_all_repos():
    repos, page = [], 1
    while True:
        r = requests.get(
            f"https://api.github.com/users/{USERNAME}/repos",
            headers=HEADERS,
            params={"per_page": 100, "page": page, "type": "owner"},
        )
        data = r.json()
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return repos


def get_languages(repo_name):
    r = requests.get(
        f"https://api.github.com/repos/{USERNAME}/{repo_name}/languages",
        headers=HEADERS,
    )
    return r.json() if r.status_code == 200 else {}


def get_manifest_paths(repo):
    branch = repo.get("default_branch")
    if not branch:
        return []
    r = requests.get(
        f"https://api.github.com/repos/{USERNAME}/{repo['name']}/git/trees/{branch}",
        headers=HEADERS,
        params={"recursive": "1"},
    )
    if r.status_code != 200:
        return []
    paths = []
    for item in r.json().get("tree", []):
        if item.get("type") != "blob":
            continue
        parts = item["path"].split("/")
        if parts[-1] in MANIFEST_NAMES and not IGNORED_DIRS & set(parts[:-1]):
            paths.append(item["path"])
    return paths


def get_file_text(repo_name, path):
    r = requests.get(
        f"https://api.github.com/repos/{USERNAME}/{repo_name}/contents/{path}",
        headers=HEADERS,
    )
    if r.status_code != 200:
        return ""
    data = r.json()
    if data.get("encoding") != "base64":
        return ""
    return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")


def detect_frameworks_in_manifest(filename, text):
    found = set()
    if filename == "package.json":
        try:
            pkg = json.loads(text)
        except json.JSONDecodeError:
            return found
        deps = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            if isinstance(pkg.get(key), dict):
                deps.update(pkg[key])
        for dep, fw in NPM_FRAMEWORKS.items():
            if dep in deps:
                found.add(fw)
        return found

    lowered = text.lower()
    for dep, fw in TEXT_MANIFEST_FRAMEWORKS.get(filename, {}).items():
        if re.search(rf"(?<![\w.-]){re.escape(dep)}(?![\w-])", lowered):
            found.add(fw)
    return found


def get_frameworks(repo):
    found = set()
    for path in get_manifest_paths(repo):
        filename = path.rsplit("/", 1)[-1]
        found |= detect_frameworks_in_manifest(filename, get_file_text(repo["name"], path))
    return found


def get_pick_repos():
    r = requests.get(
        "https://api.github.com/search/repositories",
        headers=HEADERS,
        params={"q": f"user:{USERNAME} topic:pick", "per_page": 100, "sort": "updated"},
    )
    return r.json().get("items", [])


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
    for repo in repos:
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
    r = requests.get(
        "https://api.github.com/search/repositories",
        headers=HEADERS,
        params={"q": f"user:{USERNAME} topic:writing", "per_page": 100, "sort": "updated"},
    )
    return r.json().get("items", [])


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
