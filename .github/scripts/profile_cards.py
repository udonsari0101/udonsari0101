"""Render the profile's visual cards as SVG and keep the contact email in sync.

    GH_TOKEN=... python .github/scripts/profile_cards.py OUT_DIR [--sync-readme]

Writes banner/stack/activity cards (en|ko x light|dark) and contact.svg.
With the owner's token (OWNER_TOKEN=true) repository counts include private
repositories; otherwise the cards show public numbers only. --sync-readme rewrites
the block between <!-- contact:start --> and <!-- contact:end --> in both READMEs
from the public email on the GitHub profile.
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
FONT = ("ui-rounded,'SF Pro Rounded','Segoe UI Variable Display','Segoe UI','Noto Sans KR',"
        "'Apple SD Gothic Neo','Malgun Gothic',Helvetica,Arial,sans-serif")
W = 846

THEMES = {
    "light": dict(card="#F7F8FC", stroke="#E3E6F0", text="#1F2328", muted="#6B7280", accent="#4F46E5",
                  grad=("#4F46E5", "#7C3AED", "#0E7490"), tile_alpha=0.15, empty="#E7E9F2",
                  levels=["#C7D2FE", "#A5B4FC", "#6366F1", "#4338CA"],
                  banner=("#EEF2FF", "#F5F3FF", "#ECFEFF"), blobs=("#A5B4FC", "#C4B5FD", "#67E8F9"),
                  pill="#FFFFFF", pill_alpha=0.72, pill_stroke="#FFFFFF"),
    "dark": dict(card="#141A24", stroke="#262E3D", text="#F0F6FC", muted="#9198A1", accent="#A5B4FC",
                 grad=("#A5B4FC", "#C4B5FD", "#67E8F9"), tile_alpha=0.22, empty="#1F2633",
                 levels=["#312E81", "#4338CA", "#6366F1", "#A5B4FC"],
                 banner=("#0B1020", "#1E1B4B", "#082F49"), blobs=("#4F46E5", "#7C3AED", "#0891B2"),
                 pill="#FFFFFF", pill_alpha=0.08, pill_stroke="#FFFFFF"),
}
TEXT = {
    "en": dict(interests=["Cybersecurity", "Software Engineering", "Autonomous Systems", "Computer Systems",
                          "Artificial Intelligence"],
               activity="GitHub activity", since="since {mon} {year}", heat="{n} contributions in the last year",
               less="Less", more="More", day="day", days="days", repos="", months=["Jan", "Feb", "Mar", "Apr", "May",
               "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], weekdays={1: "Mon", 3: "Wed", 5: "Fri"},
               metrics=dict(total="Total contributions", current="Current streak", longest="Longest streak",
                            repos="Repositories", public_repos="Public repositories", contributed="Contributed to",
                            year="This year", active="Active days (1y)"), public="{n} public",
               email="Email"),
    "ko": dict(interests=["사이버보안", "소프트웨어 공학", "자율 시스템", "컴퓨터 시스템", "인공지능"],
               activity="GitHub 활동", since="{year}년 {num}월부터", heat="최근 1년간 {n}회 기여",
               less="적음", more="많음", day="일", days="일", repos="개", months=[f"{m}월" for m in range(1, 13)],
               weekdays={1: "월", 3: "수", 5: "금"},
               metrics=dict(total="총 기여", current="현재 연속 기여", longest="최장 연속 기여", repos="레포지토리",
                            public_repos="공개 레포지토리", contributed="기여한 레포", year="올해 기여",
                            active="활동한 날(1년)"), public="공개 {n}개", email="이메일"),
}

# (EN title, KO title, [(label, simple-icons slug or None, brand hex, monogram/glyph)])
STACK = [
    ("Languages", "언어", [("Python", "python", "3776AB"), ("JavaScript", "javascript", "E2B714"),
        ("TypeScript", "typescript", "3178C6"), ("Kotlin", "kotlin", "7F52FF"), ("SQL", None, "336791", "SQL")]),
    ("Frontend · Backend", "프론트엔드·백엔드", [("React", "react", "149ECA"), ("HTML", "html5", "E34F26"),
        ("CSS", "css", "663399"), ("FastAPI", "fastapi", "009688"), ("Flask", "flask", "3B4252"),
        ("REST API", "openapiinitiative", "6BA539")]),
    ("Databases", "데이터베이스", [("PostgreSQL", "postgresql", "4169E1"), ("MySQL", "mysql", "4479A1"),
        ("SQLite", "sqlite", "0F80CC"), ("Firebase", "firebase", "F5A300"), ("Firestore", "firebase", "E8710A")]),
    ("Desktop · Android", "데스크톱·Android", [("PySide6 (Qt)", "qt", "41CD52"), ("Electron", "electron", "47848F"),
        ("Windows", None, "0078D4", "#window"), ("Jetpack Compose", "jetpackcompose", "4285F4"),
        ("Android SDK", "android", "34A853"), ("Gradle", "gradle", "02303A")]),
    ("DevOps · Cloud", "데브옵스·클라우드", [("Linux", "linux", "D9A300"), ("Docker", "docker", "2496ED"),
        ("Docker Compose", "docker", "1D63ED"), ("AWS", None, "FF9900", "aws"), ("GCP", "googlecloud", "4285F4"),
        ("GitHub Actions", "githubactions", "2088FF")]),
    ("Robotics", "로보틱스", [("ROS 2", "ros", "22314E"), ("Gazebo", None, "F58113", "Gz"), ("RViz", None, "5A6CF0", "RV")]),
    ("AI", "AI", [("Generative AI", None, "8B5CF6", "#sparkle"), ("Diffusion Models", None, "7C3AED", "#diffusion"),
        ("LLM Integration & Fine-tuning", None, "6D28D9", "LLM")]),
    ("Security Tools", "보안 도구", [("IDA Pro", None, "5B6B8C", "IDA"), ("Ghidra", None, "DC2626", "Gh"),
        ("JADX-GUI", None, "0EA5E9", "JX"), ("x64dbg", None, "475569", "x64"), ("Burp Suite", "burpsuite", "FF6633"),
        ("mitmproxy", None, "64748B", "mitm")]),
    ("Tools", "도구", [("Notion", "notion", "111111"), ("Figma", "figma", "F24E1E")]),
]
GLYPHS = {  # simple generic glyphs on a 24x24 grid
    "#window": "M3 3h8v8H3zM13 3h8v8h-8zM3 13h8v8H3zM13 13h8v8h-8z",
    "#sparkle": "M12 1.5l2.3 6.4 6.2 2.6-6.2 2.6L12 19.5l-2.3-6.4L3.5 10.5l6.2-2.6zM19 15.5l.9 2.4 2.3.9-2.3.9-.9 2.4-.9-2.4-2.3-.9 2.3-.9z",
    "#diffusion": "M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17zm0 3a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zm0 3a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z",
}
MAIL = "M3 6.5A2.5 2.5 0 0 1 5.5 4h13A2.5 2.5 0 0 1 21 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5zm2.2-.3 6.8 5.4 6.8-5.4z"


# ---------------------------------------------------------------- helpers
def esc(s):
    return html.escape(str(s), quote=True)


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexc(c):
    return "#" + "".join(f"{max(0, min(255, round(v))):02X}" for v in c)


def mix(a, b, t):
    a, b = rgb(a), rgb(b)
    return hexc(tuple(x + (y - x) * t for x, y in zip(a, b)))


def lum(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_w(s, size):
    return sum(size * (1.0 if ord(c) > 0x3000 else 0.3 if c in " .,'il|()" else 0.62 if c.isupper() else 0.55)
               for c in s)


def svg_open(w, h, title, extra_style=""):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">',
            f"<title>{esc(title)}</title>",
            f"<style>text{{font-family:{FONT}}}"
            ".pop{opacity:0;transform-box:fill-box;transform-origin:center;animation:pop .7s cubic-bezier(.34,1.56,.64,1) forwards}"
            "@keyframes pop{0%{opacity:0;transform:scale(.6)}100%{opacity:1;transform:scale(1)}}"
            ".fade{opacity:0;animation:fade .6s ease-out forwards}@keyframes fade{to{opacity:1}}"
            f"{extra_style}"
            "@media (prefers-reduced-motion:reduce){*{animation:none!important}.pop,.fade{opacity:1}}</style>"]


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
    except Exception as e:  # noqa: BLE001 — fall back to a monogram
        print(f"icon {slug} unavailable: {e}")
        return None


# ---------------------------------------------------------------- cards
def banner_svg(lang, theme):
    t, x = THEMES[theme], TEXT[lang]
    h = 168
    items = x["interests"]
    period = 2.6 * len(items)
    style = (".b1{animation:d1 16s ease-in-out infinite alternate}.b2{animation:d2 19s ease-in-out infinite alternate}"
             ".b3{animation:d3 13s ease-in-out infinite alternate}"
             "@keyframes d1{to{transform:translate(90px,24px)}}@keyframes d2{to{transform:translate(-110px,-18px)}}"
             "@keyframes d3{to{transform:translate(60px,-30px)}}"
             f".r{{opacity:0;animation:rot {period:.1f}s infinite}}"
             f"@keyframes rot{{0%{{opacity:0;transform:translateY(8px)}}{100 / len(items) * .18:.1f}%{{opacity:1;transform:none}}"
             f"{100 / len(items) * .82:.1f}%{{opacity:1;transform:none}}{100 / len(items):.1f}%{{opacity:0;transform:translateY(-8px)}}"
             "100%{opacity:0}}"
             "@media (prefers-reduced-motion:reduce){.r{opacity:0}.r0{opacity:1}}")
    out = svg_open(W, h, LOGIN, style)
    out.append("<defs>" + gradient("bg", t["banner"], "1", "1") + gradient("ink", t["grad"]) +
               '<filter id="blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="38"/></filter>'
               '<filter id="glow" x="-20%" y="-40%" width="140%" height="180%"><feGaussianBlur stdDeviation="10" result="g"/>'
               '<feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
               f'<clipPath id="clip"><rect width="{W}" height="{h}" rx="26"/></clipPath>'
               '<pattern id="dots" width="18" height="18" patternUnits="userSpaceOnUse">'
               f'<circle cx="2" cy="2" r="1.1" fill="{t["text"]}"/></pattern></defs>')
    out.append('<g clip-path="url(#clip)">')
    out.append(f'<rect width="{W}" height="{h}" fill="url(#bg)"/>')
    for cls, (cx, cy, r), color, op in zip(("b1", "b2", "b3"), ((150, 30, 130), (690, 150, 150), (430, -20, 110)),
                                            t["blobs"], (0.75, 0.65, 0.55) if theme == "light" else (0.55, 0.5, 0.45)):
        out.append(f'<circle class="{cls}" cx="{cx}" cy="{cy}" r="{r}" fill="{color}" opacity="{op}" filter="url(#blur)"/>')
    out.append(f'<rect width="{W}" height="{h}" fill="url(#dots)" opacity="{0.07 if theme == "light" else 0.06}"/>')
    out.append(f'<rect x=".5" y=".5" width="{W - 1}" height="{h - 1}" rx="26" fill="none" '
               f'stroke="{t["pill_stroke"]}" stroke-opacity="{0.6 if theme == "light" else 0.08}"/></g>')
    ink = 'fill="url(#ink)"' if theme == "light" else 'fill="#FFFFFF" filter="url(#glow)"'
    out.append(f'<text class="fade" x="{W / 2}" y="86" text-anchor="middle" font-size="58" font-weight="800" '
               f'letter-spacing="-1" {ink}>{LOGIN}</text>')
    pw = max(text_w(s, 16) for s in items) + 56
    px, py = (W - pw) / 2, 108
    out.append(f'<rect x="{px:.1f}" y="{py}" width="{pw:.1f}" height="34" rx="17" fill="{t["pill"]}" '
               f'fill-opacity="{t["pill_alpha"]}" stroke="{t["pill_stroke"]}" stroke-opacity="{0.9 if theme == "light" else 0.14}"/>')
    out.append(f'<circle cx="{px + 20:.1f}" cy="{py + 17}" r="4" fill="url(#ink)"/>')
    for i, s in enumerate(items):
        out.append(f'<text class="r r{i}" style="animation-delay:{i * 2.6:.1f}s" x="{W / 2 + 8:.1f}" y="{py + 22.5}" '
                   f'text-anchor="middle" font-size="16" font-weight="600" fill="{t["text"]}">{esc(s)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def stack_svg(lang, theme, paths):
    t = THEMES[theme]
    col_min, gap, pad, tile = 58, 2, 14, 46
    pods = []
    for en, ko, items in STACK:
        cols = []
        for item in items:
            label = item[0]
            words, lines = label.split(" "), [""]
            for w_ in words:
                trial = (lines[-1] + " " + w_).strip()
                if text_w(trial, 10.5) <= 70 or not lines[-1]:
                    lines[-1] = trial
                else:
                    lines.append(w_)
            cols.append((item, lines, max(col_min, max(text_w(l, 10.5) for l in lines) + 8)))
        title = ko if lang == "ko" else en
        natural = max(2 * pad + sum(c[2] for c in cols) + gap * (len(cols) - 1), text_w(title, 11) + 2 * pad + 20)
        lines_n = max(len(c[1]) for c in cols)
        pods.append(dict(title=title, cols=cols, w=natural, h=44 + tile + 10 + 13 * lines_n + 12))
    rows, left = [], list(pods)
    while left:  # first-fit: start each row with the next pod, then pull in later pods that still fit
        row = [left.pop(0)]
        used = row[0]["w"]
        for p in list(left):
            if used + 12 + p["w"] <= W:
                row.append(p)
                left.remove(p)
                used += 12 + p["w"]
        rows.append(row)
    total_h = sum(max(p["h"] for p in r) for r in rows) + 12 * (len(rows) - 1)
    title = ", ".join(i[0] for _, _, items in STACK for i in items)
    out = svg_open(W, total_h, title)
    y, k = 0, 0
    for r in rows:
        rh = max(p["h"] for p in r)
        extra = (W - sum(p["w"] for p in r) - 12 * (len(r) - 1)) / len(r)
        x = 0
        for p in r:
            pw = p["w"] + extra
            out.append(f'<rect x="{x + .5:.1f}" y="{y + .5}" width="{pw - 1:.1f}" height="{rh - 1}" rx="22" '
                       f'fill="{t["card"]}" stroke="{t["stroke"]}"/>')
            cw = text_w(p["title"], 11) + 22
            out.append(f'<rect x="{x + pad:.1f}" y="{y + 14}" width="{cw:.1f}" height="22" rx="11" fill="{t["accent"]}" '
                       f'fill-opacity="{0.12 if theme == "light" else 0.16}"/>')
            out.append(f'<text x="{x + pad + 11:.1f}" y="{y + 29}" font-size="11" font-weight="700" '
                       f'fill="{t["accent"]}">{esc(p["title"])}</text>')
            inner = sum(c[2] for c in p["cols"]) + gap * (len(p["cols"]) - 1)
            cx = x + (pw - inner) / 2
            for item, lines, cwid in p["cols"]:
                label, slug, brand = item[0], item[1], "#" + item[2]
                mark = item[3] if len(item) > 3 else None
                tile_bg = mix(t["card"], brand, t["tile_alpha"])
                ink = brand
                if theme == "dark" and lum(brand) < 0.06:  # near-black brands: neutral tile, light glyph
                    tile_bg, ink = mix(t["card"], "#FFFFFF", 0.09), "#E6EDF3"
                need = 3.0 if theme == "dark" else 2.6
                for _ in range(8):
                    if contrast(ink, tile_bg) >= need:
                        break
                    ink = mix(ink, "#FFFFFF" if theme == "dark" else "#000000", 0.18)
                tx, ty = cx + (cwid - tile) / 2, y + 44
                out.append(f'<g transform="translate({tx:.1f},{ty})"><g class="pop" style="animation-delay:{k * 0.035:.2f}s">')
                out.append(f'<rect width="{tile}" height="{tile}" rx="15" fill="{tile_bg}"/>')
                d = paths.get(slug) if slug else GLYPHS.get(mark)
                if d:
                    out.append(f'<path transform="translate(11,11)" d="{d}" fill="{ink}"/>')
                else:
                    fs = 15 if len(mark) <= 2 else 13 if len(mark) == 3 else 11
                    out.append(f'<text x="{tile / 2}" y="{tile / 2 + fs * .36:.1f}" text-anchor="middle" font-size="{fs}" '
                               f'font-weight="800" fill="{ink}">{esc(mark)}</text>')
                out.append("</g></g>")
                for li, line in enumerate(lines):
                    out.append(f'<text x="{cx + cwid / 2:.1f}" y="{ty + tile + 15 + li * 13}" text-anchor="middle" '
                               f'font-size="10.5" fill="{t["muted"]}">{esc(line)}</text>')
                cx += cwid + gap
                k += 1
            x += pw + 12
        y += rh + 12
    out.append("</svg>")
    return "\n".join(out)


def activity_svg(lang, theme, s, days, today):
    t, x = THEMES[theme], TEXT[lang]
    m = x["metrics"]
    unit = lambda n: x["day"] if n == 1 else x["days"]
    since = x["since"].format(mon=x["months"][s["created"].month - 1], year=s["created"].year, num=s["created"].month)
    metrics = [(f"{s['total']:,}", "", m["total"]), (str(s["current"]), unit(s["current"]), m["current"]),
               (str(s["longest"]), unit(s["longest"]), m["longest"])]
    if s["owner"]:
        metrics += [(str(s["repos"]), x["repos"], f"{m['repos']} · {x['public'].format(n=s['public'])}"),
                    (str(s["contributed"]), x["repos"], m["contributed"])]
    else:
        metrics += [(str(s["public"]), x["repos"], m["public_repos"]), (f"{s['year']:,}", "", m["year"])]
    metrics.append((str(s["active"]), unit(s["active"]), m["active"]))
    start = today - dt.timedelta(days=364 + (today.weekday() + 1) % 7)
    grid, d = [], start
    while d <= today:
        grid.append((d, days.get(d.isoformat(), 0)))
        d += dt.timedelta(days=1)
    counts = sorted(c for _, c in grid if c)
    q = lambda p: counts[min(len(counts) - 1, int(len(counts) * p))] if counts else 0
    cuts = [q(.25), q(.5), q(.75)]
    total_1y = sum(c for _, c in grid)
    weeks = (len(grid) + 6) // 7
    left, top = 52, 152
    pitch = (W - left - 28) / weeks
    r = pitch * 0.36
    h = top + 7 * pitch + 44
    out = svg_open(W, round(h), f"{x['activity']}: " + ", ".join(f"{a}{(' ' + b) if b else ''} {c}" for a, b, c in metrics))
    out.append("<defs>" + gradient("num", t["grad"]) +
               f'<clipPath id="k"><rect width="{W}" height="{h:.0f}" rx="24"/></clipPath></defs>')
    out.append(f'<rect x=".5" y=".5" width="{W - 1}" height="{h - 1:.0f}" rx="24" fill="{t["card"]}" stroke="{t["stroke"]}"/>')
    out.append(f'<circle cx="{W - 60}" cy="10" r="120" fill="{t["blobs"][1] if "blobs" in t else t["accent"]}" '
               f'opacity="{0.10 if theme == "light" else 0.12}" clip-path="url(#k)"/>')
    out.append(f'<text x="28" y="40" font-size="15" font-weight="800" fill="{t["text"]}">{esc(x["activity"])}</text>')
    sw = text_w(since, 11) + 22
    out.append(f'<rect x="{W - 28 - sw:.1f}" y="24" width="{sw:.1f}" height="22" rx="11" fill="{t["accent"]}" '
               f'fill-opacity="{0.12 if theme == "light" else 0.16}"/>')
    out.append(f'<text x="{W - 28 - sw / 2:.1f}" y="39" text-anchor="middle" font-size="11" font-weight="700" '
               f'fill="{t["accent"]}">{esc(since)}</text>')
    cw = (W - 56) / len(metrics)
    for i, (num, suffix, label) in enumerate(metrics):
        mx = 28 + i * cw
        tail = f'<tspan font-size="12" font-weight="700" fill="{t["muted"]}"> {esc(suffix)}</tspan>' if suffix else ""
        out.append(f'<g class="fade" style="animation-delay:{i * 0.07:.2f}s">'
                   f'<text x="{mx:.1f}" y="92" font-size="26" font-weight="800" fill="url(#num)">{esc(num)}{tail}</text>'
                   f'<text x="{mx:.1f}" y="112" font-size="11" fill="{t["muted"]}">{esc(label)}</text></g>')
    out.append(f'<line x1="28" y1="128" x2="{W - 28}" y2="128" stroke="{t["stroke"]}"/>')
    last = None
    for i, (day, count) in enumerate(grid):
        col, row = i // 7, (day.weekday() + 1) % 7
        cx, cy = left + col * pitch + pitch / 2, top + row * pitch + pitch / 2
        if row == 0 and day.month != last and day.day <= 7:
            out.append(f'<text x="{cx - r:.1f}" y="{top - 6}" font-size="10" fill="{t["muted"]}">{esc(x["months"][day.month - 1])}</text>')
            last = day.month
        lv = -1 if count == 0 else sum(count > c for c in cuts)
        fill = t["empty"] if lv < 0 else t["levels"][lv]
        out.append(f'<circle class="pop" style="animation-delay:{col * 0.012:.3f}s" cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
                   f'fill="{fill}"><title>{day.isoformat()}: {count}</title></circle>')
    for row, name in x["weekdays"].items():
        out.append(f'<text x="{left - 8}" y="{top + row * pitch + pitch / 2 + 3.5:.1f}" font-size="10" text-anchor="end" '
                   f'fill="{t["muted"]}">{esc(name)}</text>')
    fy = top + 7 * pitch + 24
    out.append(f'<text x="{left}" y="{fy:.1f}" font-size="11" fill="{t["muted"]}">{esc(x["heat"].format(n=f"{total_1y:,}"))}</text>')
    lx = W - 28 - 5 * (pitch) - text_w(x["more"], 10) - 6
    out.append(f'<text x="{lx - 6:.1f}" y="{fy:.1f}" font-size="10" text-anchor="end" fill="{t["muted"]}">{esc(x["less"])}</text>')
    for i, fill in enumerate([t["empty"]] + t["levels"]):
        out.append(f'<circle cx="{lx + i * pitch + r:.1f}" cy="{fy - 3.5:.1f}" r="{r:.1f}" fill="{fill}"/>')
    out.append(f'<text x="{lx + 5 * pitch + 4:.1f}" y="{fy:.1f}" font-size="10" fill="{t["muted"]}">{esc(x["more"])}</text>')
    out.append("</svg>")
    return "\n".join(out)


def contact_svg(email):
    """One gradient pill that reads on light and dark pages, so it can sit inside a mailto link."""
    w, h = round(text_w(email, 14) + 72), 42
    out = svg_open(w, h, email)
    out.append("<defs>" + gradient("pill", ("#4F46E5", "#7C3AED", "#0E7490")) + "</defs>")
    out.append(f'<rect width="{w}" height="{h}" rx="21" fill="url(#pill)"/>')
    out.append(f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="20.5" fill="none" stroke="#FFFFFF" stroke-opacity=".18"/>')
    out.append(f'<g transform="translate(17,9)"><path d="{MAIL}" fill="#FFFFFF"/></g>')
    out.append(f'<text x="49" y="26" font-size="14" font-weight="700" fill="#FFFFFF">{esc(email)}</text>')
    out.append("</svg>")
    return "\n".join(out), w


def contact_block(lang, email, width):
    if not email:
        return ""
    alt = f"{TEXT[lang]['email']}: {email}"
    return ('<p align="center">\n'
            f'<a href="mailto:{esc(email)}"><img src="{RAW}contact.svg" alt="{esc(alt)}" width="{width}"></a>\n'
            "</p>")


def sync_readme(root, email, width):
    changed = False
    for lang, name in (("en", "README.md"), ("ko", "README.ko.md")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        new = re.sub(r"(<!-- contact:start -->\n).*?(<!-- contact:end -->)",
                     lambda m: m.group(1) + (contact_block(lang, email, width) + "\n" if email else "") + m.group(2),
                     text, flags=re.S)
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed = True
    print("README contact block", "updated" if changed else "unchanged")


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "out")
    out.mkdir(parents=True, exist_ok=True)
    head, created, days = fetch()
    today = dt.datetime.now(dt.timezone.utc).date()
    current, longest = streaks(days)
    s = dict(total=sum(days.values()), current=current, longest=longest, repos=head["repos"]["totalCount"],
             public=head["publicRepos"]["totalCount"], contributed=head["contributedTo"]["totalCount"],
             year=sum(c for d, c in days.items() if d.startswith(str(today.year))),
             active=sum(1 for d, c in days.items() if c and dt.date.fromisoformat(d) > today - dt.timedelta(days=365)),
             created=created, owner=os.environ.get("OWNER_TOKEN", "").lower() == "true")
    slugs = {i[1] for _, _, items in STACK for i in items if i[1]}
    paths = {slug: icon_path(slug) for slug in sorted(slugs)}
    for lang in TEXT:
        for theme in THEMES:
            (out / f"banner-{lang}-{theme}.svg").write_text(banner_svg(lang, theme), encoding="utf-8")
            (out / f"stack-{lang}-{theme}.svg").write_text(stack_svg(lang, theme, paths), encoding="utf-8")
            (out / f"activity-{lang}-{theme}.svg").write_text(activity_svg(lang, theme, s, days, today), encoding="utf-8")
    email = public_email()
    width = 0
    if email:
        svg, width = contact_svg(email)
        (out / "contact.svg").write_text(svg, encoding="utf-8")
    # Update on any address; remove the block only when the owner's token confirms there is none
    # (the default Actions token may not see the email at all).
    if "--sync-readme" in sys.argv and email is not None and (email or s["owner"]):
        sync_readme(Path("."), email, width)
    print(json.dumps({k: v for k, v in s.items() if k != "created"} | {"email": email}))


if __name__ == "__main__":
    main()