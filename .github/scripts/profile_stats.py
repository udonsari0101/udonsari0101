"""Render live profile stats as SVG cards (stdlib only).

    GH_TOKEN=... python .github/scripts/profile_stats.py OUT_DIR

Writes stats-<lang>-<theme>.svg and contrib-<lang>-<theme>.svg for lang en|ko and
theme light|dark. With the owner's token, repository counts include private
repositories; with the default Actions token they fall back to public data.
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

LOGIN = "udonsari0101"
API = "https://api.github.com/graphql"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',Helvetica,Arial,sans-serif"

THEMES = {
    "light": dict(card="#FFFFFF", border="#D1D9E0", text="#1F2328", muted="#59636E", accent="#4F46E5",
                  empty="#EBEEF3", levels=["#C7D2FE", "#818CF8", "#4F46E5", "#3730A3"]),
    "dark": dict(card="#0D1117", border="#3D444D", text="#F0F6FC", muted="#9198A1", accent="#A5B4FC",
                 empty="#1E242C", levels=["#312E81", "#4338CA", "#6366F1", "#A5B4FC"]),
}
TEXT = {
    "en": dict(title="GitHub activity", since="since {month} {year}",
               labels=["Total contributions", "Current streak", "Longest streak",
                       "Repositories", "Contributed to", "Active days (1y)"],
               day="day", days="days", repos="repos", public="{n} public",
               heat="{n} contributions in the last year", less="Less", more="More",
               months=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
               weekdays={1: "Mon", 3: "Wed", 5: "Fri"}),
    "ko": dict(title="GitHub 활동", since="{year}년 {monthnum}월부터",
               labels=["총 기여", "현재 연속 기여", "최장 연속 기여", "레포지토리", "기여한 레포", "활동한 날(1년)"],
               day="일", days="일", repos="개", public="공개 {n}개",
               heat="최근 1년간 {n}회 기여", less="적음", more="많음",
               months=[f"{m}월" for m in range(1, 13)], weekdays={1: "월", 3: "수", 5: "금"}),
}


def graphql(query, variables):
    req = urllib.request.Request(API, json.dumps({"query": query, "variables": variables}).encode(), {
        "Authorization": f"bearer {os.environ['GH_TOKEN']}", "Content-Type": "application/json",
        "User-Agent": "profile-stats"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if body.get("errors"):
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]


def fetch():
    head = graphql("""query($login: String!) { user(login: $login) {
        createdAt
        repos: repositories(ownerAffiliations: OWNER) { totalCount }
        publicRepos: repositories(ownerAffiliations: OWNER, privacy: PUBLIC) { totalCount }
        contributedTo: repositoriesContributedTo(includeUserRepositories: false,
            contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount }
        contributionsCollection { contributionCalendar { totalContributions
            weeks { contributionDays { date weekday contributionCount } } } } } }""", {"login": LOGIN})["user"]
    created = dt.datetime.fromisoformat(head["createdAt"].replace("Z", "+00:00"))
    days = {}
    year_start = dt.datetime(created.year, 1, 1, tzinfo=dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    while year_start <= now:
        year_end = min(dt.datetime(year_start.year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc), now)
        data = graphql("""query($login: String!, $from: DateTime!, $to: DateTime!) { user(login: $login) {
            contributionsCollection(from: $from, to: $to) { contributionCalendar {
                weeks { contributionDays { date contributionCount } } } } } }""",
                       {"login": LOGIN, "from": year_start.isoformat(), "to": year_end.isoformat()})
        for week in data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
        year_start = dt.datetime(year_start.year + 1, 1, 1, tzinfo=dt.timezone.utc)
    return head, created, days


def streaks(days):
    dates = sorted(days)
    longest = run = 0
    for d in dates:
        run = run + 1 if days[d] else 0
        longest = max(longest, run)
    current = 0
    for i, d in enumerate(reversed(dates)):
        if days[d]:
            current += 1
        elif i == 0:
            continue  # today may not have a contribution yet
        else:
            break
    return current, longest


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def style(t):
    return (f"<style>text{{font-family:{FONT}}}"
            ".v{opacity:0;animation:up .6s ease-out forwards}"
            "@keyframes up{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}"
            ".c{opacity:0;animation:in .4s ease-out forwards}@keyframes in{to{opacity:1}}"
            "@media (prefers-reduced-motion:reduce){.v,.c{animation:none;opacity:1}}</style>")


def stats_svg(lang, theme, s):
    t, x = THEMES[theme], TEXT[lang]
    w, h = 440, 200
    since = x["since"].format(month=x["months"][s["created"].month - 1] if lang == "en" else "",
                              year=s["created"].year, monthnum=s["created"].month)
    unit = lambda n: x["day"] if n == 1 else x["days"]
    cells = [
        (f"{s['total']:,}", "", ""),
        (f"{s['current']}", unit(s["current"]), ""),
        (f"{s['longest']}", unit(s["longest"]), ""),
        (f"{s['repos']}", x["repos"] if lang == "ko" else "", x["public"].format(n=s["public"])),
        (f"{s['contributed']}", x["repos"], ""),
        (f"{s['active']}", unit(s["active"]), ""),
    ]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">',
           f"<title>{esc(x['title'])}</title>", style(t),
           '<defs><linearGradient id="g" x1="0" x2="1"><stop offset="0" stop-color="#4F46E5"/>'
           '<stop offset="1" stop-color="#0E7490"/></linearGradient>'
           f'<clipPath id="k"><rect width="{w}" height="{h}" rx="10"/></clipPath></defs>',
           f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="10" fill="{t["card"]}" stroke="{t["border"]}"/>',
           f'<rect width="{w}" height="4" fill="url(#g)" clip-path="url(#k)"/>',
           f'<text x="20" y="34" font-size="15" font-weight="700" fill="{t["text"]}">{esc(x["title"])}</text>',
           f'<text x="{w-20}" y="34" font-size="12" text-anchor="end" fill="{t["muted"]}">{esc(since)}</text>']
    for i, (num, suffix, note) in enumerate(cells):
        col, row = i % 3, i // 3
        cx, cy = 20 + col * 140, 82 + row * 74
        delay = f"animation-delay:{i * 0.08:.2f}s"
        tail = f'<tspan font-size="13" font-weight="600" fill="{t["muted"]}"> {esc(suffix)}</tspan>' if suffix else ""
        out.append(f'<g class="v" style="{delay}">'
                   f'<text x="{cx}" y="{cy}" font-size="26" font-weight="700" fill="{t["accent"] if row == 0 else t["text"]}">{esc(num)}{tail}</text>'
                   f'<text x="{cx}" y="{cy + 20}" font-size="12" fill="{t["muted"]}">{esc(x["labels"][i])}'
                   + (f' · {esc(note)}' if note else "") + "</text></g>")
    out.append("</svg>")
    return "\n".join(out)


def level(n, cuts):
    if n == 0:
        return -1
    return sum(n > c for c in cuts)


def contrib_svg(lang, theme, days, today):
    t, x = THEMES[theme], TEXT[lang]
    end = today
    start = end - dt.timedelta(days=364 + (end.weekday() + 1) % 7)  # begin on a Sunday
    grid, d = [], start
    while d <= end:
        grid.append((d, days.get(d.isoformat(), 0)))
        d += dt.timedelta(days=1)
    counts = sorted(c for _, c in grid if c)
    q = lambda p: counts[min(len(counts) - 1, int(len(counts) * p))] if counts else 0
    cuts = [q(0.25), q(0.5), q(0.75)]
    total = sum(c for _, c in grid)
    cell, gap, left, top = 12, 3, 32, 46
    weeks = (len(grid) + 6) // 7
    w = left + weeks * (cell + gap) + 16
    h = top + 7 * (cell + gap) + 30
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">',
           f"<title>{esc(x['heat'].format(n=f'{total:,}'))}</title>", style(t),
           f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="10" fill="{t["card"]}" stroke="{t["border"]}"/>',
           f'<text x="{left}" y="24" font-size="13" font-weight="600" fill="{t["text"]}">'
           f'{esc(x["heat"].format(n=f"{total:,}"))}</text>']
    last_month = None
    for i, (day, count) in enumerate(grid):
        col, row = i // 7, (day.weekday() + 1) % 7
        if row == 0 and day.month != last_month and day.day <= 7:
            out.append(f'<text x="{left + col * (cell + gap)}" y="{top - 6}" font-size="10" fill="{t["muted"]}">'
                       f'{esc(x["months"][day.month - 1])}</text>')
            last_month = day.month
        lv = level(count, cuts)
        fill = t["empty"] if lv < 0 else t["levels"][lv]
        out.append(f'<rect class="c" style="animation-delay:{col * 0.012:.3f}s" x="{left + col * (cell + gap)}" '
                   f'y="{top + row * (cell + gap)}" width="{cell}" height="{cell}" rx="2.5" fill="{fill}">'
                   f"<title>{day.isoformat()}: {count}</title></rect>")
    for r, name in x["weekdays"].items():
        out.append(f'<text x="{left - 6}" y="{top + r * (cell + gap) + 10}" font-size="10" text-anchor="end" '
                   f'fill="{t["muted"]}">{esc(name)}</text>')
    ly = top + 7 * (cell + gap) + 10
    lx = w - 16 - 5 * (cell + 3) - 40
    out.append(f'<text x="{lx - 6}" y="{ly + 10}" font-size="10" text-anchor="end" fill="{t["muted"]}">{esc(x["less"])}</text>')
    for i, fill in enumerate([t["empty"]] + t["levels"]):
        out.append(f'<rect x="{lx + i * (cell + 3)}" y="{ly}" width="{cell}" height="{cell}" rx="2.5" fill="{fill}"/>')
    out.append(f'<text x="{lx + 5 * (cell + 3) + 4}" y="{ly + 10}" font-size="10" fill="{t["muted"]}">{esc(x["more"])}</text>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
    out.mkdir(parents=True, exist_ok=True)
    head, created, days = fetch()
    today = dt.datetime.now(dt.timezone.utc).date()
    last_year = [d for d in days if dt.date.fromisoformat(d) > today - dt.timedelta(days=365)]
    current, longest = streaks(days)
    s = dict(total=sum(days.values()), current=current, longest=longest,
             repos=head["repos"]["totalCount"], public=head["publicRepos"]["totalCount"],
             contributed=head["contributedTo"]["totalCount"],
             active=sum(1 for d in last_year if days[d]), created=created)
    for lang in TEXT:
        for theme in THEMES:
            (out / f"stats-{lang}-{theme}.svg").write_text(stats_svg(lang, theme, s), encoding="utf-8")
            (out / f"contrib-{lang}-{theme}.svg").write_text(contrib_svg(lang, theme, days, today), encoding="utf-8")
    print(json.dumps({k: v for k, v in s.items() if k != "created"}))


if __name__ == "__main__":
    main()