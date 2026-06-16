#!/usr/bin/env python3
"""Update JNU-SHARK organization profile README and contribution heatmap."""

from __future__ import annotations

import datetime as dt
import functools
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path


ORG = os.getenv("ORG_LOGIN", "JNU-SHARK")
TEAM_NAME = os.getenv("TEAM_NAME", "霞客湾 SHARK 机器人俱乐部")
ORG_DESCRIPTION = os.getenv("ORG_DESCRIPTION", "江南大学霞客湾机器人俱乐部")
MANUAL_MEMBER_COUNT = int(os.getenv("MEMBER_COUNT", "24"))
MANUAL_VISIBLE_PROJECT_COUNT = int(os.getenv("VISIBLE_PROJECT_COUNT", "43"))
MAX_COMMIT_PAGES_PER_REPO = int(os.getenv("MAX_COMMIT_PAGES_PER_REPO", "5"))
TIMEZONE = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "profile"
ASSETS_DIR = PROFILE_DIR / "assets"
README_PATH = PROFILE_DIR / "README.md"
HEATMAP_PATH = ASSETS_DIR / "commit-heatmap.svg"


def token() -> str | None:
    return os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")


@functools.lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext | None:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def request_json(url: str) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "JNU-SHARK-profile-updater",
    }
    if token():
        headers["Authorization"] = f"Bearer {token()}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 404, 409}:
            return []
        raise


def get_paginated(path: str, params: dict[str, str] | None = None, max_pages: int | None = None) -> list[dict]:
    params = dict(params or {})
    params["per_page"] = "100"
    items: list[dict] = []
    page = 1
    while True:
        params["page"] = str(page)
        query = urllib.parse.urlencode(params)
        data = request_json(f"https://api.github.com{path}?{query}")
        if not isinstance(data, list) or not data:
            break
        items.extend(data)
        if len(data) < 100:
            break
        page += 1
        if max_pages is not None and page > max_pages:
            break
    return items


def get_org() -> dict:
    data = request_json(f"https://api.github.com/orgs/{ORG}")
    return data if isinstance(data, dict) else {}


def get_repos() -> list[dict]:
    repos = get_paginated(f"/orgs/{ORG}/repos", {"type": "all", "sort": "pushed"})
    return sorted(repos, key=lambda r: r.get("pushed_at") or "", reverse=True)


def get_member_count() -> int:
    members = get_paginated(f"/orgs/{ORG}/members")
    return len(members) or MANUAL_MEMBER_COUNT


def collect_commits(repos: list[dict], since: dt.datetime) -> Counter[str]:
    counts: Counter[str] = Counter()
    since_iso = since.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    for repo in repos:
        if repo.get("archived"):
            continue
        pushed_at = repo.get("pushed_at")
        if pushed_at:
            try:
                pushed_date = dt.datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                if pushed_date < since.astimezone(dt.timezone.utc):
                    continue
            except ValueError:
                pass
        owner = repo.get("owner", {}).get("login", ORG)
        name = repo.get("name")
        if not name:
            continue
        commits = get_paginated(
            f"/repos/{owner}/{name}/commits",
            {"since": since_iso},
            max_pages=MAX_COMMIT_PAGES_PER_REPO,
        )
        for commit in commits:
            commit_data = commit.get("commit", {}) if isinstance(commit, dict) else {}
            author = commit_data.get("author", {})
            date_text = author.get("date")
            if not date_text:
                continue
            try:
                day = dt.datetime.fromisoformat(date_text.replace("Z", "+00:00")).astimezone(TIMEZONE).date()
            except ValueError:
                continue
            counts[day.isoformat()] += 1
    return counts


def contribution_color(count: int, max_count: int) -> str:
    if count <= 0:
        return "#ebedf0"
    if max_count <= 1:
        level = 1
    else:
        level = min(4, max(1, int((count / max_count) * 4 + 0.999)))
    return ["#9be9a8", "#40c463", "#30a14e", "#216e39"][level - 1]


def build_heatmap_svg(counts: Counter[str], today: dt.date) -> str:
    start = today - dt.timedelta(days=364)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)
    max_count = max(counts.values(), default=0)
    cell = 11
    gap = 3
    left = 34
    top = 22
    width = left + 53 * (cell + gap) + 16
    height = top + 7 * (cell + gap) + 28
    month_labels: list[str] = []
    last_month = None
    rects: list[str] = []
    days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    for week in range(53):
        for weekday in range(7):
            day = start + dt.timedelta(days=week * 7 + weekday)
            if day > today:
                continue
            count = counts.get(day.isoformat(), 0)
            x = left + week * (cell + gap)
            y = top + weekday * (cell + gap)
            rects.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
                f'fill="{contribution_color(count, max_count)}"><title>{day.isoformat()}: {count} commits</title></rect>'
            )
            if day.day <= 7 and day.month != last_month:
                last_month = day.month
                month_labels.append(f'<text x="{x}" y="13">{month_names[day.month - 1]}</text>')

    day_labels = "\n".join(
        f'<text x="0" y="{top + idx * (cell + gap) + 9}">{name}</text>'
        for idx, name in enumerate(days)
        if idx in {1, 3, 5}
    )
    total = sum(counts.values())
    legend_x = width - 160
    legend_y = height - 18
    legend = [
        f'<text x="{legend_x - 34}" y="{legend_y + 9}">Less</text>',
        f'<text x="{legend_x + 82}" y="{legend_y + 9}">More</text>',
    ]
    for idx, color in enumerate(["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]):
        legend.append(f'<rect x="{legend_x + idx * 14}" y="{legend_y}" width="11" height="11" rx="2" fill="{color}"/>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">JNU-SHARK commit activity heatmap</title>
  <desc id="desc">{total} commits across visible organization repositories in the past year.</desc>
  <style>
    text {{ font: 10px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; fill: #57606a; }}
    .summary {{ font-weight: 600; fill: #24292f; }}
  </style>
  <text class="summary" x="0" y="{height - 9}">{total} commits in visible repositories, last 365 days</text>
  {''.join(month_labels)}
  {day_labels}
  {''.join(rects)}
  {''.join(legend)}
</svg>
"""


def language_summary(repos: list[dict]) -> str:
    languages = Counter(repo.get("language") or "Docs" for repo in repos if not repo.get("archived"))
    top = languages.most_common(6)
    if not top:
        return "C / C++ / Python / Vue"
    return " / ".join(name for name, _ in top)


def repo_line(repo: dict) -> str:
    name = repo["name"]
    url = repo["html_url"]
    desc = repo.get("description") or "项目仓库"
    lang = repo.get("language") or "Docs"
    pushed = (repo.get("pushed_at") or "")[:10] or "未知"
    stars = repo.get("stargazers_count", 0)
    return f"| [{name}]({url}) | {desc} | {lang} | {stars} | {pushed} |"


def build_readme(org: dict, repos: list[dict], member_count: int, commit_counts: Counter[str]) -> str:
    public_repos = [repo for repo in repos if not repo.get("private")]
    visible_repos = [repo for repo in repos if not repo.get("archived")]
    active_repos = [repo for repo in public_repos if not repo.get("archived") and repo.get("name") != ".github"][:8]
    today = dt.datetime.now(TIMEZONE).date()
    public_count = org.get("public_repos") or len(public_repos)
    total_commits = sum(commit_counts.values())
    latest_public = active_repos[0]["name"] if active_repos else "暂无公开活跃仓库"
    repo_table = "\n".join(repo_line(repo) for repo in active_repos) or "| 暂无 | 暂无 | 暂无 | 0 | 暂无 |"

    return f"""# {TEAM_NAME}

我们是来自江南大学霞客湾校区的 RoboMaster 机器人战队，围绕电控、视觉、机械、嵌入式、上位机与赛事工程化持续建设代码资产。

<!--
配图建议 6：
1. 将战队 GitHub 组织团队页面截图放到 profile/assets/github-team.png。
2. 将代码库列表截图放到 profile/assets/github-repos.png。
3. 若加入截图，可在下方取消图片注释：
   ![JNU-SHARK GitHub team](./assets/github-team.png)
   ![JNU-SHARK repositories](./assets/github-repos.png)
-->

## 当前概览

| 指标 | 数据 |
| --- | ---: |
| 队员 / 组织成员 | {member_count} |
| 维护项目 | {max(len(visible_repos), MANUAL_VISIBLE_PROJECT_COUNT)} |
| 公开项目 | {public_count} |
| 近一年可见提交 | {total_commits} |
| 最近活跃公开项目 | {latest_public} |

## 技术方向

`{language_summary(visible_repos)}`

重点沉淀方向包括机器人电控框架、飞镖系统、哨兵/步兵/英雄机器人代码、雷达与视觉、工程机器人控制、自定义客户端、赛事数据工具与队内新人教程。

## 近期活跃公开项目

| 项目 | 简介 | 语言 | Stars | 最近推送 |
| --- | --- | --- | ---: | --- |
{repo_table}

## Commit 活跃历史

![JNU-SHARK organization commit heatmap](./assets/commit-heatmap.svg)

## 快速入口

[组织主页](https://github.com/{ORG}) · [公开仓库](https://github.com/orgs/{ORG}/repositories) · [战队网站](https://{ORG}.github.io)

---

<sub>Last updated: {today.isoformat()} Asia/Shanghai. Commit heatmap and public repository table are generated from GitHub API.</sub>
"""


def main() -> int:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    org = get_org()
    repos = get_repos()
    member_count = get_member_count()
    today = dt.datetime.now(TIMEZONE).date()
    since = dt.datetime.combine(today - dt.timedelta(days=365), dt.time.min, tzinfo=TIMEZONE)
    commit_counts = collect_commits(repos, since)

    HEATMAP_PATH.write_text(build_heatmap_svg(commit_counts, today), encoding="utf-8")
    README_PATH.write_text(build_readme(org, repos, member_count, commit_counts), encoding="utf-8")

    print(f"Updated {README_PATH.relative_to(ROOT)}")
    print(f"Updated {HEATMAP_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"profile update failed: {exc}", file=sys.stderr)
        raise
