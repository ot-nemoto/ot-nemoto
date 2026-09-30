import base64
import html
import json
import os
import re
import requests
import tomllib
from urllib.parse import quote
from datetime import datetime, timezone, timedelta

import project_card_svg
import tech_stack_svg

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
USERNAME = "ot-nemoto"
README_PATH = "README.md"
ASSETS_DIR = "assets"
TOP_LANGS = tech_stack_svg.MAX_SERIES
TOP_FRAMEWORKS = 8
# これ未満の割合の言語は「Other」にまとめる（積み上げバーで見えないため）
MIN_SHARE_PCT = 1.0

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# GitHub の言語集計に含まれるが、言語ではなくフレームワークとして扱うもの
NON_LANGUAGES = {"Vue", "Svelte", "Astro"}

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
    data = api_get(
        "https://api.github.com/search/repositories",
        params={"q": f"user:{USERNAME} topic:pick", "per_page": 100},
    )
    # 検索がタイムアウトして結果が欠けていると、カードを誤って消してしまうので止める
    if data.get("incomplete_results"):
        raise RuntimeError("GitHub search returned incomplete results")
    # 更新順だと push のたびに並びが変わるので、名前順に固定する
    return sorted(data.get("items", []), key=lambda r: r["name"].lower())


def top_n(counts, limit):
    # 同じ値のときは名前順にして、実行ごとに並びが変わらないようにする
    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:limit]


def collect_languages(repos):
    """[(言語名, 割合%)] を返す。上位以外と小さすぎる言語は最後の「Other」にまとめる"""
    lang_bytes: dict[str, int] = {}
    for repo in repos:
        for lang, b in get_languages(repo["name"]).items():
            if lang in NON_LANGUAGES:
                continue
            lang_bytes[lang] = lang_bytes.get(lang, 0) + b

    total = sum(lang_bytes.values())
    if total == 0:
        return []

    top = [(l, b) for l, b in top_n(lang_bytes, TOP_LANGS) if b / total * 100 >= MIN_SHARE_PCT]
    other = total - sum(b for _, b in top)
    items = [(l, round(b / total * 100, 1)) for l, b in top]
    # 丸めて 0.0% になるほど小さい「Other」は出さない
    if round(other / total * 100, 1) > 0:
        items.append(("Other", round(other / total * 100, 1)))
    return items


def collect_frameworks(repos):
    """[(フレームワーク名, 使っているリポジトリ数)] を返す"""
    fw_repos: dict[str, int] = {}
    # フォークは他人のコードなのでフレームワークの集計から除く
    for repo in repos:
        if repo.get("fork"):
            continue
        for fw in get_frameworks(repo):
            fw_repos[fw] = fw_repos.get(fw, 0) + 1
    return top_n(fw_repos, TOP_FRAMEWORKS)


def build_tech_stack():
    repos = get_all_repos()
    languages = collect_languages(repos)
    frameworks = collect_frameworks(repos)

    os.makedirs(ASSETS_DIR, exist_ok=True)
    for theme in tech_stack_svg.THEMES:
        with open(f"{ASSETS_DIR}/tech-stack-{theme}.svg", "w", encoding="utf-8") as f:
            f.write(tech_stack_svg.render(theme, languages, frameworks))

    # 画像を読めない環境向けに、内容を代替テキストにも入れる
    alt = tech_stack_svg.describe(languages, frameworks)
    return (
        "<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="{ASSETS_DIR}/tech-stack-dark.svg">\n'
        f'  <img alt="{html.escape(alt)}" src="{ASSETS_DIR}/tech-stack-light.svg">\n'
        "</picture>"
    )


def build_projects():
    repos = get_pick_repos()
    cards_dir = f"{ASSETS_DIR}/projects"
    os.makedirs(cards_dir, exist_ok=True)

    written = set()
    cards = []
    cols = project_card_svg.GRID_COLUMNS
    for i, repo in enumerate(repos):
        name = repo["name"]
        desc = project_card_svg.clean(repo.get("description"))
        for theme in project_card_svg.THEMES:
            path = f"{cards_dir}/{name}-{theme}.svg"
            with open(path, "w", encoding="utf-8") as f:
                f.write(project_card_svg.render(
                    theme, name, desc,
                    language=repo.get("language"),
                    stars=repo.get("stargazers_count", 0),
                    has_web=bool((repo.get("homepage") or "").strip()),
                    # 白と色付きのカードを市松模様に並べる
                    tinted=(i // cols + i % cols) % 2 == 1,
                ))
            written.add(os.path.basename(path))
        alt = html.escape(f"{name}: {desc}" if desc else name)
        # カード全体をリポジトリへのリンクにする。最大 4 枚ずつ横に並び、狭い画面では折り返す
        cards.append(
            f'<a href="{html.escape(repo["html_url"])}"><picture>'
            f'<source media="(prefers-color-scheme: dark)" srcset="{cards_dir}/{name}-dark.svg">'
            f'<img alt="{alt}" src="{cards_dir}/{name}-light.svg" width="{project_card_svg.WIDTH}">'
            "</picture></a>"
        )

    # `pick` トピックから外れたリポジトリのカードを消す（このスクリプトが作るカード以外には触らない）
    for filename in os.listdir(cards_dir):
        path = f"{cards_dir}/{filename}"
        is_card = filename.endswith(("-light.svg", "-dark.svg")) and os.path.isfile(path)
        if is_card and filename not in written:
            os.remove(path)

    if not cards:
        return "_`pick` トピックが付いたリポジトリはありません。_"
    # Web ページへはリポジトリのページ（About の homepage）から移動してもらう
    return "<p>\n" + "\n".join(cards) + "\n</p>"


def update_section(content, marker, new_content):
    pattern = rf"(<!-- {marker}_START -->).*?(<!-- {marker}_END -->)"
    # new_content を置換テンプレートとして解釈させない（説明文にバックスラッシュが含まれても壊れないように）
    return re.sub(
        pattern,
        lambda m: f"{m.group(1)}\n{new_content}\n{m.group(2)}",
        content,
        flags=re.DOTALL,
    )


def build_last_updated():
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")
    return f"_Last updated: {now}_"


def main():
    with open(README_PATH, encoding="utf-8") as f:
        content = f.read()

    content = update_section(content, "TECH_STACK", build_tech_stack())
    content = update_section(content, "PROJECTS", build_projects())
    content = update_section(content, "LAST_UPDATED", build_last_updated())

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print("README updated.")


if __name__ == "__main__":
    main()
