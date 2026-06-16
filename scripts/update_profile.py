#!/usr/bin/env python3
"""Generate the JNU-SHARK GitHub organization profile dashboard."""

from __future__ import annotations

import datetime as dt
import functools
import html
import json
import os
import shutil
import ssl
import subprocess
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
MAX_COMMIT_PAGES_PER_REPO = int(os.getenv("MAX_COMMIT_PAGES_PER_REPO", "8"))
FULL_STATS_REQUIRED = os.getenv("FULL_STATS_REQUIRED", "0") == "1"
TIMEZONE = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "profile"
ASSETS_DIR = PROFILE_DIR / "assets"
README_PATH = PROFILE_DIR / "README.md"
DASHBOARD_PATH = ASSETS_DIR / "shark-dashboard.svg"
PNG_DASHBOARD_PATH = ASSETS_DIR / "shark-dashboard.png"


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


def short_name(name: str, limit: int = 28) -> str:
    if len(name) <= limit:
        return name
    return f"{name[: limit - 1]}..."


def collect_commit_stats(repos: list[dict], since: dt.datetime) -> tuple[Counter[str], Counter[str], Counter[str]]:
    daily_counts: Counter[str] = Counter()
    repo_counts: Counter[str] = Counter()
    author_counts: Counter[str] = Counter()
    since_utc = since.astimezone(dt.timezone.utc)
    since_iso = since_utc.isoformat().replace("+00:00", "Z")

    for repo in repos:
        if repo.get("archived"):
            continue
        pushed_at = repo.get("pushed_at")
        if pushed_at:
            try:
                pushed_date = dt.datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                if pushed_date < since_utc:
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
        repo_counts[name] += len(commits)
        for commit in commits:
            commit_data = commit.get("commit", {}) if isinstance(commit, dict) else {}
            author = commit_data.get("author", {})
            date_text = author.get("date")
            if date_text:
                try:
                    day = dt.datetime.fromisoformat(date_text.replace("Z", "+00:00")).astimezone(TIMEZONE).date()
                    daily_counts[day.isoformat()] += 1
                except ValueError:
                    pass

            login = (commit.get("author") or {}).get("login") if isinstance(commit, dict) else None
            author_name = login or author.get("name") or "unknown"
            author_counts[author_name] += 1

    return daily_counts, repo_counts, author_counts


def contribution_color(count: int, max_count: int) -> str:
    if count <= 0:
        return "#172033"
    if max_count <= 1:
        level = 1
    else:
        level = min(4, max(1, int((count / max_count) * 4 + 0.999)))
    return ["#1b5e6d", "#1f9a8a", "#58c76f", "#e7ff61"][level - 1]


def heatmap_cells(counts: Counter[str], today: dt.date, left: int, top: int, cell: int, gap: int) -> str:
    start = today - dt.timedelta(days=364)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)
    max_count = max(counts.values(), default=0)
    parts: list[str] = []
    for week in range(53):
        for weekday in range(7):
            day = start + dt.timedelta(days=week * 7 + weekday)
            if day > today:
                continue
            count = counts.get(day.isoformat(), 0)
            x = left + week * (cell + gap)
            y = top + weekday * (cell + gap)
            parts.append(
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" '
                f'fill="{contribution_color(count, max_count)}" opacity="0.96">'
                f'<title>{day.isoformat()}: {count} commits</title></rect>'
            )
    return "\n".join(parts)


def stat_card(x: int, y: int, label: str, value: str, accent: str) -> str:
    return f"""
  <g>
    <rect x="{x}" y="{y}" width="260" height="126" rx="24" fill="#10182a" stroke="#25334f"/>
    <rect x="{x}" y="{y}" width="260" height="6" rx="3" fill="{accent}"/>
    <text x="{x + 26}" y="{y + 47}" class="label">{html.escape(label)}</text>
    <text x="{x + 26}" y="{y + 99}" class="stat">{html.escape(value)}</text>
  </g>"""


def ranking_table(counter: Counter[str], x: int, y: int, title: str, accent: str, limit: int = 3) -> str:
    rows = counter.most_common(limit)
    if not rows:
        rows = [("暂无数据", 0)]
    parts = [
        f'<text x="{x}" y="{y}" class="section-title">{html.escape(title)}</text>',
        f'<text x="{x + 46}" y="{y + 29}" class="table-head">名称</text>',
        f'<text x="{x + 388}" y="{y + 29}" class="table-head" text-anchor="end">提交数</text>',
    ]
    for idx, (name, value) in enumerate(rows):
        row_y = y + 51 + idx * 35
        rank = idx + 1
        parts.append(
            f"""
  <g>
    <rect x="{x}" y="{row_y - 21}" width="410" height="30" rx="10" fill="#111b2e" stroke="#22314d"/>
    <circle cx="{x + 22}" cy="{row_y - 6}" r="11" fill="{accent}" opacity="0.95"/>
    <text x="{x + 22}" y="{row_y}" class="rank" text-anchor="middle">{rank}</text>
    <text x="{x + 46}" y="{row_y - 1}" class="row-name">{html.escape(short_name(name, 22))}</text>
    <text x="{x + 388}" y="{row_y - 1}" class="row-value" text-anchor="end">{value} 次</text>
  </g>"""
        )
    return "\n".join(parts)


def build_dashboard_svg(
    org: dict,
    repos: list[dict],
    member_count: int,
    daily_counts: Counter[str],
    repo_counts: Counter[str],
    author_counts: Counter[str],
) -> str:
    today = dt.datetime.now(TIMEZONE).date()
    visible_repos = [repo for repo in repos if not repo.get("archived")]
    public_count = org.get("public_repos") or sum(1 for repo in visible_repos if not repo.get("private"))
    private_count = sum(1 for repo in visible_repos if repo.get("private"))
    total_commits = sum(daily_counts.values())
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900" role="img" aria-labelledby="title desc">
  <title id="title">JNU-SHARK 代码活跃看板</title>
  <desc id="desc">16:9 organization statistics dashboard.</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#07111f"/>
      <stop offset="0.52" stop-color="#0b1020"/>
      <stop offset="1" stop-color="#131625"/>
    </linearGradient>
    <linearGradient id="hero" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#52f0b4"/>
      <stop offset="0.45" stop-color="#5db7ff"/>
      <stop offset="1" stop-color="#f0d85a"/>
    </linearGradient>
    <filter id="softShadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="18" stdDeviation="18" flood-color="#000000" flood-opacity="0.32"/>
    </filter>
  </defs>
  <style>
    text {{ font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; fill: #e8edf7; }}
    .title {{ font-size: 64px; font-weight: 900; letter-spacing: 0; }}
    .subtitle {{ font-size: 32px; font-weight: 780; fill: #e8edf7; }}
    .label {{ font-size: 22px; fill: #aab6cc; font-weight: 760; }}
    .stat {{ font-size: 50px; font-weight: 900; }}
    .section-title {{ font-size: 28px; font-weight: 860; fill: #eef4ff; }}
    .table-head {{ font-size: 16px; fill: #8494b4; font-weight: 720; }}
    .row-name {{ font-size: 18px; fill: #d7e2f4; font-weight: 720; }}
    .row-value {{ font-size: 18px; fill: #eef4ff; font-weight: 860; }}
    .rank {{ font-size: 15px; fill: #07111f; font-weight: 900; }}
    .tiny {{ font-size: 18px; fill: #aab6cc; font-weight: 620; }}
  </style>

  <rect width="1600" height="900" fill="url(#bg)"/>
  <path d="M0 124 C250 80 385 160 620 114 C860 67 982 28 1220 74 C1392 108 1495 152 1600 121 L1600 0 L0 0 Z" fill="#12385c" opacity="0.38"/>
  <path d="M0 834 C216 805 318 875 553 830 C835 776 935 837 1160 794 C1350 758 1464 789 1600 744 L1600 900 L0 900 Z" fill="#173622" opacity="0.36"/>

  <g filter="url(#softShadow)">
    <rect x="48" y="42" width="1504" height="816" rx="34" fill="#0b1324" opacity="0.88" stroke="#263654"/>
  </g>

  <text x="78" y="124" class="title">JNU-SHARK 代码活跃看板</text>
  <text x="80" y="172" class="subtitle">霞客湾 SHARK 机器人俱乐部</text>
  <rect x="78" y="200" width="520" height="7" rx="3.5" fill="url(#hero)"/>

  {stat_card(78, 245, "成员", str(member_count), "#52f0b4")}
  {stat_card(362, 245, "项目总数", str(max(len(visible_repos), MANUAL_VISIBLE_PROJECT_COUNT)), "#5db7ff")}
  {stat_card(646, 245, "私有仓库", str(private_count), "#ff7a90")}
  {stat_card(930, 245, "公开仓库", str(public_count), "#f0d85a")}
  {stat_card(1214, 245, "近一年提交", str(total_commits), "#b59cff")}

  <rect x="78" y="412" width="880" height="388" rx="28" fill="#10182a" stroke="#25334f"/>
  <text x="112" y="466" class="section-title">近一年提交热力图 · {total_commits} 次</text>
  {heatmap_cells(daily_counts, today, 112, 510, 12, 3)}
  <text x="112" y="666" class="tiny">少</text>
  <rect x="150" y="649" width="17" height="17" rx="4" fill="#172033"/>
  <rect x="178" y="649" width="17" height="17" rx="4" fill="#1b5e6d"/>
  <rect x="206" y="649" width="17" height="17" rx="4" fill="#1f9a8a"/>
  <rect x="234" y="649" width="17" height="17" rx="4" fill="#58c76f"/>
  <rect x="262" y="649" width="17" height="17" rx="4" fill="#e7ff61"/>
  <text x="300" y="666" class="tiny">多</text>

  <rect x="990" y="412" width="484" height="184" rx="28" fill="#10182a" stroke="#25334f"/>
  {ranking_table(author_counts, 1028, 454, "成员提交排行", "#52f0b4", 3)}
  <rect x="990" y="616" width="484" height="184" rx="28" fill="#10182a" stroke="#25334f"/>
  {ranking_table(repo_counts, 1028, 658, "项目提交排行", "#5db7ff", 3)}
</svg>
"""


def build_readme() -> str:
    return f"""<div align="center">

![{TEAM_NAME} 代码活跃看板](./assets/shark-dashboard.png)

</div>
"""


def render_dashboard_png() -> bool:
    converter = shutil.which("rsvg-convert")
    if not converter:
        print("rsvg-convert not found; skipped PNG rendering", file=sys.stderr)
        return False
    subprocess.run(
        [
            converter,
            "--width",
            "1600",
            "--height",
            "900",
            str(DASHBOARD_PATH),
            "--output",
            str(PNG_DASHBOARD_PATH),
        ],
        check=True,
    )
    return True


def ensure_full_stats(repos: list[dict], member_count: int) -> None:
    if not FULL_STATS_REQUIRED:
        return
    if member_count < MANUAL_MEMBER_COUNT or len(repos) < MANUAL_VISIBLE_PROJECT_COUNT:
        raise RuntimeError(
            "full organization stats are required, but the token cannot see all members/repos. "
            "Set PROFILE_STATS_TOKEN with repo and read:org scopes."
        )


def main() -> int:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    org = get_org()
    repos = get_repos()
    member_count = get_member_count()
    ensure_full_stats(repos, member_count)

    today = dt.datetime.now(TIMEZONE).date()
    since = dt.datetime.combine(today - dt.timedelta(days=365), dt.time.min, tzinfo=TIMEZONE)
    daily_counts, repo_counts, author_counts = collect_commit_stats(repos, since)

    DASHBOARD_PATH.write_text(
        build_dashboard_svg(org, repos, member_count, daily_counts, repo_counts, author_counts),
        encoding="utf-8",
    )
    rendered_png = render_dashboard_png()
    README_PATH.write_text(build_readme(), encoding="utf-8")

    print(f"Updated {README_PATH.relative_to(ROOT)}")
    print(f"Updated {DASHBOARD_PATH.relative_to(ROOT)}")
    if rendered_png:
        print(f"Updated {PNG_DASHBOARD_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"profile update failed: {exc}", file=sys.stderr)
        raise
