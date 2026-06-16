#!/usr/bin/env python3
"""Generate the JNU-SHARK GitHub organization profile dashboard."""

from __future__ import annotations

import datetime as dt
import functools
import html
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
MAX_COMMIT_PAGES_PER_REPO = int(os.getenv("MAX_COMMIT_PAGES_PER_REPO", "8"))
FULL_STATS_REQUIRED = os.getenv("FULL_STATS_REQUIRED", "0") == "1"
TIMEZONE = dt.timezone(dt.timedelta(hours=8), "Asia/Shanghai")
ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = ROOT / "profile"
ASSETS_DIR = PROFILE_DIR / "assets"
README_PATH = PROFILE_DIR / "README.md"
DASHBOARD_PATH = ASSETS_DIR / "shark-dashboard.svg"


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
    <rect x="{x}" y="{y}" width="245" height="112" rx="22" fill="#10182a" stroke="#23304a"/>
    <rect x="{x}" y="{y}" width="245" height="5" rx="2.5" fill="{accent}"/>
    <text x="{x + 24}" y="{y + 45}" class="label">{html.escape(label)}</text>
    <text x="{x + 24}" y="{y + 88}" class="stat">{html.escape(value)}</text>
  </g>"""


def bar_rows(counter: Counter[str], x: int, y: int, width: int, title: str, accent: str, limit: int = 6) -> str:
    rows = counter.most_common(limit)
    if not rows:
        rows = [("No data", 0)]
    max_value = max((value for _, value in rows), default=1) or 1
    parts = [
        f'<text x="{x}" y="{y}" class="section-title">{html.escape(title)}</text>',
    ]
    for idx, (name, value) in enumerate(rows):
        row_y = y + 38 + idx * 48
        bar_width = max(10, int((value / max_value) * (width - 150)))
        parts.append(
            f"""
  <g>
    <text x="{x}" y="{row_y}" class="row-name">{html.escape(short_name(name, 20))}</text>
    <rect x="{x + 250}" y="{row_y - 16}" width="{width - 250}" height="14" rx="7" fill="#172033"/>
    <rect x="{x + 250}" y="{row_y - 16}" width="{bar_width}" height="14" rx="7" fill="{accent}"/>
    <text x="{x + width}" y="{row_y}" class="row-value" text-anchor="end">{value}</text>
  </g>"""
        )
    return "\n".join(parts)


def language_pills(repos: list[dict]) -> str:
    languages = Counter(repo.get("language") or "Docs" for repo in repos if not repo.get("archived"))
    colors = ["#48d597", "#5db7ff", "#f0d85a", "#ff7a90", "#b59cff", "#ffad5c"]
    x = 78
    y = 770
    parts = ['<text x="78" y="735" class="section-title">TECH STACK</text>']
    for idx, (name, value) in enumerate(languages.most_common(6)):
        pill_x = x + idx * 170
        parts.append(
            f'<g><rect x="{pill_x}" y="{y}" width="146" height="40" rx="20" fill="#10182a" stroke="#263654"/>'
            f'<circle cx="{pill_x + 24}" cy="{y + 20}" r="6" fill="{colors[idx % len(colors)]}"/>'
            f'<text x="{pill_x + 40}" y="{y + 26}" class="pill">{html.escape(name)} · {value}</text></g>'
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
    latest_repo = next((repo["name"] for repo in visible_repos if repo.get("name") != ".github"), "N/A")
    updated = today.isoformat()

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900" role="img" aria-labelledby="title desc">
  <title id="title">JNU-SHARK GitHub organization dashboard</title>
  <desc id="desc">16:9 dashboard with full visible organization statistics, commit heatmap, repository ranking, and contributor ranking.</desc>
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
    .kicker {{ font-size: 24px; font-weight: 700; fill: #52f0b4; letter-spacing: 0; }}
    .title {{ font-size: 78px; font-weight: 900; letter-spacing: 0; }}
    .cn-title {{ font-size: 38px; font-weight: 820; fill: #eef4ff; }}
    .subtitle {{ font-size: 23px; fill: #aab6cc; }}
    .label {{ font-size: 18px; fill: #8fa0bc; font-weight: 650; }}
    .stat {{ font-size: 44px; font-weight: 850; }}
    .section-title {{ font-size: 22px; font-weight: 820; fill: #eef4ff; }}
    .row-name {{ font-size: 18px; fill: #c8d3e7; font-weight: 650; }}
    .row-value {{ font-size: 20px; fill: #eef4ff; font-weight: 800; }}
    .tiny {{ font-size: 15px; fill: #8fa0bc; }}
    .pill {{ font-size: 18px; fill: #d7e2f4; font-weight: 720; }}
    .mono {{ font-size: 18px; fill: #aab6cc; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
  </style>

  <rect width="1600" height="900" fill="url(#bg)"/>
  <path d="M0 124 C250 80 385 160 620 114 C860 67 982 28 1220 74 C1392 108 1495 152 1600 121 L1600 0 L0 0 Z" fill="#12385c" opacity="0.38"/>
  <path d="M0 834 C216 805 318 875 553 830 C835 776 935 837 1160 794 C1350 758 1464 789 1600 744 L1600 900 L0 900 Z" fill="#173622" opacity="0.36"/>

  <g filter="url(#softShadow)">
    <rect x="48" y="42" width="1504" height="816" rx="34" fill="#0b1324" opacity="0.88" stroke="#263654"/>
  </g>

  <text x="78" y="98" class="kicker">ROBOMASTER ENGINEERING · FULL ORG STATS</text>
  <text x="78" y="178" class="title">JNU-SHARK</text>
  <text x="80" y="226" class="cn-title">霞客湾 SHARK 机器人俱乐部</text>
  <text x="80" y="264" class="subtitle">{html.escape(ORG_DESCRIPTION)} · 成员 / 私有仓库 / 全量可见提交统计</text>
  <rect x="78" y="286" width="524" height="6" rx="3" fill="url(#hero)"/>
  <text x="1170" y="104" class="mono">github.com/{ORG}</text>
  <text x="1170" y="136" class="tiny">Updated {updated} Asia/Shanghai</text>
  <text x="1170" y="168" class="tiny">Latest active project: {html.escape(short_name(latest_repo, 30))}</text>

  {stat_card(78, 324, "ORGANIZATION MEMBERS", str(member_count), "#52f0b4")}
  {stat_card(360, 324, "TOTAL PROJECTS", str(max(len(visible_repos), MANUAL_VISIBLE_PROJECT_COUNT)), "#5db7ff")}
  {stat_card(642, 324, "PRIVATE REPOS", str(private_count), "#ff7a90")}
  {stat_card(924, 324, "PUBLIC REPOS", str(public_count), "#f0d85a")}
  {stat_card(1206, 324, "COMMITS · 365D", str(total_commits), "#b59cff")}

  <text x="78" y="506" class="section-title">COMMIT HISTORY · LAST 365 DAYS</text>
  {heatmap_cells(daily_counts, today, 78, 535, 12, 5)}
  <text x="78" y="685" class="tiny">Less</text>
  <rect x="126" y="671" width="16" height="16" rx="4" fill="#172033"/>
  <rect x="152" y="671" width="16" height="16" rx="4" fill="#1b5e6d"/>
  <rect x="178" y="671" width="16" height="16" rx="4" fill="#1f9a8a"/>
  <rect x="204" y="671" width="16" height="16" rx="4" fill="#58c76f"/>
  <rect x="230" y="671" width="16" height="16" rx="4" fill="#e7ff61"/>
  <text x="262" y="685" class="tiny">More</text>

  <g transform="translate(0 0)">
    {bar_rows(author_counts, 1010, 512, 470, "CONTRIBUTOR COMMIT RANKING", "#52f0b4", 3)}
  </g>
  <g transform="translate(0 0)">
    {bar_rows(repo_counts, 1010, 690, 470, "PROJECT COMMIT RANKING", "#5db7ff", 3)}
  </g>

  {language_pills(visible_repos)}
</svg>
"""


def build_readme() -> str:
    return f"""<div align="center">

![{TEAM_NAME} GitHub dashboard](./assets/shark-dashboard.svg)

[组织主页](https://github.com/{ORG}) · [公开仓库](https://github.com/orgs/{ORG}/repositories) · [战队网站](https://{ORG}.github.io)

</div>

<!--
配图建议 6：
1. 这张 dashboard 已经是 16:9，适合直接整图截图。
2. 如需保留 GitHub 组织团队页面截图，可放到 profile/assets/github-team.png。
3. 如需保留代码库列表截图，可放到 profile/assets/github-repos.png。
-->
"""


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
    README_PATH.write_text(build_readme(), encoding="utf-8")

    print(f"Updated {README_PATH.relative_to(ROOT)}")
    print(f"Updated {DASHBOARD_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"profile update failed: {exc}", file=sys.stderr)
        raise
