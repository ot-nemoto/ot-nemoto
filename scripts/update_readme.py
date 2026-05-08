import os
import re
import requests
from datetime import datetime, timezone, timedelta

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
USERNAME = "ot-nemoto"
README_PATH = "README.md"
TOP_LANGS = 8

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

BADGE_MAP = {
    "TypeScript": ("TypeScript", "3178C6", "typescript",   "white"),
    "Python":     ("Python",     "3776AB", "python",       "white"),
    "JavaScript": ("JavaScript", "F7DF1E", "javascript",   "black"),
    "HTML":       ("HTML",       "E34F26", "html5",        "white"),
    "CSS":        ("CSS",        "1572B6", "css3",         "white"),
    "Go":         ("Go",         "00ADD8", "go",           "white"),
    "Rust":       ("Rust",       "000000", "rust",         "white"),
    "Java":       ("Java",       "007396", "openjdk",      "white"),
    "Shell":      ("Shell",      "4EAA25", "gnubash",      "white"),
    "Vue":        ("Vue.js",     "4FC08D", "vuedotjs",     "white"),
    "Dockerfile": ("Docker",     "2496ED", "docker",       "white"),
}


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


def get_pick_repos():
    r = requests.get(
        "https://api.github.com/search/repositories",
        headers=HEADERS,
        params={"q": f"user:{USERNAME} topic:pick", "per_page": 100, "sort": "updated"},
    )
    return r.json().get("items", [])


def make_badge(lang):
    if lang not in BADGE_MAP:
        return None
    label, color, logo, font_color = BADGE_MAP[lang]
    return f"![{label}](https://img.shields.io/badge/{label}-{color}?style=flat-square&logo={logo}&logoColor={font_color})"


def make_progress_bar(pct, width=10):
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def build_tech_stack():
    repos = get_all_repos()
    lang_bytes: dict[str, int] = {}
    for repo in repos:
        for lang, b in get_languages(repo["name"]).items():
            lang_bytes[lang] = lang_bytes.get(lang, 0) + b

    total = sum(lang_bytes.values())
    if total == 0:
        return ""

    sorted_langs = sorted(lang_bytes.items(), key=lambda x: x[1], reverse=True)
    top = [(l, b) for l, b in sorted_langs if make_badge(l)][:TOP_LANGS]

    badges = " ".join(make_badge(l) for l, _ in top)

    rows = []
    for lang, b in top:
        pct = b / total * 100
        rows.append(f"| {lang} | {make_progress_bar(pct)} | {pct:.1f}% |")

    table = "| Language | | Share |\n|---|---|---|\n" + "\n".join(rows)
    return f"{badges}\n\n{table}"


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
        lang = repo.get("language") or ""
        url = repo["html_url"]
        rows.append(f"| [{name}]({url}) | {desc} | {lang} |")

    return "| Project | Description | Tech |\n|---|---|---|\n" + "\n".join(rows)


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
