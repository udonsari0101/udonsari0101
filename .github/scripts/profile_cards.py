"""Render the profile's live cards and tech-stack badges, and keep README blocks in sync.

    GH_TOKEN=... python .github/scripts/profile_cards.py OUT_DIR [--sync-readme]

Writes stats-<lang>-<theme>.svg and contrib-<lang>-<theme>.svg (activity), one
capsule badge per technology (badges/<id>.svg), and contact.svg. With the owner's
token (OWNER_TOKEN=true) repository counts include private repositories; otherwise
the stats card shows public numbers. --sync-readme rewrites the blocks between the
stack and contact markers in both READMEs: the stack table from STACK below, the
contact pill from the public email on the GitHub profile.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

LOGIN = "udonsari0101"
RAW = f"https://raw.githubusercontent.com/{LOGIN}/{LOGIN}/profile-cards/"
ICONS = "https://cdn.jsdelivr.net/npm/simple-icons@15.17.0/icons/{}.svg"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',Helvetica,Arial,sans-serif"
ACCENT = ("#4F46E5", "#7C3AED", "#0E7490")

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
               public_labels=["Public repositories", "This year"],
               day="day", days="days", repos="repos", public="{n} public",
               heat="{n} contributions in the last year", less="Less", more="More",
               months=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
               weekdays={1: "Mon", 3: "Wed", 5: "Fri"}, email="Email"),
    "ko": dict(title="GitHub 활동", since="{year}년 {monthnum}월부터",
               labels=["총 기여", "현재 연속 기여", "최장 연속 기여", "레포지토리", "기여한 레포", "활동한 날(1년)"],
               public_labels=["공개 레포지토리", "올해 기여"],
               day="일", days="일", repos="개", public="공개 {n}개",
               heat="최근 1년간 {n}회 기여", less="적음", more="많음",
               months=[f"{m}월" for m in range(1, 13)], weekdays={1: "월", 3: "수", 5: "금"}, email="이메일"),
}

# (EN label, KO label, [(name, simple-icons slug or #glyph, badge hex, official site/repo or None, alt)])
STACK = [
    ("Languages", "언어", [
        ("Python", "python", "3776AB", "https://www.python.org"),
        ("JavaScript", "javascript", "F7DF1E", "https://developer.mozilla.org/en-US/docs/Web/JavaScript"),
        ("TypeScript", "typescript", "3178C6", "https://www.typescriptlang.org"),
        ("Kotlin", "kotlin", "7F52FF", "https://kotlinlang.org"),
        ("SQL", "#database", "336791", None)]),
    ("Frontend · Backend", "프론트엔드·백엔드", [
        ("React", "react", "087EA4", "https://react.dev"),
        ("HTML", "html5", "E34F26", "https://html.spec.whatwg.org"),
        ("CSS", "css", "663399", "https://www.w3.org/Style/CSS/"),
        ("FastAPI", "fastapi", "009688", "https://fastapi.tiangolo.com"),
        ("Flask", "flask", "475569", "https://flask.palletsprojects.com"),
        ("REST API", "openapiinitiative", "4D7F2A", None)]),
    ("Databases", "데이터베이스", [
        ("PostgreSQL", "postgresql", "4169E1", "https://www.postgresql.org"),
        ("MySQL", "mysql", "4479A1", "https://www.mysql.com"),
        ("SQLite", "sqlite", "0B5E86", "https://www.sqlite.org"),
        ("Firebase", "firebase", "FFCA28", "https://firebase.google.com"),
        ("Firestore", "firebase", "B45309", "https://firebase.google.com/docs/firestore")]),
    ("Desktop · Android", "데스크톱·Android", [
        ("PySide6 (Qt)", "qt", "217A35", "https://doc.qt.io/qtforpython-6/"),
        ("Electron", "electron", "47848F", "https://www.electronjs.org", "Electron (Node.js)"),
        ("Windows", "#window", "0078D4", "https://learn.microsoft.com/windows/apps/"),
        ("Jetpack Compose", "jetpackcompose", "4285F4", "https://developer.android.com/compose"),
        ("Android SDK", "android", "34A853", "https://developer.android.com"),
        ("Gradle", "gradle", "0F6674", "https://gradle.org")]),
    ("DevOps · Cloud", "데브옵스·클라우드", [
        ("Linux", "linux", "FCC624", "https://www.kernel.org"),
        ("Docker", "docker", "2496ED", "https://www.docker.com"),
        ("Docker Compose", "docker", "1D63ED", "https://docs.docker.com/compose/"),
        ("AWS", "#cloud", "FF9900", "https://aws.amazon.com"),
        ("GCP", "googlecloud", "4285F4", "https://cloud.google.com"),
        ("GitHub Actions", "githubactions", "2088FF", "https://github.com/features/actions")]),
    ("Robotics", "로보틱스", [
        ("ROS 2", "ros", "34508A", "https://www.ros.org"),
        ("Gazebo", "#cube", "B85409", "https://gazebosim.org"),
        ("RViz", "#axes", "4F5BD5", "https://github.com/ros2/rviz")]),
    ("AI", "AI", [
        ("Generative AI", "#sparkle", "7C3AED", None),
        ("Diffusion Models", "#diffusion", "6D28D9", None),
        ("LLM Integration & Fine-tuning", "#chat", "5B21B6", None)]),
    ("Security Tools", "보안 도구", [
        ("IDA Pro", "#magnifier", "4B5563", "https://hex-rays.com/ida-pro"),
        ("Ghidra", "#graph", "B91C1C", "https://ghidra-sre.org"),
        ("JADX-GUI", "#braces", "0369A1", "https://github.com/skylot/jadx"),
        ("x64dbg", "#bug", "475569", "https://x64dbg.com"),
        ("Burp Suite", "burpsuite", "C73E12", "https://portswigger.net/burp"),
        ("mitmproxy", "#swap", "0F766E", "https://mitmproxy.org")]),
    ("Tools", "도구", [
        ("Notion", "notion", "3F3F46", "https://www.notion.so"),
        ("Figma", "figma", "F24E1E", "https://www.figma.com")]),
]


def ring(cx, cy, r):
    return f"M{cx - r} {cy}a{r} {r} 0 1 0 {2 * r} 0a{r} {r} 0 1 0 {-2 * r} 0z"


# Generic glyphs on a 24x24 grid for tools without a simple-icons logo: (fill paths, stroke paths).
GLYPHS = {
    "#database": ([], ["M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z",
                       "M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6", "M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"]),
    "#window": (["M3 3h8.5v8.5H3zM12.5 3H21v8.5h-8.5zM3 12.5h8.5V21H3zM12.5 12.5H21V21h-8.5z"], []),
    "#cloud": ([], ["M7 19h10.5a4.5 4.5 0 0 0 .7-8.95A6.5 6.5 0 0 0 5.6 9.2 5 5 0 0 0 7 19z"]),
    "#cube": ([], ["M12 2.5 20.5 7v10L12 21.5 3.5 17V7z", "M3.5 7 12 11.5 20.5 7", "M12 11.5v10"]),
    "#axes": ([ring(12, 14, 1.8)], ["M12 14V3.5", "M9.5 6 12 3.5 14.5 6", "M12 14l8.2 4.6",
                                    "M17.1 19.6l3.1-1 -.9-3.1", "M12 14l-8.2 4.6", "M6.9 19.6l-3.1-1 .9-3.1"]),
    "#sparkle": (["M11 1.5l2.4 6.6 6.6 2.4-6.6 2.4L11 19.5l-2.4-6.6L2 10.5l6.6-2.4z"
                  "M19 14.5l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1z"], []),
    "#diffusion": ([ring(12, 12, 2.6), ring(4, 5, 1), ring(20, 5, 1), ring(4, 19, 1), ring(20, 19, 1)],
                   [ring(12, 12, 6.5)]),
    "#chat": ([ring(8.3, 11.5, 1.2), ring(12, 11.5, 1.2), ring(15.7, 11.5, 1.2)],
              ["M5 4.5h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-8.5L6 21v-3.5H5a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2z"]),
    "#magnifier": ([], [ring(10.5, 10.5, 6.5), "M15.3 15.3 21 21", "M8 8.5v4", "M11.5 8.5h2v4h-2z"]),
    "#graph": ([ring(12, 4.5, 2.2), ring(5, 12, 2.2), ring(19, 12, 2.2), ring(12, 19.5, 2.2)],
               ["M10.6 6.2 6.4 10.3", "M13.4 6.2l4.2 4.1", "M6.4 13.7l4.2 4.1", "M17.6 13.7l-4.2 4.1"]),
    "#braces": ([], ["M8.5 3.5C6.5 3.5 6 4.6 6 6.5v2.6c0 1.2-.8 2.4-2.5 2.9 1.7.5 2.5 1.7 2.5 2.9v2.6c0 1.9.5 3 2.5 3",
                     "M15.5 3.5c2 0 2.5 1.1 2.5 3v2.6c0 1.2.8 2.4 2.5 2.9-1.7.5-2.5 1.7-2.5 2.9v2.6c0 1.9-.5 3-2.5 3",
                     "M10.5 12h3"]),
    "#bug": ([], ["M12 7.5a4.5 4.5 0 0 1 4.5 4.5v3a4.5 4.5 0 0 1-9 0v-3A4.5 4.5 0 0 1 12 7.5z", "M12 11v8",
                  "M7.5 12.5H3.5", "M7.6 16.5 4.5 18", "M16.5 12.5h4", "M16.4 16.5l3.1 1.5",
                  "M9.5 8.3 7.5 5.5", "M14.5 8.3l2-2.8"]),
    "#swap": ([], ["M3.5 8h15", "M14.5 4l4 4-4 4", "M20.5 16h-15", "M9.5 12l-4 4 4 4"]),
}
MAIL = "M3 6.5A2.5 2.5 0 0 1 5.5 4h13A2.5 2.5 0 0 1 21 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5zm2.2-.3 6.8 5.4 6.8-5.4z"


# ---------------------------------------------------------------- helpers
def esc(s):
    return html.escape(str(s), quote=True)


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_w(s, size, bold=False):
    k = 1.06 if bold else 1.0
    return k * sum(size * (1.0 if ord(c) > 0x3000 else 0.3 if c in " .,'il|()!" else 0.66 if c.isupper()
                           else 0.6 if c.isdigit() else 0.56) for c in s)


def slug_id(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def style(t):
    return (f"<style>text{{font-family:{FONT}}}"
            ".v{opacity:0;animation:up .6s ease-out forwards}"
            "@keyframes up{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}"
            ".c{opacity:0;animation:in .4s ease-out forwards}@keyframes in{to{opacity:1}}"
            "@media (prefers-reduced-motion:reduce){.v,.c{animation:none;opacity:1}}</style>")


def svg_open(w, h, title):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">',
            f"<title>{esc(title)}</title>", f"<style>text{{font-family:{FONT}}}</style>"]


def gradient(gid, colors, x2="1", y2="0"):
    stops = "".join(f'<stop offset="{i / (len(colors) - 1):.2f}" stop-color="{c}"/>' for i, c in enumerate(colors))
    return f'<linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}">{stops}</linearGradient>'


# ---------------------------------------------------------------- data
def request(url, data=None):
    headers = {"Authorization": f"bearer {os.environ['GH_TOKEN']}", "User-Agent": "profile-cards"}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=30) as r:
        return json.load(r)


def graphql(query, variables):
    body = request("https://api.github.com/graphql", {"query": query, "variables": variables})
    if body.get("errors"):
        raise SystemExit(f"GraphQL error: {body['errors']}")
    return body["data"]


def fetch():
    head = graphql("""query($login: String!) { user(login: $login) {
        createdAt
        repos: repositories(ownerAffiliations: OWNER) { totalCount }
        publicRepos: repositories(ownerAffiliations: OWNER, privacy: PUBLIC) { totalCount }
        contributedTo: repositoriesContributedTo(includeUserRepositories: false,
            contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount } } }""",
                   {"login": LOGIN})["user"]
    created = dt.datetime.fromisoformat(head["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    days, start = {}, dt.datetime(created.year, 1, 1, tzinfo=dt.timezone.utc)
    while start <= now:
        end = min(dt.datetime(start.year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc), now)
        data = graphql("""query($login: String!, $from: DateTime!, $to: DateTime!) { user(login: $login) {
            contributionsCollection(from: $from, to: $to) { contributionCalendar {
                weeks { contributionDays { date contributionCount } } } } } }""",
                       {"login": LOGIN, "from": start.isoformat(), "to": end.isoformat()})
        for week in data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
        start = dt.datetime(start.year + 1, 1, 1, tzinfo=dt.timezone.utc)
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
        elif i:
            break
    return current, longest


def public_email():
    try:
        email = (request(f"https://api.github.com/users/{LOGIN}").get("email") or "").strip()
    except Exception as e:  # noqa: BLE001 — keep the README as it is when the API fails
        print(f"email lookup failed: {e}")
        return None
    return email if re.fullmatch(r"[^@\s<>\"']+@[^@\s<>\"']+\.[A-Za-z]{2,}", email) else ""


def icon_path(slug):
    try:
        with urllib.request.urlopen(ICONS.format(slug), timeout=30) as r:
            return re.search(r'<path d="([^"]+)"', r.read().decode()).group(1)
    except Exception as e:  # noqa: BLE001 — the badge falls back to a dot
        print(f"icon {slug} unavailable: {e}")
        return None


# ---------------------------------------------------------------- activity cards
def stats_svg(lang, theme, s):
    t, x = THEMES[theme], TEXT[lang]
    w, h = 440, 200
    since = x["since"].format(month=x["months"][s["created"].month - 1] if lang == "en" else "",
                              year=s["created"].year, monthnum=s["created"].month)
    unit = lambda n: x["day"] if n == 1 else x["days"]
    labels = list(x["labels"])
    cells = [(f"{s['total']:,}", "", ""), (f"{s['current']}", unit(s["current"]), ""),
             (f"{s['longest']}", unit(s["longest"]), "")]
    if s["owner"]:
        cells += [(f"{s['repos']}", x["repos"] if lang == "ko" else "", x["public"].format(n=s["public"])),
                  (f"{s['contributed']}", x["repos"], "")]
    else:  # the default Actions token sees public data only; don't show private-dependent zeros
        labels[3:5] = x["public_labels"]
        cells += [(f"{s['public']}", x["repos"] if lang == "ko" else "", ""), (f"{s['year']:,}", "", "")]
    cells.append((f"{s['active']}", unit(s["active"]), ""))
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
                   f'<text x="{cx}" y="{cy + 20}" font-size="12" fill="{t["muted"]}">{esc(labels[i])}'
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


# ---------------------------------------------------------------- badges
BADGE_H, BADGE_FS, ICON, PAD_Y = 25, 11.5, 14, 3  # PAD_Y: transparent space above and below each pill


def glyph_markup(icon, paths, color, x, y):
    scale = ICON / 24
    head = f'<g transform="translate({x:.1f},{y:.1f}) scale({scale:.4f})">'
    if icon.startswith("#"):
        fills, strokes = GLYPHS[icon]
        body = "".join(f'<path d="{d}" fill="{color}"/>' for d in fills)
        body += "".join(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.1" stroke-linecap="round" '
                        f'stroke-linejoin="round"/>' for d in strokes)
        return head + body + "</g>"
    d = paths.get(icon)
    if not d:
        return f'<circle cx="{x + ICON / 2:.1f}" cy="{y + ICON / 2:.1f}" r="3" fill="{color}"/>'
    return head + f'<path d="{d}" fill="{color}"/></g>'


def badge_svg(name, icon, color, paths, alt):
    """A capsule badge: brand colour, a soft top gloss, a white (or dark on light brands) glyph and name."""
    color = "#" + color
    dark_ink = lum(color) > 0.45
    ink = "#1F2328" if dark_ink else "#FFFFFF"
    tw = text_w(name, BADGE_FS, bold=True)
    w = round(10 + ICON + 6 + tw + 11)
    h = BADGE_H
    out = svg_open(w, h + 2 * PAD_Y, alt)
    out.append("<defs>"
               '<linearGradient id="gloss" x1="0" y1="0" x2="0" y2="1">'
               '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".34"/>'
               '<stop offset=".48" stop-color="#FFFFFF" stop-opacity=".08"/>'
               '<stop offset=".5" stop-color="#FFFFFF" stop-opacity="0"/>'
               '<stop offset="1" stop-color="#000000" stop-opacity=".14"/></linearGradient></defs>')
    out.append(f'<g transform="translate(0,{PAD_Y})">')
    out.append(f'<rect width="{w}" height="{h}" rx="{h / 2}" fill="{color}"/>')
    out.append(f'<rect width="{w}" height="{h}" rx="{h / 2}" fill="url(#gloss)"/>')
    out.append(f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="{(h - 1) / 2}" fill="none" '
               f'stroke="#FFFFFF" stroke-opacity=".28"/>')
    out.append(glyph_markup(icon, paths, ink, 10, (h - ICON) / 2))
    ty = h / 2 + BADGE_FS * 0.36
    if not dark_ink:
        out.append(f'<text x="{10 + ICON + 6}" y="{ty + 1:.1f}" font-size="{BADGE_FS}" font-weight="700" '
                   f'fill="#000000" fill-opacity=".22" textLength="{tw:.1f}" lengthAdjust="spacingAndGlyphs">{esc(name)}</text>')
    out.append(f'<text x="{10 + ICON + 6}" y="{ty:.1f}" font-size="{BADGE_FS}" font-weight="700" fill="{ink}" '
               f'textLength="{tw:.1f}" lengthAdjust="spacingAndGlyphs">{esc(name)}</text>')
    out.append("</g></svg>")
    return "\n".join(out), w


def stack_block(lang):
    rows = []
    for en, ko, items in STACK:
        label = f'<td valign="top" nowrap>{esc(ko)}</td>' if lang == "ko" else f'<td valign="top" width="170">{esc(en)}</td>'
        imgs = []
        for item in items:
            alt = item[4] if len(item) > 4 else item[0]
            img = f'<img src="{RAW}badges/{slug_id(item[0])}.svg" alt="{esc(alt)}">'
            imgs.append(f'<a href="{esc(item[3])}">{img}</a>' if item[3] else img)
        rows.append(f'<tr>{label}<td valign="top" width="1012">\n' + "\n".join(imgs) + "\n</td></tr>")
    return "<table>\n" + "\n<tr></tr>\n".join(rows) + "\n</table>"


# ---------------------------------------------------------------- contact + README sync
def contact_svg(email):
    """One gradient capsule that reads on light and dark pages, so it can sit inside a mailto link."""
    w, h = round(text_w(email, 14) + 72), 42
    out = svg_open(w, h, email)
    out.append("<defs>" + gradient("pill", ACCENT) + "</defs>")
    out.append(f'<rect width="{w}" height="{h}" rx="21" fill="url(#pill)"/>')
    out.append(f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="20.5" fill="none" stroke="#FFFFFF" stroke-opacity=".18"/>')
    out.append(f'<g transform="translate(17,9)"><path d="{MAIL}" fill="#FFFFFF"/></g>')
    out.append(f'<text x="49" y="26" font-size="14" font-weight="700" fill="#FFFFFF">{esc(email)}</text>')
    out.append("</svg>")
    return "\n".join(out), w


def contact_block(lang, email, width):
    alt = f"{TEXT[lang]['email']}: {email}"
    return ('<p align="center">\n'
            f'<a href="mailto:{esc(email)}"><img src="{RAW}contact.svg" alt="{esc(alt)}" width="{width}"></a>\n'
            "</p>")


def replace_block(text, name, content):
    return re.sub(rf"(<!-- {name}:start -->\n).*?(<!-- {name}:end -->)",
                  lambda m: m.group(1) + (content + "\n" if content else "") + m.group(2), text, flags=re.S)


def sync_readme(root, email, width, owner):
    changed = False
    for lang, name in (("en", "README.md"), ("ko", "README.ko.md")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        new = replace_block(text, "stack", stack_block(lang))
        # Update on any address; remove the block only when the owner's token confirms there is none
        # (the default Actions token may not see the email at all).
        if email or (email == "" and owner):
            new = replace_block(new, "contact", contact_block(lang, email, width) if email else "")
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed = True
    print("README blocks", "updated" if changed else "unchanged")


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "out")
    (out / "badges").mkdir(parents=True, exist_ok=True)
    head, created, days = fetch()
    today = dt.datetime.now(dt.timezone.utc).date()
    current, longest = streaks(days)
    owner = os.environ.get("OWNER_TOKEN", "").lower() == "true"
    s = dict(total=sum(days.values()), current=current, longest=longest, repos=head["repos"]["totalCount"],
             public=head["publicRepos"]["totalCount"], contributed=head["contributedTo"]["totalCount"],
             year=sum(c for d, c in days.items() if d.startswith(str(today.year))),
             active=sum(1 for d, c in days.items() if c and dt.date.fromisoformat(d) > today - dt.timedelta(days=365)),
             created=created, owner=owner)
    for lang in TEXT:
        for theme in THEMES:
            (out / f"stats-{lang}-{theme}.svg").write_text(stats_svg(lang, theme, s), encoding="utf-8")
            (out / f"contrib-{lang}-{theme}.svg").write_text(contrib_svg(lang, theme, days, today), encoding="utf-8")
    slugs = sorted({i[1] for _, _, items in STACK for i in items if not i[1].startswith("#")})
    paths = {slug: icon_path(slug) for slug in slugs}
    for _, _, items in STACK:
        for item in items:
            alt = item[4] if len(item) > 4 else item[0]
            svg, _w = badge_svg(item[0], item[1], item[2], paths, alt)
            (out / "badges" / f"{slug_id(item[0])}.svg").write_text(svg, encoding="utf-8")
    email = public_email()
    width = 0
    if email:
        svg, width = contact_svg(email)
        (out / "contact.svg").write_text(svg, encoding="utf-8")
    if "--sync-readme" in sys.argv:
        sync_readme(Path("."), email, width, owner)
    print(json.dumps({k: v for k, v in s.items() if k != "created"} | {"email": email}))


if __name__ == "__main__":
    main()