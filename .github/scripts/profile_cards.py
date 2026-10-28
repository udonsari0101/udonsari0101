"""Render the profile's visual cards and badges as SVG and keep README blocks in sync.

    GH_TOKEN=... python .github/scripts/profile_cards.py OUT_DIR [--sync-readme]

Every block is drawn on one 832px column so edges line up: the hero, the
contribution calendar, eight stack cards drawn in pairs (416px images, 2 per row on
desktop and 1 on phones, where the pair scales down and its type steps up), and six
stat tiles drawn in threes (416px images, the same way). Images carry a 4px transparent margin,
so placed side by side with no whitespace they get an exact 8px gutter. Also writes
one capsule badge per linked technology (official-links drawer) and the contact pill.
With the owner's token (OWNER_TOKEN=true) repository counts include private
repositories; otherwise the tiles show public numbers. --sync-readme rewrites the
stack, activity, and contact blocks in both READMEs.
"""
import datetime as dt
import html
import json
import math
import os
import re
import sys
import urllib.request
from pathlib import Path

LOGIN = "udonsari0101"
RAW = f"https://raw.githubusercontent.com/{LOGIN}/{LOGIN}/profile-cards/"
ICONS = "https://cdn.jsdelivr.net/npm/simple-icons@15.17.0/icons/{}.svg"
FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI Variable Text','Segoe UI','Noto Sans KR',"
        "'Apple SD Gothic Neo','Malgun Gothic',Helvetica,Arial,sans-serif")
DISPLAY = "-apple-system,BlinkMacSystemFont,'Segoe UI Variable Display','Segoe UI','Noto Sans KR','Malgun Gothic',sans-serif"
ACCENT = ("#4F46E5", "#7C3AED", "#0E7490")
RAMP = ("#8B5CF6", "#6366F1", "#3B82F6", "#06B6D4")  # violet -> cyan, the page's one accent family
COL, GUT = 832, 8
CARD_W, TILE_W = COL / 4, COL / 6
PAIR_W = 2 * CARD_W
PAIR_SMALL = 400  # a pair or trio rendered narrower than this (phones) switches to larger type
# On phones an 832px image scales half as much as a 416px one, so its 4px margin shrinks to half.
# Scaling the card by (832 - 16) / (832 - 8) restores the pairs' edge.
PHONE_FRAME = f"{(COL - 2 * GUT) / (COL - GUT):.4f}"

THEMES = {
    "light": dict(surface="#FFFFFF", icon_bg="#F8F9FC", card=("#FFFFFF", 1), card2=("#F8F9FC", 1), border=("#E4E7EC", 1),
                  text="#1F2328", muted="#59636E", hero_muted="#4B5563", accent="#4F46E5", ink=("#111827", "#4F46E5"),
                  empty="#EBEEF3", levels=["#C7D2FE", "#818CF8", "#4F46E5", "#3730A3"], glow_a=.16,
                  hero="#FBFBFE", glow=(("#6366F1", .20), ("#06B6D4", .16), ("#A855F7", .14)), grid=("#0F172A", .05)),
    "dark": dict(surface="#161B22", icon_bg="#2B3239", card=("#FFFFFF", .045), card2=("#FFFFFF", .02), border=("#FFFFFF", .09),
                 text="#F0F6FC", muted="#A0A8B2", hero_muted="#A0A8B2", accent="#A5B4FC", ink=("#FFFFFF", "#C7D2FE"),
                 empty="#1E242C", levels=["#312E81", "#4338CA", "#6366F1", "#A5B4FC"], glow_a=.26,
                 hero="#090C13", glow=(("#4F46E5", .42), ("#0891B2", .30), ("#7C3AED", .30)), grid=("#FFFFFF", .045)),
}
TEXT = {
    "en": dict(focus="Interested in", interests=["Cybersecurity", "Software Engineering", "Autonomous Systems",
                                                  "Computer Systems", "Artificial Intelligence"],
               tiles=dict(total="All-time total", current="Current streak", longest="Longest streak",
                          repos="Repositories", public_repos="Public repos", contributed="Contributed to",
                          best="Most in one day", active="Active days · 1y"),
               # Fuller wording for alt text, which the tile's width doesn't limit.
               tile_alts=dict(total="All-time contributions", best="Most contributions in one day",
                              active="Active days in the last year", contributed="Repositories contributed to"),
               day="day", days="days", repos="", contribs="",
               heat="{n} contributions in the last year", less="Less", more="More",
               months=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
               weekdays={1: "Mon", 3: "Wed", 5: "Fri"}, email="Email",
               links="Official links", links_note="{n}&nbsp;links"),
    "ko": dict(focus="관심 분야", interests=["사이버보안", "소프트웨어 공학", "자율 시스템", "컴퓨터 시스템", "인공지능"],
               tiles=dict(total="누적 기여", current="현재 연속 기여", longest="최장 연속 기여", repos="저장소",
                          public_repos="공개 저장소", contributed="기여한 저장소", best="하루 최다 기여", active="최근 1년 활동일"),
               day="일", days="일", repos="개", contribs="회",
               heat="최근 1년간 {n}회 기여", less="적음", more="많음", months=[f"{m}월" for m in range(1, 13)],
               weekdays={1: "월", 3: "수", 5: "금"}, email="이메일",
               links="공식 링크", links_note="{n}개"),
}

# (EN title, KO title, group glyph, [(name, simple-icons slug | @logo | #glyph, brand hex, official link or None[, alt])])
STACK = [
    ("Languages", "언어", "#code", [
        ("Python", "python", "3776AB", "https://www.python.org"),
        ("JavaScript", "javascript", "D4B000", "https://developer.mozilla.org/en-US/docs/Web/JavaScript"),
        ("TypeScript", "typescript", "3178C6", "https://www.typescriptlang.org"),
        ("Kotlin", "kotlin", "7F52FF", "https://kotlinlang.org"),
        ("SQL", "#table", "336791", None)]),
    ("Frontend · Backend", "프론트엔드·백엔드", "#layers", [
        ("React", "react", "087EA4", "https://react.dev"),
        ("HTML", "html5", "E34F26", "https://html.spec.whatwg.org"),
        ("CSS", "css", "663399", "https://www.w3.org/Style/CSS/"),
        ("FastAPI", "fastapi", "009688", "https://fastapi.tiangolo.com"),
        ("Flask", "flask", "475569", "https://flask.palletsprojects.com"),
        ("REST API", "openapiinitiative", "4D7F2A", None)]),
    ("Databases", "데이터베이스", "#database", [
        ("PostgreSQL", "postgresql", "4169E1", "https://www.postgresql.org"),
        ("MySQL", "mysql", "4479A1", "https://www.mysql.com"),
        ("SQLite", "sqlite", "0F80CC", "https://www.sqlite.org"),
        ("Firebase", "firebase", "F59E0B", "https://firebase.google.com"),
        ("Firestore", "firebase", "EA580C", "https://firebase.google.com/docs/firestore")]),
    ("Desktop · Android", "데스크톱·Android", "#monitor", [
        ("PySide6 (Qt)", "qt", "2E9E4F", "https://doc.qt.io/qtforpython-6/"),
        ("Electron", "electron", "47848F", "https://www.electronjs.org", "Electron (Node.js)"),
        ("Windows", "#window", "0078D4", "https://learn.microsoft.com/windows/apps/"),
        ("Jetpack Compose", "jetpackcompose", "4285F4", "https://developer.android.com/compose"),
        ("Android SDK", "android", "34A853", "https://developer.android.com")]),
    ("DevOps · Cloud", "데브옵스·클라우드", "#infinity", [
        ("Linux", "linux", "C99700", "https://www.kernel.org"),
        ("Docker", "docker", "2496ED", "https://www.docker.com"),
        ("Docker Compose", "docker", "1D63ED", "https://docs.docker.com/compose/"),
        ("AWS", "#cloud", "FF9900", "https://aws.amazon.com"),
        ("GCP", "googlecloud", "4285F4", "https://cloud.google.com")]),
    ("Robotics · AI", "로보틱스·AI", "#bot", [
        ("ROS 2", "ros", "4A6CB3", "https://www.ros.org"),
        ("Gazebo", "#cube", "D97706", "https://gazebosim.org"),
        ("RViz", "#axes", "6366F1", "https://github.com/ros2/rviz"),
        ("Generative AI", "#sparkle", "8B5CF6", None),
        ("Diffusion Models", "#diffusion", "7C3AED", None),
        ("LLM Integration & Fine-tuning", "#chat", "6D28D9", None)]),
    ("Security", "보안", "#shield", [
        ("IDA Pro", "@ida", "64748B", "https://hex-rays.com/ida-pro"),
        ("Ghidra", "@ghidra", "E22726", "https://ghidra-sre.org"),
        ("JADX-GUI", "@jadx", "461BBC", "https://github.com/skylot/jadx"),
        ("x64dbg", "#bug", "64748B", "https://x64dbg.com"),
        ("Burp Suite", "burpsuite", "EA580C", "https://portswigger.net/burp"),
        ("mitmproxy", "@mitmproxy", "3F3F46", "https://mitmproxy.org")]),
    ("Tools", "도구", "#wrench", [
        ("Gradle", "gradle", "1F8A99", "https://gradle.org"),
        ("GitHub Actions", "githubactions", "2088FF", "https://github.com/features/actions"),
        ("Notion", "notion", "3F3F46", "https://www.notion.so"),
        ("Figma", "figma", "F24E1E", "https://www.figma.com")]),
]
ICON_CROP = {"mysql": (13.8, 2.3, 10.4)}  # show only the dolphin of the MySQL wordmark
# Logos the owner picked for tools that simple-icons doesn't carry: 64px PNG, trimmed to a square
# (mitmproxy's square avatar gets rounded corners), embedded so every SVG stays self-contained.
LOGOS = {
    "ida": (
        "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"),
    "ghidra": (
        "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"
        "TkSuQmCC"),
    "jadx": (
        "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAMAAACdt4HsAAAB/lBMVEVcWlrhpKDq29yeIlExH1/QTSmLb9UoKyqiRCepsrJtIVCijN1W"
        "p6OtYosbXI8MX1ZrMyMikoc1JJ2aysbIudiVk5OipaWdo6htcnFdN8bWX1ZzV8vPyMtkW15BH5iHOyQQY15YaKaRZ37LvcTLNzfzg16W"
        "aWk3DCLL0tJTMkn/v7+///8+DsMNRjucdYnNfqhyRDpDPj4A///9/f0AAADxWikBg3UjHiBFGronIiMYFRYBemydHmPq5+wiHBz///9H"
        "GsPX19ieIWTJyMmYFVs+G5t/f386C7gQDQ7xURzl3O/Hxsapp6hWU1O0U4ikHmbwSxW6uLmz2dXT6eVJGzPY19eqqKmFw73yYzQZHCBv"
        "uLEumI2/v7+sN3ZMR0nSyO5LI7tSKsL6x7fy2dA5NTaIhodrZ2r2poxSKCx3dnfa0vGqp6j2lHQkIBy6ubmkI2Y8ErebmZpsR8uXlpYZ"
        "Jyb1eE0dIR7zjG6UkpOHhobCwsIZODS2peQXR0O3trcFanAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAQIIdfAAAAgHRSTlMr/vb/////HP+v/////v///////v5TGP5R////vf///xX//5///xv/eRcEBP//Df//MQH+AP//////////"
        "/P8C//j/+v//Av////7Tlv/////+/P3/2P7//////wT////////9//7////+/27//5L//4//dP//////a5j////E/1ppz8UAAAaXSURB"
        "VHjajZf5Q9pIFMejqFiPam2tR2uv7bHde3cISQYSDEEDAhVEregWaRVPPOt9/uv73szkAMHu+6ENY95n3vGdzIwUumOTMfxX2r5Iz5kr"
        "um6ac+ndbQnHfpm8+7ZUPxBD98GLOZ3UmD63O+j89V7AvzC0O8d9rPmzyuZm5Wze4rS5zEf2wj0A4EsX+LY+v1nSKE1Syv7RSpt5HDZ3"
        "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"),
    "mitmproxy": (
        "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAMAAACdt4HsAAAB/lBMVEUBAAD9/f0AAADX19fm5+dVVVUWFhaoqaq2t7eWlpYnJyfHyMk3"
        "NzdHR0Z4d3WFhoZoaGjwWSgAAACSVAn+YiwAAAAAAADUegywZgvsiREAAABzRw/a3eK4vML8mBhwZFaLTAQtFghvOQBGKwpTNQ7/pSa+"
        "xMzc4ehWRTPOSyMuDAgAAAAyIhBoWUlnIhLGbANqSiWoOx1OPCaYnqR+UBp6WC+EZ0aaoKd+gomNMRj/oR6ZYBuHYDGIf3SNhHisWwC/"
        "dBRiHxJfYGDehg1YGxDhfgcfHyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AAAAAABd5/KgAAAAgHRSTlP+/wH////////////////////I//8xTP///5X/////////////////////Yv//////////////////////"
        "/////////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFwXUMAAAARPSURB"
        "VHjarVfZduMoEJUGECAkUKzYlrzETuwsnU7S+zb71v3/nzQgxCbwpM+ZqZfEAi5VdS9Fkf1gbLGaZd9ps9XCLsvGvy+/e/WI8TIAmKeW"
        "l0hQTAjGApUpiLkDmEejRUNA7hkkPAaZG4BoPSJ5wkiTQlAA0+VsXAEIFZzLOIwzgE+maoAw/krvDqgfeFkLDcJQmAcFsAg+ce0tipNW"
        "42GIBh8XEsB3oBi2J3WaunKAAFXgQuY7UCo/YXOa/XpIj4+/yFZe+FBtX/yrgKhC2FI7aZW5CEo1JgI1VDVCdRVANjnkOwzMNy8Bhdrf"
        "c7/ihs4cCM/rLe8urrYido4F660YrATMnjcfLq6/UhytF3KW1UltpAMBAHD8d0QnYv/XFYsyXcsp2AdTjuvoCxMMHn6WG8oZixyQWwLz"
        "vxZDFUhgyD4YxFkIHDPNPXrVdiDSUqU+w/IUvcAFwKyziSzBEypp5Fjp5ErTs5SbLD3ExkUF2dx6yUwhKF60sSKgYMgZwe9bnhdeVeO8"
        "8eLGgTYaX+CDawVYX1zs7Zk3hcmRXsCgRPkpHDT0wNofr9ubnZ7sbcdKW1mMqXAK7xRp1jHdtzud6WIQD8D4Jk/zJ51BjgNgCgrBowSU"
        "+9vHddvuHz8ppIg/7NgSXuKr2hFLj/3vbdv1VzxFrXBJwJMyYJR1dXG4f3q6vOz3n61OvOLtxM+COmCJvesf/jiX9iXrj8A7qsZXmRm3"
        "G4r9w/vu/vxM2vnf6074pFkAQwPw9aVNplh0xy8DwNmLw1KlZDIFuLBA6iLLxavDmxHgYblLTnkGoFs/6RDeHJY8DeBCoCg0Ke6b9TI7"
        "Uwjn9137Tt1WoXF3uEnMghInWrbZCxnA/bF/C+M8eyzghEwk6ObYd5fS2v6wTZSSxhWHBEcDSeyuXUrr3hJ7dgVjplpRp986VaqGtNHd"
        "69ePn6Gt2BR8/JkSKz/hnXKUFYkSKJF1BcDjxA+9vJVqk6Xar+PQmI0GWXrhKOPq9idZLz6hMQVw0lXElYoTuT9k9lbLwK9td7cpx01x"
        "eC9H+tJDpRdaAfJ3dNOYJHt3R1kZq5PFwwuVVoYDkJ6E7BUW9Y7E9Q9lHp/v4AJKdEnD3Yad9mA848/K8UcnYRQ899ajlAOYYUBtPbTB"
        "ao8F9Fs8JZzojhNkvXx/q12vgGk2a5lXJHR7AJGfzGoKsP3YXy9/MSriMDr7LiiazCDhr65/o9S160GZ2YgyyHLi/kXwbr0LTmXVYKC0"
        "DQivJp1iUinN7ca/BY0nRUJMwfqZ11biZzrdsX3zGgO5fBU1svhkI1QM40EzvMoWUa8jE56WsqYmvAUX2fS9MbaEaBp7TYflk/ZtFj04"
        "pBNaAhDzujRdRUNHUqeX8CJ+8qhG0pUiJs39ikKbJR9dygsSK9ErTJNHV+LZKN1AlEHnCG6+JSbNTz88TfCoaVBdnqhQ82eevs+9nuf/"
        "5+P7Pzz//wH65jsFjDTiggAAAABJRU5ErkJggg=="),
}


def ring(cx, cy, r):
    return f"M{cx - r} {cy}a{r} {r} 0 1 0 {2 * r} 0a{r} {r} 0 1 0 {-2 * r} 0z"


# Generic glyphs on a 24x24 grid: (fill paths, stroke paths).
GLYPHS = {
    "#database": ([], ["M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z",
                       "M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6", "M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"]),
    "#table": ([], ["M4.5 4h15A1.5 1.5 0 0 1 21 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5v-13A1.5 1.5 0 0 1 4.5 4z",
                    "M3 9.5h18", "M3 14.5h18", "M9.5 9.5V20"]),
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
    "#bug": ([], ["M12 7.5a4.5 4.5 0 0 1 4.5 4.5v3a4.5 4.5 0 0 1-9 0v-3A4.5 4.5 0 0 1 12 7.5z", "M12 11v8",
                  "M7.5 12.5H3.5", "M7.6 16.5 4.5 18", "M16.5 12.5h4", "M16.4 16.5l3.1 1.5",
                  "M9.5 8.3 7.5 5.5", "M14.5 8.3l2-2.8"]),
    "#code": ([], ["M8 7 3 12l5 5", "M16 7l5 5-5 5", "M13.5 4.5l-3 15"]),
    "#layers": ([], ["M12 3 21 8l-9 5-9-5z", "M3 12.5l9 5 9-5", "M3 16.5l9 5 9-5"]),
    "#monitor": ([], ["M4 4.5h16a1.5 1.5 0 0 1 1.5 1.5v9.5a1.5 1.5 0 0 1-1.5 1.5H4a1.5 1.5 0 0 1-1.5-1.5V6A1.5 1.5 0 0 1 4 4.5z",
                      "M9 21h6", "M12 17v4"]),
    "#infinity": ([], ["M12 12c-1.8-2.4-3.3-4-5.5-4a4 4 0 0 0 0 8c2.2 0 3.7-1.6 5.5-4zm0 0c1.8 2.4 3.3 4 5.5 4a4 4 0 0 0 0-8c-2.2 0-3.7 1.6-5.5 4z"]),
    "#bot": ([ring(9, 14, 1.3), ring(15, 14, 1.3), ring(12, 3.5, 1.3)],
             ["M7 8h10a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3z", "M12 4.8V8", "M2 13v3", "M22 13v3"]),
    "#shield": ([], ["M12 2.5 20 5.5v6c0 5-3.4 8.6-8 10-4.6-1.4-8-5-8-10v-6z", "M8.5 12l2.4 2.4 4.6-4.8"]),
    "#wrench": ([], ["M14.7 6.3a4 4 0 0 0-5.4 5.4L3.5 17.5l3 3 5.8-5.8a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"]),
    "#flame": ([], ["M12 21c-3.9 0-7-2.8-7-6.6 0-4.4 4.2-6.6 4.6-11.4 2.8 1.9 4.4 4.6 4.6 7.4.9-.8 1.5-2 1.6-3.4 1.4 1.5 3.2 3.9 3.2 7.4 0 3.8-3.1 6.6-7 6.6z"]),
    "#trophy": ([], ["M7 4h10v5a5 5 0 0 1-10 0z", "M7 6H4v1.5A3.5 3.5 0 0 0 7.5 11", "M17 6h3v1.5a3.5 3.5 0 0 1-3.5 3.5",
                     "M12 14v3.5", "M8.5 20.5h7", "M9.5 17.5h5v3h-5z"]),
    "#pulse": ([], ["M3 12h4l2.5-6 4.5 13 2.5-7H21"]),
    "#repo": ([], ["M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5z", "M5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3",
                   "M9 7h6"]),
    "#branch": ([ring(6, 5, 2), ring(6, 19, 2), ring(18, 8, 2)], ["M6 7v10", "M18 10c0 4-6 3.5-11.2 7.5"]),
    "#bolt": ([], ["M13 2.5 4.5 13.5H11L10 21.5l8.5-11H12z"]),
    "#calendar": ([], ["M5 5h14a1.5 1.5 0 0 1 1.5 1.5v12A1.5 1.5 0 0 1 19 20H5a1.5 1.5 0 0 1-1.5-1.5v-12A1.5 1.5 0 0 1 5 5z",
                       "M3.5 10h17", "M8 3v4", "M16 3v4", "M8 14h2", "M14 14h2"]),
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


def chroma(h):
    r, g, b = rgb(h)
    return (max(r, g, b) - min(r, g, b)) / 255


def readable(color, bg, need):
    """Nudge a brand colour toward white (dark bg) or black (light bg) until it reads on bg."""
    target = "#FFFFFF" if lum(bg) < 0.2 else "#000000"
    for _ in range(12):
        if contrast(color, bg) >= need:
            break
        color = mix(color, target, 0.15)
    return color


def ramp(u):
    k = min(int(u * (len(RAMP) - 1)), len(RAMP) - 2)
    return mix(RAMP[k], RAMP[k + 1], u * (len(RAMP) - 1) - k)


# Advance widths in 1/1000 em for ASCII 32-126 and · – —: the wider of Segoe UI and Arial (Helvetica
# metrics), so boxes sized from them fit the type on Windows, macOS, and Linux. Hangul counts 1 em.
ADV_CHARS = "".join(chr(i) for i in range(32, 127)) + "·–—"
ADV = {
    False: dict(zip(ADV_CHARS, (
        278, 284, 392, 591, 556, 889, 800, 230, 333, 333, 417, 684, 278, 400, 278, 390, 556, 556, 556, 556, 556, 556,
        556, 556, 556, 556, 278, 278, 684, 684, 684, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667,
        556, 898, 748, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 302, 379, 302, 684, 556, 333, 556,
        588, 500, 589, 556, 313, 589, 566, 242, 242, 500, 242, 861, 566, 586, 588, 589, 348, 500, 339, 566, 500, 723,
        500, 500, 500, 334, 260, 334, 684, 333, 556, 1000))),
    True: dict(zip(ADV_CHARS, (
        278, 333, 493, 592, 575, 889, 850, 293, 369, 369, 455, 707, 278, 404, 278, 443, 575, 575, 575, 575, 575, 575,
        575, 575, 575, 575, 333, 333, 707, 707, 707, 611, 975, 722, 722, 722, 737, 667, 611, 778, 766, 317, 556, 722,
        611, 957, 790, 778, 667, 778, 722, 667, 611, 723, 667, 1005, 667, 667, 611, 369, 436, 369, 707, 556, 333, 556,
        620, 556, 619, 556, 383, 619, 611, 284, 284, 559, 284, 916, 611, 611, 620, 619, 398, 556, 389, 611, 556, 797,
        556, 556, 500, 389, 326, 389, 707, 333, 556, 1000))),
}


def text_w(s, size, bold=False):
    adv = ADV[bold]
    return sum(size * (adv[c] / 1000 if c in adv else 1.0 if ord(c) > 0x3000 else 0.6) for c in s)


def slug_id(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def svg_open(w, h, title, style=""):
    # Animations only ever start from a hidden state ("both" + from-keyframes), so the content is
    # visible in renderers that don't run them; prefers-reduced-motion switches them off.
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}" height="{h:g}" viewBox="0 0 {w:g} {h:g}" role="img">',
            f"<title>{esc(title)}</title>",
            f"<style>text{{font-family:{FONT}}}.d{{font-family:{DISPLAY}}}"
            ".in{animation:in .7s ease-out both}@keyframes in{from{opacity:0}}"
            ".up{animation:up .7s cubic-bezier(.2,.8,.2,1) both}@keyframes up{from{opacity:0;transform:translateY(6px)}}"
            f"{style}@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}</style>"]


def gradient(gid, colors, x1="0", y1="0", x2="1", y2="0"):
    stops = "".join(f'<stop offset="{i / (len(colors) - 1):.2f}" stop-color="{c}"/>' for i, c in enumerate(colors))
    return f'<linearGradient id="{gid}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">{stops}</linearGradient>'


def glyph(icon, paths, color, x, y, size, stroke=2.0):
    if icon.startswith("@"):
        return (f'<image x="{x:.1f}" y="{y:.1f}" width="{size}" height="{size}" '
                f'href="data:image/png;base64,{LOGOS[icon[1:]]}"/>')
    if icon.startswith("#"):
        fills, strokes = GLYPHS[icon]
        body = "".join(f'<path d="{d}" fill="{color}"/>' for d in fills)
        body += "".join(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
                        f'stroke-linejoin="round"/>' for d in strokes)
        return f'<g transform="translate({x:.1f},{y:.1f}) scale({size / 24:.4f})">{body}</g>'
    d = paths.get(icon)
    if not d:
        return f'<circle cx="{x + size / 2:.1f}" cy="{y + size / 2:.1f}" r="{size / 5:.1f}" fill="{color}"/>'
    if icon in ICON_CROP:
        cx, cy, cs = ICON_CROP[icon]
        return (f'<svg x="{x:.1f}" y="{y:.1f}" width="{size}" height="{size}" viewBox="{cx} {cy} {cs} {cs}">'
                f'<path d="{d}" fill="{color}" stroke="{color}" stroke-width=".45" stroke-linejoin="round"/></svg>')
    return f'<g transform="translate({x:.1f},{y:.1f}) scale({size / 24:.4f})"><path d="{d}" fill="{color}"/></g>'


def backdrop(t, accent, x, y, w, h):
    """The card colour under (x, y): icon_bg tinted by card()'s corner glow, which fades out at distance 1."""
    return mix(t["icon_bg"], accent, t["glow_a"] * max(0.0, 1 - math.hypot(x / w, y / h)))


def card(w, h, t, rx, glow, uid=""):
    """A rounded surface: a soft vertical gradient (translucent on dark pages), a hairline border, a corner glow."""
    (c1, a1), (c2, a2), (bc, ba) = t["card"], t["card2"], t["border"]
    return [f'<defs><linearGradient id="cg{uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c1}" stop-opacity="{a1}"/>'
            f'<stop offset="1" stop-color="{c2}" stop-opacity="{a2}"/></linearGradient>'
            f'<clipPath id="cc{uid}"><rect width="{w:g}" height="{h:g}" rx="{rx}"/></clipPath>'
            f'<radialGradient id="glow{uid}" cx="0" cy="0" r="1"><stop offset="0" stop-color="{glow}" stop-opacity="{t["glow_a"]}"/>'
            f'<stop offset="1" stop-color="{glow}" stop-opacity="0"/></radialGradient></defs>',
            f'<rect width="{w:g}" height="{h:g}" rx="{rx}" fill="url(#cg{uid})"/>',
            f'<rect width="{w:g}" height="{h:g}" fill="url(#glow{uid})" clip-path="url(#cc{uid})"/>',
            f'<rect x=".5" y=".5" width="{w - 1:g}" height="{h - 1:g}" rx="{rx - .5}" fill="none" stroke="{bc}" stroke-opacity="{ba}"/>']


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
    except Exception as e:  # noqa: BLE001 — falls back to a dot
        print(f"icon {slug} unavailable: {e}")
        return None


# ---------------------------------------------------------------- hero
def hero_svg(lang, theme):
    t, x = THEMES[theme], TEXT[lang]
    w, h, iw = COL, 180, COL - GUT
    items = x["interests"]
    period, share = 2.8 * len(items), 100 / len(items)
    style = (f".r{{opacity:0;animation:rot {period:.1f}s infinite both}}.r0{{opacity:1}}"
             f"@keyframes rot{{0%{{opacity:0;transform:translateY(6px)}}{share * .14:.1f}%{{opacity:1;transform:none}}"
             f"{share * .86:.1f}%{{opacity:1;transform:none}}{share:.1f}%{{opacity:0;transform:translateY(-6px)}}100%{{opacity:0}}}}"
             ".pulse{animation:pulse 3.2s ease-in-out infinite}@keyframes pulse{50%{opacity:.55}}"
             ".txt{transform-origin:44px 112px}"
             # SMIL ignores prefers-reduced-motion, so the moving dots give way to resting ones there.
             ".st{display:none}@media (prefers-reduced-motion:reduce){.mv{display:none}.st{display:inline}}"
             "@media (max-width:520px){.orb{display:none}.txt{transform:scale(1.75)}}"
             f"@media (max-width:416px){{.frame{{transform-origin:{COL / 2:g}px {h / 2:g}px;transform:scale({PHONE_FRAME})}}}}")
    out = svg_open(w, h, f"{LOGIN} · {x['focus']}{': ' if lang == 'ko' else ' '}" + ", ".join(items), style)
    glows = "".join(
        f'<radialGradient id="g{i}" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="{c}" stop-opacity="{a}"/>'
        f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>' for i, (c, a) in enumerate(t["glow"]))
    out.append("<defs>" + glows + gradient("ink", t["ink"], "0", "0", "1", "1") + gradient("acc", ACCENT) +
               '<radialGradient id="fade" cx=".38" cy=".5" r=".75"><stop offset="0" stop-color="#FFFFFF"/>'
               '<stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></radialGradient>'
               f'<mask id="gm"><rect width="{w}" height="{h}" fill="url(#fade)"/></mask>'
               '<pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse">'
               f'<path d="M28 0H0V28" fill="none" stroke="{t["grid"][0]}" stroke-opacity="{t["grid"][1]}"/></pattern>'
               '<radialGradient id="core" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".95"/>'
               f'<stop offset=".25" stop-color="{ACCENT[1]}" stop-opacity=".7"/><stop offset="1" stop-color="{ACCENT[0]}" stop-opacity="0"/></radialGradient>'
               f'<clipPath id="hc"><rect x="4" width="{iw}" height="{h}" rx="24"/></clipPath></defs>')
    out.append('<g class="frame"><g clip-path="url(#hc)">')
    out.append(f'<rect x="4" width="{iw}" height="{h}" fill="{t["hero"]}"/>')
    for i, (cx, cy, r) in enumerate(((150, -10, 300), (780, 220, 280), (560, 40, 220))):
        out.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#g{i})"/>')
    out.append(f'<rect width="{w}" height="{h}" fill="url(#grid)" mask="url(#gm)"/>')
    ox, oy = 4 + iw - 152, 90
    out.append(f'<g class="orb"><g transform="translate({ox},{oy}) rotate(-16)">')
    for rr, dot, op, dur, sweep, rest in ((112, 3.4, .30, 26, 1, 40), (78, 3.0, .38, 18, 0, 205), (46, 2.6, .5, 12, 1, 300)):
        ry = rr * .38
        orbit = f"M{rr} 0A{rr} {ry:.1f} 0 1 {sweep} {-rr} 0A{rr} {ry:.1f} 0 1 {sweep} {rr} 0"
        out.append(f'<ellipse rx="{rr}" ry="{ry:.1f}" fill="none" stroke="url(#acc)" stroke-opacity="{op}" stroke-width="1.4"/>')
        out.append(f'<circle class="mv" r="{dot}" fill="{t["accent"]}"><animateMotion dur="{dur}s" repeatCount="indefinite" path="{orbit}"/></circle>')
        a = math.radians(rest)
        out.append(f'<circle class="st" cx="{rr * math.cos(a):.1f}" cy="{ry * math.sin(a):.1f}" r="{dot}" fill="{t["accent"]}"/>')
    out.append("</g>")
    out.append(f'<circle class="pulse" cx="{ox}" cy="{oy}" r="28" fill="url(#core)"/></g>')
    out.append("</g>")
    out.append(f'<rect x="4.5" y=".5" width="{iw - 1}" height="{h - 1}" rx="23.5" fill="none" stroke="{t["border"][0]}" '
               f'stroke-opacity="{t["border"][1]}"/>')
    out.append('<g class="txt">')
    out.append(f'<text class="up d" x="42" y="98" font-size="36" font-weight="700" letter-spacing="-1" fill="url(#ink)">{LOGIN}</text>')
    out.append(f'<text class="in" x="44" y="132" font-size="16" fill="{t["hero_muted"]}">{esc(x["focus"])}</text>')
    for i, s in enumerate(items):
        out.append(f'<text class="r r{i}" style="animation-delay:{i * 2.8:.1f}s" x="44" y="132" font-size="16">'
                   f'<tspan fill-opacity="0">{esc(x["focus"])}</tspan>'
                   f'<tspan dx="8" font-weight="600" fill="{t["accent"]}">{esc(s)}</tspan></text>')
    out.append("</g></g></svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- stack cards
CARD_INNER = CARD_W - GUT
CARD_TOP, ROW = 52, 24
LABEL_W = CARD_INNER - 16 - 24 - 12


def wrap(label, width, size):
    words, lines = label.split(" "), [""]
    for w_ in words:
        trial = (lines[-1] + " " + w_).strip()
        if text_w(trial, size) <= width or not lines[-1]:
            lines[-1] = trial
        else:
            lines.append(w_)
    return lines


ITEM, ITEM_SMALL = 12.5, 14  # item type on desktop; phones show a pair at about 0.7x, so it steps up


def card_height(items):
    extra = sum(len(wrap(i[0], LABEL_W, ITEM_SMALL)) - 1 for i in items)
    return CARD_TOP + 6 + len(items) * ROW + 15 * extra + 10


def pair_height(p):
    """The two pairs on one desktop row (four cards) share the tallest card's height."""
    row = 4 * (p // 2)
    return max(card_height(STACK[n][3]) for n in range(row, min(row + 4, len(STACK)))) + 3


def title_small(lang):
    titles = [g[1] if lang == "ko" else g[0] for g in STACK]
    return round(min([14.5] + [(CARD_INNER - 50 - 12) / text_w(s, 1, bold=True) for s in titles]), 1)


def group_alt(lang, n):
    en, ko, _, items = STACK[n]
    return f"{ko if lang == 'ko' else en}: " + ", ".join(i[4] if len(i) > 4 else i[0] for i in items)


def stack_card(lang, theme, n, paths, height, uid):
    t = THEMES[theme]
    en, ko, gicon, items = STACK[n]
    title = ko if lang == "ko" else en
    accent = ramp(n / (len(STACK) - 1))
    out = card(CARD_INNER, height, t, 20, accent, uid)
    chip = .14 if theme == "light" else .22
    on_chip = mix(backdrop(t, accent, 29, 29, CARD_INNER, height), accent, chip)
    out.append(f'<rect x="16" y="16" width="26" height="26" rx="8" fill="{accent}" fill-opacity="{chip}"/>')
    out.append(glyph(gicon, paths, readable(accent, on_chip, 3.0), 21, 21, 16, 2.2))
    out.append(f'<text class="tt" x="50" y="34" font-size="13" font-weight="700" fill="{t["text"]}">{esc(title)}</text>')
    y = CARD_TOP + 6
    for k, item in enumerate(items):
        name, icon, brand = item[0], item[1], "#" + item[2]
        bg = backdrop(t, accent, 23, y + 6, CARD_INNER, height)
        if icon.startswith("#"):
            color = readable(accent, bg, 3.0)
        elif chroma(brand) < .2:
            color = t["text"]
        else:
            color = readable(brand, bg, 2.6 if theme == "light" else 3.0)
        lines = wrap(name, LABEL_W, ITEM_SMALL)
        out.append(f'<g class="up" style="animation-delay:{.05 * k:.2f}s">')
        out.append(glyph(icon, paths, color, 16, y - 1, 15, 2.4))
        for li, line in enumerate(lines):
            out.append(f'<text class="it" x="40" y="{y + 11.5 + li * 15:.1f}" font-size="{ITEM}" fill="{t["text"]}">{esc(line)}</text>')
        out.append("</g>")
        y += ROW + 15 * (len(lines) - 1)
    return out


def stack_pair_svg(lang, theme, p, paths):
    """Two cards in one image: next to the other pair of its row on desktop, alone and scaled down on phones."""
    height = pair_height(p)
    style = f"@media (max-width:{PAIR_SMALL}px){{.it{{font-size:{ITEM_SMALL}px}}.tt{{font-size:{title_small(lang)}px}}}}"
    out = svg_open(PAIR_W, height, "; ".join(group_alt(lang, n) for n in (2 * p, 2 * p + 1)), style)
    for k, n in enumerate((2 * p, 2 * p + 1)):
        out.append(f'<g transform="translate({4 + k * CARD_W:g},1)">')
        out += stack_card(lang, theme, n, paths, height - 3, k)
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)

# ---------------------------------------------------------------- stat tiles
TILE_H = 104
TRIO_W = 3 * TILE_W


def tile(theme, glyph_name, value, unit, label, accent, uid, iw):
    t = THEMES[theme]
    ih = TILE_H - 3
    out = card(iw, ih, t, 18, accent, uid)
    ink = (ACCENT[0], ACCENT[2]) if theme == "light" else ("#C7D2FE", "#FFFFFF")
    out.append("<defs>" + gradient(f"num{uid}", ink, "0", "0", "1", "1") + "</defs>")
    out.append(glyph(glyph_name, {}, readable(accent, backdrop(t, accent, 21, 21, iw, ih), 3.0), 13, 13, 16, 2.1))
    tail = f'<tspan class="un" font-size="11.5" font-weight="600" fill="{t["muted"]}"> {esc(unit)}</tspan>' if unit else ""
    out.append(f'<text class="up d" x="13" y="64" font-size="25" font-weight="800" letter-spacing="-.5" fill="url(#num{uid})">{esc(value)}{tail}</text>')
    size = 10.5 if text_w(label, 10.5) <= iw - 26 else 10
    out.append(f'<text class="lb" x="13" y="85" font-size="{size}" fill="{t["muted"]}">{esc(label)}</text>')
    return out


def label_small(rows):
    """Label size on phones: up to 14px while every label still fits its narrowest tile."""
    room = math.floor(TILE_W - GUT) - 26
    return round(min([14] + [room / text_w(r[4], 1) for r in rows]), 1)


def tile_trio_svg(theme, rows, k):
    """Three tiles in one image: six across with the other trio on desktop, three across on phones."""
    trio, small = rows[3 * k:3 * k + 3], label_small(rows)
    style = f"@media (max-width:{PAIR_SMALL}px){{.lb{{font-size:{small}px}}.un{{font-size:{min(small + 1, 14):g}px}}}}"
    out = svg_open(TRIO_W, TILE_H, "; ".join(f"{r[4]}: {r[2]}{(' ' + r[3]) if r[3] else ''}" for r in trio), style)
    for j, (_key, g, value, unit, label, _alt, accent) in enumerate(trio):
        # Whole-unit edges (131/130/131 wide, 8px gutters) keep the hairline borders crisp on 1x screens.
        x0, x1 = round(4 + j * TILE_W), round(4 + (j + 1) * TILE_W - GUT)
        out.append(f'<g transform="translate({x0},1)">')
        out += tile(theme, g, value, unit, label, accent, j, x1 - x0)
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


def tiles(s, lang):
    x = TEXT[lang]
    m, alts = x["tiles"], x.get("tile_alts", {})
    unit = lambda n: x["day"] if n == 1 else x["days"]
    rows = [("total", "#pulse", f"{s['total']:,}", x["contribs"], "total"),
            ("current", "#flame", str(s["current"]), unit(s["current"]), "current"),
            ("longest", "#trophy", str(s["longest"]), unit(s["longest"]), "longest")]
    if s["owner"]:
        rows += [("repos", "#repo", str(s["repos"]), x["repos"], "repos"),
                 ("contributed", "#branch", str(s["contributed"]), x["repos"], "contributed")]
    else:  # the default Actions token sees public data only; don't show private-dependent zeros
        rows += [("repos", "#repo", str(s["public"]), x["repos"], "public_repos"),
                 ("contributed", "#bolt", f"{s['best']:,}", x["contribs"], "best")]
    rows.append(("active", "#calendar", str(s["active"]), unit(s["active"]), "active"))
    return [(key, g, value, u, m[name], alts.get(name, m[name]), ramp(i / (len(rows) - 1)))
            for i, (key, g, value, u, name) in enumerate(rows)]


# ---------------------------------------------------------------- contribution calendar
def level(n, cuts):
    return -1 if n == 0 else sum(n > c for c in cuts)


def contrib_svg(lang, theme, days, today):
    t, x = THEMES[theme], TEXT[lang]
    start = today - dt.timedelta(days=364 + (today.weekday() + 1) % 7)  # begin on a Sunday
    grid, d = [], start
    while d <= today:
        grid.append((d, days.get(d.isoformat(), 0)))
        d += dt.timedelta(days=1)
    counts = sorted(c for _, c in grid if c)
    q = lambda p: counts[min(len(counts) - 1, int(len(counts) * p))] if counts else 0
    cuts = [q(0.25), q(0.5), q(0.75)]
    total = sum(c for _, c in grid)
    weeks = (len(grid) + 6) // 7
    iw = COL - GUT
    left, top, right = 44, 58, 24
    pitch = (iw - left - right) / weeks
    cell = pitch * .8
    h = round(top + 7 * pitch + 22)
    title = x["heat"].format(n=f"{total:,}")
    shift = (left - (right + pitch - cell)) / 2  # centres the grid once the weekday labels are hidden
    out = svg_open(COL, h + 3, title, ".c{animation:in .5s ease-out both}"
                   "@media (max-width:520px){.lab{display:none}.ttl{font-size:28px;transform:translateY(6px)}"
                   f".cells{{transform:translateX({-shift:.1f}px)}}}}"
                   f"@media (max-width:416px){{.frame{{transform-origin:{COL / 2:g}px {(h + 3) / 2:g}px;transform:scale({PHONE_FRAME})}}}}")
    out.append('<g class="frame"><g transform="translate(4,1)">')
    out += card(iw, h, t, 20, ACCENT[0])
    out.append(f'<text class="ttl" x="24" y="36" font-size="13" font-weight="700" fill="{t["text"]}">{esc(title)}</text>')
    lx = iw - right - 5 * pitch - text_w(x["more"], 10) - 6
    legend = [f'<text x="{lx - 6:.1f}" y="33" font-size="10" text-anchor="end" fill="{t["muted"]}">{esc(x["less"])}</text>']
    legend += [f'<rect x="{lx + i * pitch:.1f}" y="24.5" width="{cell:.1f}" height="{cell:.1f}" rx="2.5" fill="{f}"/>'
               for i, f in enumerate([t["empty"]] + t["levels"])]
    legend.append(f'<text x="{lx + 5 * pitch + 4:.1f}" y="33" font-size="10" fill="{t["muted"]}">{esc(x["more"])}</text>')
    out.append('<g class="lab">' + "".join(legend))
    last = None
    for i, (day, _) in enumerate(grid):
        col, row = i // 7, (day.weekday() + 1) % 7
        if row == 0 and day.month != last and day.day <= 7:
            out.append(f'<text x="{left + col * pitch:.1f}" y="{top - 7}" font-size="10" fill="{t["muted"]}">{esc(x["months"][day.month - 1])}</text>')
            last = day.month
    for row, name in x["weekdays"].items():
        out.append(f'<text x="{left - 8}" y="{top + row * pitch + cell / 2 + 3.5:.1f}" font-size="10" text-anchor="end" '
                   f'fill="{t["muted"]}">{esc(name)}</text>')
    out.append('</g><g class="cells">')
    for col in range(weeks):
        week = grid[col * 7:(col + 1) * 7]
        rects = []
        for day, count in week:
            lv = level(count, cuts)
            rects.append(f'<rect x="{left + col * pitch:.1f}" y="{top + ((day.weekday() + 1) % 7) * pitch:.1f}" '
                         f'width="{cell:.1f}" height="{cell:.1f}" rx="2.5" fill="{t["empty"] if lv < 0 else t["levels"][lv]}"/>')
        out.append(f'<g class="c" style="animation-delay:{col * 0.012:.3f}s">' + "".join(rects) + "</g>")
    out.append("</g></g></g></svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- badges (official-links drawer) + contact
BADGE_H, BADGE_FS, ICON, PAD_Y = 25, 11.5, 14, 3


def badge_colors(color):
    """White type on the brand colour, deepened just enough for 4.5:1; dark type on brands too light for white."""
    if contrast("#FFFFFF", color) < 3:
        return color, "#1F2328"
    while contrast("#FFFFFF", color) < 4.5:
        color = mix(color, "#000000", .04)
    return color, "#FFFFFF"


def badge_svg(name, icon, color, paths, alt):
    """A capsule badge: brand colour, a soft top gloss, a white (or dark on light brands) glyph and name."""
    color, ink = badge_colors("#" + color)
    dark_ink = ink != "#FFFFFF"
    tw = text_w(name, BADGE_FS, bold=True) * 1.03  # a little slack for wider system fonts; the name is centred
    w = round(10 + ICON + 6 + tw + 11)
    h = BADGE_H
    out = svg_open(w, h + 2 * PAD_Y, alt)
    out.append("<defs>"
               '<linearGradient id="gloss" x1="0" y1="0" x2="0" y2="1">'
               '<stop offset="0" stop-color="#FFFFFF" stop-opacity=".3"/>'
               '<stop offset=".3" stop-color="#FFFFFF" stop-opacity="0"/>'
               '<stop offset=".5" stop-color="#000000" stop-opacity="0"/>'
               '<stop offset="1" stop-color="#000000" stop-opacity=".14"/></linearGradient></defs>')
    out.append(f'<g transform="translate(0,{PAD_Y})">')
    out.append(f'<rect width="{w}" height="{h}" rx="{h / 2}" fill="{color}"/>')
    out.append(f'<rect width="{w}" height="{h}" rx="{h / 2}" fill="url(#gloss)"/>')
    out.append(f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="{(h - 1) / 2}" fill="none" '
               f'stroke="#FFFFFF" stroke-opacity=".28"/>')
    if icon.startswith("@"):  # a raster logo sits on a white disc, so it reads on any badge colour
        out.append(f'<circle cx="{10 + ICON / 2:g}" cy="{h / 2:g}" r="{ICON / 2 + 1:g}" fill="#FFFFFF"/>')
        out.append(glyph(icon, paths, ink, 10.5, (h - ICON + 1) / 2, ICON - 1))
    else:
        out.append(glyph(icon, paths, ink, 10, (h - ICON) / 2, ICON, 2.1))
    ty, tx = h / 2 + BADGE_FS * 0.36, 10 + ICON + 6 + tw / 2
    if not dark_ink:
        out.append(f'<text x="{tx:.1f}" y="{ty + 1:.1f}" text-anchor="middle" font-size="{BADGE_FS}" font-weight="700" '
                   f'fill="#000000" fill-opacity=".22">{esc(name)}</text>')
    out.append(f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle" font-size="{BADGE_FS}" font-weight="700" '
               f'fill="{ink}">{esc(name)}</text>')
    out.append("</g></svg>")
    return "\n".join(out), w


def contact_svg(email):
    """One gradient capsule that reads on light and dark pages, so it can sit inside a mailto link."""
    w, h = round(text_w(email, 14, bold=True) + 76), 42
    out = svg_open(w, h, email)
    out.append("<defs>" + gradient("pill", ACCENT) + "</defs>")
    out.append(f'<rect width="{w}" height="{h}" rx="21" fill="url(#pill)"/>')
    out.append(f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="20.5" fill="none" stroke="#FFFFFF" stroke-opacity=".18"/>')
    out.append(f'<g transform="translate(17,9)"><path d="{MAIL}" fill="#FFFFFF"/></g>')
    out.append(f'<text x="{49 + (w - 49 - 22) / 2:.1f}" y="26" text-anchor="middle" font-size="14" font-weight="700" '
               f'fill="#FFFFFF">{esc(email)}</text>')
    out.append("</svg>")
    return "\n".join(out), w


# ---------------------------------------------------------------- README blocks
def picture(path, alt):
    """One line with no whitespace, so pictures placed side by side touch and the SVG margins form the gutter."""
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{RAW}{path.format(theme="dark")}">'
            f'<img src="{RAW}{path.format(theme="light")}" alt="{esc(alt)}"></picture>')


def stack_block(lang):
    x = TEXT[lang]
    cards = [picture(f"stack/{lang}-{{theme}}-{p}.svg", "; ".join(group_alt(lang, n) for n in (2 * p, 2 * p + 1)))
             for p in range(len(STACK) // 2)]
    linked = sum(1 for *_, items in STACK for i in items if i[3])
    rows = []
    for en, ko, _, items in STACK:  # the drawer lists only what has an official page; the cards show the rest
        badges = [f'<a href="{esc(i[3])}"><img src="{RAW}badges/{slug_id(i[0])}.svg" alt="{esc(i[4] if len(i) > 4 else i[0])}"></a>'
                  for i in items if i[3]]
        if badges:
            rows.append(f"<b>{esc(ko if lang == 'ko' else en)}</b><br>\n" + "\n".join(badges))
    drawer = (f"<details>\n<summary><b>{esc(x['links'])}</b> ·&nbsp;{x['links_note'].format(n=linked)}</summary>\n\n"
              "<p></p>\n\n<p>\n" + "\n<br><br>\n".join(rows) + "\n</p>\n\n</details>")
    return '<p align="center">\n' + "".join(cards) + "\n</p>\n\n" + drawer


def activity_block(lang, s):
    x = TEXT[lang]
    note = " (updated daily)" if lang == "en" else " (매일 갱신)"
    rows = tiles(s, lang)
    trios = "".join(picture(f"tiles/{lang}-{{theme}}-{k}.svg", "; ".join(r[5] for r in rows[3 * k:3 * k + 3]) + note)
                    for k in range(2))
    heat = "Contribution calendar for the last year" if lang == "en" else "최근 1년 기여 달력"
    # One paragraph, so the calendar wraps under the tiles with the same 8px gap as the stack rows.
    return '<p align="center">\n' + trios + picture(f"contrib-{lang}-{{theme}}.svg", heat + note) + "\n</p>"


def contact_block(lang, email, width):
    alt = f"{TEXT[lang]['email']}: {email}"
    return ('<p align="center">\n'
            f'<a href="mailto:{esc(email)}"><img src="{RAW}contact.svg" alt="{esc(alt)}" width="{width}"></a>\n'
            "</p>")


def replace_block(text, name, content):
    return re.sub(rf"(<!-- {name}:start -->\n).*?(<!-- {name}:end -->)",
                  lambda m: m.group(1) + (content + "\n" if content else "") + m.group(2), text, flags=re.S)


def readme_email(root):
    """The address the README shows now, so a run that can't read the profile still draws its pill."""
    block = re.search(r"<!-- contact:start -->(.*?)<!-- contact:end -->", (root / "README.md").read_text(encoding="utf-8"), re.S)
    m = re.search(r'href="mailto:([^"]+)"', block.group(1)) if block else None
    return html.unescape(m.group(1)) if m else ""


def sync_readme(root, s, email, width):
    changed = False
    for lang, name in (("en", "README.md"), ("ko", "README.ko.md")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        new = replace_block(text, "stack", stack_block(lang))
        new = replace_block(new, "activity", activity_block(lang, s))
        new = replace_block(new, "contact", contact_block(lang, email, width) if email else "")
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed = True
    print("README blocks", "updated" if changed else "unchanged")


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "out")
    for sub in ("badges", "stack", "tiles"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    head, created, days = fetch()
    today = dt.datetime.now(dt.timezone.utc).date()
    current, longest = streaks(days)
    s = dict(total=sum(days.values()), current=current, longest=longest, repos=head["repos"]["totalCount"],
             public=head["publicRepos"]["totalCount"], contributed=head["contributedTo"]["totalCount"],
             best=max(days.values(), default=0),
             active=sum(1 for d, c in days.items() if c and dt.date.fromisoformat(d) > today - dt.timedelta(days=365)),
             owner=os.environ.get("OWNER_TOKEN", "").lower() == "true")
    slugs = sorted({i[1] for *_, items in STACK for i in items if i[1][0] not in "#@"})
    paths = {slug: icon_path(slug) for slug in slugs}
    assert len(STACK) % 2 == 0, "stack cards are drawn in pairs"
    for lang in TEXT:
        for theme in THEMES:
            (out / f"hero-{lang}-{theme}.svg").write_text(hero_svg(lang, theme), encoding="utf-8")
            (out / f"contrib-{lang}-{theme}.svg").write_text(contrib_svg(lang, theme, days, today), encoding="utf-8")
            for p in range(len(STACK) // 2):
                (out / "stack" / f"{lang}-{theme}-{p}.svg").write_text(stack_pair_svg(lang, theme, p, paths), encoding="utf-8")
            rows = tiles(s, lang)
            assert len(rows) == 6, "tiles are drawn in threes"
            for k in range(2):
                (out / "tiles" / f"{lang}-{theme}-{k}.svg").write_text(tile_trio_svg(theme, rows, k), encoding="utf-8")
    for *_, items in STACK:
        for item in filter(lambda i: i[3], items):  # the drawer lists only technologies with an official page
            alt = item[4] if len(item) > 4 else item[0]
            svg, _w = badge_svg(item[0], item[1], item[2], paths, alt)
            (out / "badges" / f"{slug_id(item[0])}.svg").write_text(svg, encoding="utf-8")
    found = public_email()  # None when the lookup fails, "" when the profile shows no public address
    email = readme_email(Path(".")) if found is None else found
    width = 0
    if email:
        svg, width = contact_svg(email)
        (out / "contact.svg").write_text(svg, encoding="utf-8")
    if "--sync-readme" in sys.argv:
        sync_readme(Path("."), s, email, width)
    print(json.dumps(s | {"email": email}))


if __name__ == "__main__":
    main()