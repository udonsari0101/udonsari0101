"""Render the profile's visual cards as SVG and keep README blocks in sync.

    GH_TOKEN=... python .github/scripts/profile_cards.py OUT_DIR [--sync-readme]

Every block is drawn on one 832px column so edges line up: the hero, the
contribution calendar, eight stack cards drawn in pairs (416px images, 2 per row on
desktop and 1 on phones, where the pair scales down and its type steps up), and six
stat tiles drawn in threes (416px images, the same way). Images carry a 4px
transparent margin, so placed side by side with no whitespace they get an exact 8px
gutter. Also writes the contact pills (email and Instagram, from the public profile).
GH_TOKEN (the default Actions token) reads the calendar and public numbers;
OWNER_GH_TOKEN, the owner's token when the PROFILE_STATS_TOKEN secret exists, adds
repository counts that include private ones. --sync-readme rewrites the stack,
activity, and contact blocks in both READMEs.
"""
import datetime as dt
import html
import json
import math
import os
import re
import sys
import urllib.parse
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
    "en": dict(focus="Interested in", interests=["Information Security", "Software Engineering", "Automation",
                                                  "Computer Systems", "Artificial Intelligence"],
               tiles=dict(total="All-time total", longest="Longest streak", best="Most in one day",
                          repos="Repos · {p} private", public_repos="Public repos", contributed="Contributed to",
                          private="Private contributions", active="Active days · 1y"),
               # Fuller wording for alt text, which the tile's width doesn't limit; never a daily number.
               tile_alts=dict(total="All-time contributions", best="Most contributions in one day",
                              repos="Repositories, private ones included",
                              contributed="Repositories contributed to, private ones included",
                              private="Contributions to private repositories", active="Active days in the last year"),
               day="day", days="days", repos="", contribs="",
               heat="{n} contributions in the last year", less="Less", more="More",
               months=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
               weekdays={1: "Mon", 3: "Wed", 5: "Fri"}, email="Email"),
    "ko": dict(focus="관심 분야", interests=["정보보안", "소프트웨어 공학", "자동화", "컴퓨터 시스템", "인공지능"],
               tiles=dict(total="누적 기여", longest="최장 연속 기여", best="하루 최다 기여", repos="저장소 · 비공개 {p}",
                          public_repos="공개 저장소", contributed="기여한 저장소", private="비공개 기여", active="최근 1년 활동일"),
               tile_alts=dict(repos="저장소(비공개 포함)", contributed="기여한 저장소(비공개 포함)", private="비공개 저장소 기여"),
               day="일", days="일", repos="개", contribs="회",
               heat="최근 1년간 {n}회 기여", less="적음", more="많음", months=[f"{m}월" for m in range(1, 13)],
               weekdays={1: "월", 3: "수", 5: "금"}, email="이메일"),
}

# (EN title, KO title, group glyph, [(name, simple-icons slug | @logo | #glyph, brand hex[, alt])])
STACK = [
    ("Languages", "언어", "#code", [
        ("Python", "python", "3776AB"),
        ("JavaScript", "javascript", "D4B000"),
        ("TypeScript", "typescript", "3178C6"),
        ("Kotlin", "kotlin", "7F52FF"),
        ("SQL", "#table", "336791")]),
    ("Frontend · Backend", "프론트엔드·백엔드", "#layers", [
        ("React", "react", "087EA4"),
        ("HTML", "html5", "E34F26"),
        ("CSS", "css", "663399"),
        ("FastAPI", "fastapi", "009688"),
        ("Flask", "flask", "475569"),
        ("REST API", "openapiinitiative", "4D7F2A")]),
    ("Databases", "데이터베이스", "#database", [
        ("PostgreSQL", "postgresql", "4169E1"),
        ("MySQL", "mysql", "4479A1"),
        ("SQLite", "sqlite", "0F80CC"),
        ("Firebase", "firebase", "F59E0B"),
        ("Firestore", "firebase", "EA580C")]),
    ("Desktop · Android", "데스크톱·Android", "#monitor", [
        ("PySide6 (Qt)", "qt", "2E9E4F"),
        ("Electron", "electron", "47848F", "Electron (Node.js)"),
        ("Windows", "#window", "0078D4"),
        ("Jetpack Compose", "jetpackcompose", "4285F4"),
        ("Android SDK", "android", "34A853")]),
    ("DevOps · Cloud", "데브옵스·클라우드", "#infinity", [
        ("Linux", "linux", "C99700"),
        ("Docker", "docker", "2496ED"),
        ("Docker Compose", "docker", "1D63ED"),
        ("AWS", "#cloud", "FF9900"),
        ("GCP", "googlecloud", "4285F4")]),
    ("Robotics · AI", "로보틱스·AI", "#bot", [
        ("ROS 2", "ros", "4A6CB3"),
        ("Gazebo", "#cube", "D97706"),
        ("RViz", "#axes", "6366F1"),
        ("Generative AI", "#sparkle", "8B5CF6"),
        ("Diffusion Models", "#diffusion", "7C3AED"),
        ("LLM Integration & Fine-tuning", "#chat", "6D28D9")]),
    ("Security", "보안", "#shield", [
        ("IDA Pro", "@ida", "64748B"),
        ("Ghidra", "@ghidra", "E22726"),
        ("JADX-GUI", "@jadx", "461BBC"),
        ("x64dbg", "#bug", "64748B"),
        ("Burp Suite", "burpsuite", "EA580C"),
        ("mitmproxy", "@mitmproxy", "3F3F46")]),
    ("Tools", "도구", "#wrench", [
        ("Gradle", "gradle", "1F8A99"),
        ("GitHub Actions", "githubactions", "2088FF"),
        ("Notion", "notion", "3F3F46"),
        ("Figma", "figma", "F24E1E")]),
]
ICON_CROP = {"mysql": (13.8, 2.3, 10.4)}  # show only the dolphin of the MySQL wordmark
# Logos simple-icons doesn't carry, traced to one colour from the images the owner picked
# (IDA Pro's portrait, Ghidra's dragon, JADX's lettered disc, mitmproxy's circuit mark): 24-unit paths, even-odd fill.
LOGOS = {
    "ida": (
        "M4.20 23.77C4.56 23.45 5.77 22.66 6.37 22.36C7.10 22 7.42 21.52 7.21 21.12C7.15 21.03 7.09 20.79 7.05 20"
        ".60C7.02 20.38 6.86 20.10 6.62 19.85C6.23 19.45 6.23 19.45 6.42 19.14C6.58 18.87 6.60 18.71 6.54 18.16C6"
        ".46 17.41 6.43 17.38 5.75 17.15C5.14 16.94 4.85 16.68 4.60 16.13C4.50 15.89 4.31 15.60 4.18 15.48C3.54 1"
        "4.87 2.85 13.47 2.66 12.40C2.55 11.82 2.37 11.51 2.04 11.35C1.55 11.12 1.29 10.61 1.52 10.33C1.60 10.23 "
        "1.60 10.13 1.53 9.97C1.47 9.85 1.45 9.61 1.47 9.43C1.51 9.18 1.46 9.05 1.22 8.80C0.87 8.43 0.76 7.94 0.8"
        "5 7.17C0.91 6.74 0.89 6.60 0.75 6.46C0.21 5.93 0.31 4.53 0.94 3.85C1.08 3.70 1.20 3.50 1.20 3.41C1.20 2."
        "92 1.85 1.80 2.14 1.80C2.19 1.80 2.31 1.74 2.39 1.66C2.48 1.58 2.80 1.42 3.10 1.30C3.40 1.18 3.74 1 3.85"
        " 0.90C4.45 0.35 6.48 -0.01 7.51 0.25C8.02 0.38 8.12 0.38 8.51 0.24C9.19 -0.01 11.10 0.17 12.60 0.62C12.7"
        "9 0.67 13.36 0.95 13.85 1.22C14.34 1.50 14.93 1.74 15.15 1.77C16.15 1.91 17.67 2.89 17.85 3.53C17.88 3.6"
        "5 17.95 3.84 18 3.95C18.05 4.06 18.14 4.28 18.20 4.44C18.30 4.70 18.32 4.71 18.48 4.58C18.57 4.49 18.83 "
        "4.35 19.05 4.25C19.27 4.16 19.55 4.03 19.68 3.97C19.84 3.89 19.94 3.90 20.02 3.98C20.09 4.05 20.22 4.10 "
        "20.32 4.10C20.42 4.10 20.70 4.29 20.93 4.53C21.17 4.77 21.53 5.02 21.77 5.09C22.10 5.20 22.28 5.35 22.55"
        " 5.74C22.93 6.30 22.97 6.54 22.75 7.15C22.66 7.40 22.64 7.58 22.70 7.64C22.76 7.70 22.80 7.83 22.80 7.94"
        "C22.80 8.05 22.95 8.29 23.12 8.48C23.41 8.77 23.45 8.87 23.43 9.33C23.42 9.62 23.41 10.19 23.41 10.60C23"
        ".41 11.47 23.14 12.15 22.76 12.30C22.63 12.35 22.45 12.49 22.36 12.61C22.21 12.83 21.62 13.10 21.28 13.1"
        "0C21.13 13.10 21.10 13.19 21.10 13.55C21.10 14.38 20.49 15.07 19.55 15.29C19.28 15.36 18.95 15.44 18.82 "
        "15.47C18.61 15.52 18.31 15.43 17.90 15.19C17.56 14.99 17.48 14.98 17.30 15.15C17.03 15.39 17.05 15.49 17"
        ".38 15.56C17.99 15.69 18.50 16.27 18.50 16.84C18.50 16.92 18.54 17.02 18.60 17.05C18.89 17.23 18.71 17.9"
        "9 18.28 18.39C17.83 18.83 17.83 19 18.28 18.81C18.65 18.65 19.03 18.75 19.40 19.10C19.68 19.36 19.70 19."
        "43 19.70 20.13C19.70 20.67 19.74 20.91 19.85 21C19.93 21.07 20 21.21 20 21.31C20 21.41 20.05 21.52 20.10"
        " 21.55C20.16 21.58 20.20 21.83 20.20 22.10C20.20 22.37 20.25 22.62 20.30 22.65C20.36 22.68 20.40 22.91 2"
        "0.40 23.15C20.40 23.59 20.40 23.59 20.82 23.44C21.22 23.30 21.25 23.31 21.62 23.56C21.83 23.71 22 23.87 "
        "22 23.91C22 23.96 21.23 24 20.30 23.99C19 23.99 18.61 23.96 18.67 23.87C18.86 23.56 18.80 23.01 18.57 22"
        ".98C18.43 22.96 18.34 22.87 18.32 22.73C18.30 22.60 18.22 22.50 18.14 22.50C17.94 22.50 17.85 22.23 18 2"
        "2.05C18.13 21.89 18.09 21.87 17.73 21.90C17.56 21.91 17.50 21.86 17.50 21.71C17.50 21.59 17.44 21.50 17."
        "37 21.50C17.30 21.50 17.18 21.40 17.10 21.28C17.02 21.16 16.84 20.95 16.70 20.81C16.57 20.67 16.47 20.48"
        " 16.48 20.38C16.50 20.29 16.46 20.19 16.40 20.15C16.34 20.11 16.30 20.19 16.30 20.34C16.30 20.48 16.26 2"
        "0.60 16.20 20.60C16.14 20.60 16.10 20.51 16.10 20.41C16.10 20.31 16.03 20.20 15.95 20.16C15.87 20.13 15."
        "80 20.04 15.80 19.97C15.80 19.89 15.71 19.75 15.60 19.65C15.49 19.55 15.40 19.41 15.40 19.35C15.40 19.28"
        " 15.33 19.20 15.25 19.16C15.17 19.13 15.10 19.04 15.10 18.95C15.10 18.87 15.02 18.80 14.92 18.80C14.82 1"
        "8.80 14.70 18.68 14.63 18.50C14.57 18.34 14.43 18.17 14.33 18.14C14.23 18.11 14.07 18.04 13.98 17.99C13."
        "88 17.94 13.74 17.93 13.65 17.96C13.41 18.06 13.47 17.84 13.75 17.62C13.92 17.48 13.98 17.37 13.93 17.24"
        "C13.88 17.11 13.90 17.08 14.03 17.13C14.23 17.20 14.26 17 14.08 16.82C13.92 16.66 13.70 16.67 13.70 16.8"
        "4C13.70 16.97 13.42 17.15 13.34 17.07C13.32 17.05 13.35 16.89 13.41 16.71C13.59 16.19 13.30 15.68 12.90 "
        "15.83C12.59 15.95 12.20 15.73 12.20 15.43C12.20 15.28 12.36 15.25 12.44 15.39C12.52 15.51 13.01 15.40 13"
        ".06 15.25C13.09 15.18 13.04 14.96 12.96 14.75C12.87 14.54 12.80 14.27 12.80 14.14C12.80 14.01 12.76 13.9"
        "0 12.70 13.90C12.64 13.90 12.60 14.17 12.60 14.50C12.60 14.83 12.56 15.10 12.50 15.10C12.33 15.10 12.27 "
        "14.40 12.40 14C12.51 13.65 12.51 13.58 12.31 13.25C12.20 13.05 12.10 12.80 12.10 12.70C12.10 12.60 12.06"
        " 12.49 12 12.45C11.95 12.42 11.93 12.33 11.96 12.26C11.99 12.18 11.91 12 11.79 11.86C11.52 11.54 11.51 1"
        "1.49 11.48 9.70C11.47 9.03 11.45 8.56 11.41 8.32C11.39 8.15 10.43 7.51 10.02 7.39C9.34 7.19 7.70 7.52 7."
        "70 7.87C7.70 7.94 7.75 8 7.80 8C7.86 8 7.90 7.96 7.90 7.90C7.90 7.85 8.08 7.80 8.31 7.80C8.55 7.80 8.69 "
        "7.84 8.65 7.90C8.62 7.96 8.46 8 8.30 8C8.01 8 7.40 8.29 7.40 8.43C7.40 8.47 7.31 8.50 7.20 8.50C6.97 8.5"
        "0 6.93 8.32 7.14 8.24C7.41 8.14 7.41 7.90 7.15 7.80C6.94 7.72 6.91 7.66 6.96 7.43C7.11 6.78 7.72 6.55 8."
        "97 6.67C10.83 6.84 11.65 6.71 10.93 6.35C10.67 6.22 9.90 5.31 9.90 5.13C9.90 4.99 9.29 4.30 9.17 4.30C9."
        "09 4.30 8.55 3.94 8.32 3.73C8.25 3.66 8.14 3.57 8.07 3.53C7.91 3.42 7.10 2.24 7.10 2.11C7.10 1.94 6.88 1"
        ".98 6.55 2.20C6.35 2.34 6.16 2.38 5.97 2.34C5.78 2.30 5.68 2.33 5.64 2.44C5.60 2.54 5.46 2.60 5.26 2.60C"
        "4.97 2.60 4.40 3.04 4.40 3.26C4.40 3.30 4.33 3.41 4.24 3.51C4.15 3.61 4.08 3.89 4.07 4.18C4.06 4.46 4.01"
        " 4.72 3.97 4.76C3.83 4.90 3.90 5.19 4.10 5.30C4.21 5.36 4.28 5.45 4.25 5.50C4.22 5.55 4.48 5.89 4.84 6.2"
        "5C5.83 7.27 5.87 7.86 5.10 9.45C4.83 10 4.58 10.57 4.55 10.72C4.51 10.87 4.42 11.04 4.34 11.11C3.90 11.4"
        "7 4.25 11.65 5.40 11.65C6.45 11.65 6.70 11.83 5.97 12.07C5.02 12.39 4.60 13.20 5.40 13.20C5.60 13.20 5.8"
        "2 13.26 5.88 13.32C5.95 13.39 6.24 13.47 6.52 13.50C7.09 13.56 7.25 13.75 6.86 13.90C6.22 14.14 6 14.40 "
        "6.16 14.72C6.34 15.07 6.26 15.24 5.95 15.16C5.66 15.09 5.10 15.37 5.10 15.59C5.10 15.79 5.52 16.22 5.78 "
        "16.28C6.16 16.37 7.01 16.31 7.16 16.19C7.30 16.08 7.36 16.10 7.55 16.32C7.80 16.62 8.37 16.62 8.61 16.34"
        "C8.67 16.26 8.89 16.20 9.10 16.20C9.30 16.20 9.61 16.15 9.79 16.09C10.24 15.93 10.31 16.07 9.94 16.38C8."
        "97 17.22 8.47 18.75 9.11 18.90C9.24 18.93 9.37 19.05 9.39 19.15C9.41 19.26 9.47 19.38 9.53 19.41C9.68 19"
        ".51 9.53 19.81 9.31 19.87C8.92 19.97 8.93 21.40 9.32 21.40C9.58 21.40 9.52 21.73 9.25 21.79C9.14 21.81 8"
        ".84 21.97 8.59 22.16C8.34 22.34 8.02 22.54 7.88 22.59C7.74 22.64 7.36 22.90 7.04 23.17C6.04 23.99 6.02 2"
        "4 4.93 24C3.95 24 3.95 24 4.20 23.77ZM15.97 23.93C15.93 23.90 15.90 23.78 15.90 23.68C15.90 23.58 15.79 "
        "23.44 15.65 23.38C15.44 23.29 15.40 23.22 15.45 23C15.49 22.83 15.46 22.69 15.37 22.62C15.11 22.40 15.22"
        " 21.95 15.53 21.92C15.98 21.87 16.15 21.96 15.99 22.17C15.87 22.32 15.87 22.33 16.02 22.27C16.14 22.23 1"
        "6.21 22.27 16.25 22.41C16.29 22.51 16.40 22.65 16.50 22.70C16.64 22.78 16.68 22.88 16.64 23.08C16.60 23."
        "29 16.66 23.43 16.89 23.68L17.19 24L16.61 24C16.29 24 16 23.97 15.97 23.93ZM12.80 18.11C12.80 17.96 13.0"
        "8 17.78 13.20 17.85C13.28 17.90 13.28 17.96 13.19 18.06C13.06 18.21 12.80 18.25 12.80 18.11ZM3.84 10.74C"
        "3.79 10.39 3.81 10.29 3.94 10.24C4.03 10.21 4.10 10.10 4.10 10C4.10 9.89 4.15 9.78 4.20 9.75C4.42 9.61 4"
        ".28 9.51 3.88 9.53C3.34 9.55 3.09 9.81 3.34 10.09C3.43 10.19 3.48 10.34 3.44 10.43C3.37 10.62 3.69 11.32"
        " 3.82 11.24C3.87 11.21 3.88 10.99 3.84 10.74ZM8.56 9.05C8.47 8.96 8.40 8.82 8.40 8.75C8.40 8.56 8.27 8.5"
        "0 8.10 8.60C7.99 8.67 7.99 8.71 8.09 8.84C8.21 8.98 8.17 9 7.76 9C7.20 9 7.14 8.79 7.62 8.50C7.98 8.28 8"
        ".87 8.23 9.18 8.40C9.27 8.45 9.48 8.55 9.63 8.60C9.98 8.72 9.96 9.03 9.60 9.05C9.46 9.06 9.21 9.10 9.04 "
        "9.14C8.81 9.19 8.68 9.17 8.56 9.05ZM9.82 8.38C9.52 8.08 9.74 8.02 10.10 8.30C10.33 8.48 10.34 8.50 10.15"
        " 8.50C10.03 8.50 9.89 8.45 9.82 8.38Z"),
    "ghidra": (
        "M9.97 23.14C7.99 22.78 6.09 21.85 4.45 20.44C3.79 19.86 3.08 19.03 3.35 19.14C3.46 19.18 3.63 19.23 3.72"
        " 19.25C3.81 19.27 4.92 19.62 6.17 20.03C9.05 20.98 9.80 21.14 11.40 21.13C13.41 21.13 14.80 20.71 16.49 "
        "19.60C18.36 18.37 19.24 16.59 19.25 14C19.25 11.48 18.54 10.44 16.53 10.09C15.63 9.93 15.23 10.10 14.98 "
        "10.76C14.62 11.74 13.63 12.60 12.87 12.60C12.54 12.60 12.54 12.60 11.94 14.16C10.80 17.16 10.10 18.63 9."
        "70 18.82C8.91 19.21 7.36 18.42 6.20 17.05C5.57 16.31 5.57 16.32 6.38 16.41C8.47 16.65 8.51 16.62 8.64 14"
        ".92C8.73 13.62 8.73 13.62 8.36 12.84C8.15 12.40 7.95 11.83 7.91 11.55L7.85 11.05L7.60 11.54C7.20 12.34 6"
        ".56 12.63 5.83 12.37C5.44 12.23 5.56 12.56 6 12.87C6.22 13.02 6.40 13.18 6.40 13.21C6.40 13.41 5.06 13.4"
        "7 4.65 13.28C4.17 13.06 4.23 13.46 4.77 14.04C5.12 14.42 5.01 14.46 4.12 14.25C3.52 14.11 3.28 14 3.02 1"
        "3.74C2.56 13.28 2.55 13.29 2.24 14.78C2.17 15.11 2.08 15.06 1.68 14.45C0.87 13.21 0.97 11.64 1.94 10.62C"
        "2.34 10.19 2.62 10.05 3.68 9.74C5.54 9.20 6.32 8.54 6.75 7.15C7.16 5.79 7.81 5.36 9.03 5.60C9.57 5.70 9."
        "63 5.70 9.75 5.53C11.78 2.63 15.94 1.23 18.24 2.67C18.95 3.11 18.94 3.16 18.12 3.23C17.49 3.27 16.82 3.4"
        "5 16.91 3.55C16.94 3.57 17.13 3.55 17.35 3.50C18.82 3.19 19.12 3.24 19.87 3.95C20.83 4.83 21.82 6.25 22."
        "38 7.53C25.93 15.74 18.78 24.73 9.97 23.14ZM11.78 21.53C11.57 21.51 11.23 21.51 11.03 21.53C10.82 21.55 "
        "10.99 21.57 11.40 21.57C11.81 21.57 11.98 21.55 11.78 21.53ZM2.79 18.56C2.64 18.25 2.82 17.97 3.14 18.02"
        "C3.46 18.07 3.44 18.74 3.13 18.78C2.97 18.80 2.87 18.74 2.79 18.56ZM3.24 18.27C3.16 18.06 3.01 18.05 2.9"
        "4 18.25C2.83 18.53 2.98 18.76 3.16 18.59C3.24 18.50 3.28 18.36 3.24 18.27ZM3.84 17.66C3.72 17.34 3.84 17"
        ".05 4.10 17.05C4.46 17.05 4.48 17.73 4.12 17.78C3.99 17.80 3.88 17.75 3.84 17.66ZM4.28 17.38C4.26 17.25 "
        "4.18 17.15 4.10 17.15C4.02 17.15 3.94 17.25 3.92 17.38C3.89 17.55 3.94 17.60 4.10 17.60C4.26 17.60 4.31 "
        "17.55 4.28 17.38ZM2.77 16.64C2.51 16.37 2.88 15.77 3.18 15.97C3.46 16.14 3.40 16.64 3.10 16.68C2.96 16.7"
        "0 2.81 16.68 2.77 16.64ZM3.80 16.55C3.64 16.36 3.81 15.90 4.04 15.90C4.43 15.90 4.53 16.62 4.14 16.68C4."
        "03 16.70 3.87 16.64 3.80 16.55ZM4.80 16.51C4.65 16.22 4.84 15.88 5.13 15.92C5.31 15.94 5.35 16.02 5.35 1"
        "6.30C5.35 16.72 4.99 16.86 4.80 16.51ZM3.20 16.35C3.20 16.19 3.14 16.10 3.05 16.10C2.96 16.10 2.90 16.19"
        " 2.90 16.35C2.90 16.51 2.96 16.60 3.05 16.60C3.14 16.60 3.20 16.51 3.20 16.35ZM4.25 16.34C4.25 16.24 4.1"
        "7 16.14 4.08 16.12C3.90 16.09 3.82 16.39 3.97 16.54C4.09 16.65 4.25 16.54 4.25 16.34ZM5.25 16.34C5.25 16"
        ".24 5.17 16.14 5.08 16.12C4.90 16.09 4.82 16.39 4.97 16.54C5.09 16.65 5.25 16.54 5.25 16.34ZM3.78 15.45C"
        "3.64 15.15 3.83 14.88 4.14 14.92C4.53 14.98 4.43 15.70 4.04 15.70C3.96 15.70 3.85 15.59 3.78 15.45ZM4.86"
        " 15.54C4.54 15.23 4.83 14.70 5.21 14.90C5.42 15.02 5.46 15.40 5.28 15.58C5.12 15.74 5.05 15.73 4.86 15.5"
        "4ZM4.27 15.35C4.32 15.19 4.13 14.97 4.01 15.04C3.83 15.16 3.88 15.52 4.07 15.48C4.16 15.46 4.25 15.41 4."
        "27 15.35ZM5.25 15.25C5.25 14.97 4.96 15 4.92 15.28C4.89 15.47 4.92 15.51 5.07 15.48C5.17 15.46 5.25 15.3"
        "6 5.25 15.25ZM5.90 15.11C5.90 14.95 5.87 14.75 5.84 14.66C5.80 14.55 5.83 14.50 5.94 14.50C6.06 14.50 6."
        "10 14.60 6.10 14.95C6.10 15.20 6.05 15.40 6 15.40C5.95 15.40 5.90 15.27 5.90 15.11ZM19.57 13.88C19.55 13"
        ".64 19.53 13.83 19.53 14.30C19.53 14.77 19.55 14.96 19.57 14.73C19.59 14.49 19.59 14.11 19.57 13.88ZM6.7"
        "7 14.34C6.51 14.07 6.88 13.47 7.18 13.67C7.46 13.84 7.40 14.34 7.10 14.38C6.96 14.40 6.81 14.38 6.77 14."
        "34ZM7.20 14.06C7.20 13.92 7.16 13.79 7.11 13.76C6.98 13.67 6.79 13.95 6.86 14.14C6.96 14.39 7.20 14.33 7"
        ".20 14.06Z"),
    "jadx": (
        "M10.36 22.99C5.07 22.22 0.90 17.44 0.90 12.14C0.90 11.11 0.90 11.11 1.29 11.39C2.28 12.10 4.11 11.84 4.7"
        "9 10.89C5.25 10.27 5.30 9.78 5.30 6.29L5.30 3.10L6.01 2.64C9.22 0.56 13.45 0.32 16.85 2.02C20.29 3.75 22"
        ".58 7 23.05 10.82L23.12 11.39L22.09 11.42L21.06 11.45L20.44 12.55C20.10 13.15 19.78 13.66 19.73 13.67C19"
        ".69 13.68 19.38 13.19 19.04 12.57L18.44 11.45L17.36 11.42C16.45 11.40 16.28 11.42 16.33 11.54C16.36 11.6"
        "2 16.89 12.49 17.51 13.47C18.12 14.45 18.63 15.30 18.63 15.35C18.63 15.41 18.02 16.39 17.27 17.53C16.52 "
        "18.68 15.90 19.65 15.90 19.71C15.90 19.76 16.36 19.80 16.95 19.80L17.99 19.80L18.82 18.40C19.28 17.63 19"
        ".68 17 19.72 17C19.79 17 20.80 18.59 20.80 18.71C20.80 18.87 19.24 20.42 18.62 20.88C16.27 22.62 13.21 2"
        "3.41 10.36 22.99ZM12.45 19.65C14.12 19.21 15.12 18.09 15.41 16.33C15.71 14.49 14.91 12.69 13.44 11.94L12"
        ".89 11.65L12.30 12.30C11.60 13.07 11.60 13.05 12.07 13.21C13.07 13.54 13.66 14.56 13.58 15.84C13.48 17.3"
        "3 12.76 18.04 11.19 18.17L10.50 18.23L10.50 16.36C10.50 15.18 10.46 14.50 10.40 14.52C10.35 14.54 9.94 1"
        "4.96 9.51 15.45L8.71 16.35L8.70 18.07L8.70 19.80L10.28 19.80C11.37 19.80 12.04 19.75 12.45 19.65ZM21.30 "
        "16.14C21.02 15.73 20.80 15.35 20.82 15.31C20.93 15.02 22.97 11.90 23.04 11.90C23.18 11.90 23.02 13.54 22"
        ".80 14.48C22.58 15.41 22.02 16.90 21.89 16.90C21.84 16.90 21.58 16.56 21.30 16.14ZM8.60 10.80L8.92 10L10"
        ".58 10.02L12.23 10.05L12.38 10.48C12.55 11 12.51 11.01 13.33 10.14L14 9.43L13.36 7.84C13.01 6.97 12.46 5"
        ".56 12.14 4.72L11.55 3.20L10.62 3.22C9.69 3.25 9.69 3.25 9.50 3.70C8.27 6.64 6.40 11.19 6.33 11.43C6.28 "
        "11.58 6.37 11.60 7.28 11.60L8.28 11.60L8.60 10.80ZM1.06 9.93C1.40 8.40 1.95 7.05 2.71 5.90C3 5.46 3.28 5"
        ".10 3.33 5.10C3.38 5.10 3.40 6.08 3.38 7.34C3.35 9.56 3.35 9.59 3.11 9.84C2.78 10.19 2.45 10.17 2.08 9.7"
        "8L1.78 9.46L1.48 9.83C1.13 10.27 0.97 10.30 1.06 9.93ZM9.60 8.39C9.60 8.30 10.50 5.90 10.57 5.81C10.63 5"
        ".73 10.71 5.89 11.09 6.91C11.75 8.65 11.79 8.50 10.61 8.50C9.97 8.50 9.60 8.46 9.60 8.39Z"),
    "mitmproxy": (
        "M10.56 22.55C8.50 22.25 6.12 21.17 4.93 20.01C4.76 19.83 4.39 19.63 4.12 19.55C3.17 19.26 2.81 18.39 3.3"
        "2 17.63C4.03 16.59 5.71 17.31 5.47 18.55C5.37 19.09 7.28 20.35 9.05 20.93C14.81 22.81 20.79 19.01 21.64 "
        "12.93L21.70 12.50L18.65 12.50C15.88 12.50 15.60 12.52 15.60 12.67C15.60 12.99 15.07 13.91 14.64 14.34C13"
        ".20 15.76 10.80 15.75 9.42 14.32C9.01 13.90 8.65 13.27 8.46 12.68C8.41 12.51 8.18 12.50 5.39 12.50L2.38 "
        "12.50L2.45 13.06C2.49 13.37 2.58 13.84 2.66 14.11L2.81 14.60L4.65 14.60C6 14.60 6.52 14.63 6.60 14.73C6."
        "65 14.79 6.90 15.12 7.14 15.46C8.90 17.91 12.55 18.63 15.17 17.03C16.09 16.47 17.03 15.53 16.93 15.26C16"
        ".62 14.43 17.08 13.62 17.91 13.53C19.05 13.42 19.67 14.75 18.86 15.56C18.67 15.75 18.43 15.90 18.33 15.9"
        "0C18.22 15.90 17.98 16.11 17.76 16.40C15.86 18.89 12.04 19.82 9.06 18.51C8 18.04 6 16.39 6 15.99C6 15.94"
        " 5.18 15.90 4.17 15.90C1.71 15.90 1.88 15.98 1.50 14.57C-0.34 7.66 4.89 0.87 12.05 0.87C14.58 0.87 17 1."
        "72 18.86 3.27C19.14 3.50 19.61 3.77 19.90 3.87C20.90 4.21 21.18 5.21 20.46 5.87C19.61 6.66 18.25 5.97 18"
        ".43 4.84C18.55 4.13 16.22 2.78 14.04 2.30C8.57 1.09 2.95 5.12 2.43 10.62L2.37 11.30L5.37 11.30L8.38 11.3"
        "0L8.45 10.93C8.92 8.38 12.26 7.21 14.32 8.87C14.89 9.34 15.45 10.18 15.60 10.82L15.72 11.30L18.72 11.30L"
        "21.72 11.30L21.65 10.68C21.61 10.33 21.50 9.76 21.41 9.40L21.24 8.75L19.28 8.72C17.32 8.70 17.32 8.70 17"
        ".21 8.42C16.96 7.83 15.73 6.71 14.85 6.28C13.42 5.56 11.55 5.41 10.16 5.89C8.63 6.41 7 7.72 7.20 8.25C7."
        "52 9.10 6.64 10.04 5.76 9.79C4.62 9.46 4.55 7.86 5.65 7.50C5.86 7.43 6.34 7.05 6.83 6.57C7.28 6.12 7.92 "
        "5.60 8.24 5.41C10.70 3.96 13.91 4.06 16.22 5.66C16.76 6.03 18 7.25 18 7.41C18 7.46 18.92 7.50 20.04 7.50"
        "L22.08 7.50L22.29 8.07C22.84 9.59 23.05 11.73 22.81 13.39C21.96 19.19 16.34 23.39 10.56 22.55ZM4.80 18.8"
        "8C5.28 18.37 5.11 17.73 4.46 17.56C3.95 17.43 3.56 17.71 3.52 18.25C3.46 18.99 4.31 19.40 4.80 18.88ZM3."
        "87 18.72C3.65 18.48 3.66 18.07 3.88 17.87C4.46 17.34 5.25 18.15 4.70 18.70C4.45 18.95 4.08 18.96 3.87 18"
        ".72ZM18.57 15.35C18.84 15.16 18.94 14.74 18.80 14.40C18.48 13.62 17.30 13.84 17.30 14.68C17.30 15.36 18."
        "01 15.74 18.57 15.35ZM17.56 15.08C17.07 14.39 18.02 13.74 18.53 14.41C18.69 14.64 18.70 14.71 18.60 14.9"
        "1C18.35 15.37 17.82 15.45 17.56 15.08ZM13.07 13.96C14.94 13 14.96 10.51 13.11 9.58C10.48 8.25 8.20 12 10"
        ".59 13.72C11.28 14.21 12.38 14.32 13.07 13.96ZM11.50 13.91C9.77 13.35 9.25 11.41 10.50 10.19C12.43 8.30 "
        "15.36 10.81 13.83 13.03C13.35 13.73 12.23 14.15 11.50 13.91ZM12.52 13.50C13.30 13.28 13.80 12.59 13.80 1"
        "1.73C13.80 9.92 11.55 9.27 10.53 10.79C9.62 12.14 10.94 13.93 12.52 13.50ZM11.65 13.12C10.11 12.61 10.43"
        " 10.37 12.04 10.37C13.53 10.37 14 12.34 12.66 12.99C12.23 13.20 12.01 13.23 11.65 13.12ZM6.51 9.29C7.12 "
        "8.86 6.80 7.90 6.05 7.90C5.28 7.90 4.96 8.67 5.49 9.21C5.84 9.55 6.11 9.58 6.51 9.29ZM5.80 9.23C5.36 9.0"
        "6 5.29 8.60 5.65 8.24C5.94 7.95 6.23 7.98 6.53 8.32C6.76 8.59 6.75 8.76 6.45 9.05C6.21 9.30 6.08 9.33 5."
        "80 9.23ZM19.89 5.80C20.10 5.80 20.40 5.36 20.40 5.05C20.40 4.11 19.17 3.94 18.85 4.84C18.69 5.30 19.27 6"
        " 19.68 5.85C19.76 5.82 19.85 5.80 19.89 5.80ZM19.42 5.59C19.09 5.46 18.93 5.06 19.10 4.75C19.48 4.05 20."
        "50 4.60 20.14 5.31C19.99 5.61 19.74 5.71 19.42 5.59Z"),
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
    "#lock": ([], ["M6.5 10.5h11a2 2 0 0 1 2 2V19a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2v-6.5a2 2 0 0 1 2-2z",
                   "M8 10.5V7.5a4 4 0 0 1 8 0v3", "M12 14.5v2.5"]),
    "#instagram": ([ring(17.3, 6.7, 1.3)], ["M7.5 3h9A4.5 4.5 0 0 1 21 7.5v9a4.5 4.5 0 0 1-4.5 4.5h-9A4.5 4.5 0 0 1 3 16.5v-9A4.5 4.5 0 0 1 7.5 3z",
                                            ring(12, 12, 4.2)]),
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
        return (f'<g transform="translate({x:.1f},{y:.1f}) scale({size / 24:.4f})">'
                f'<path d="{LOGOS[icon[1:]]}" fill="{color}" fill-rule="evenodd"/></g>')
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
def request(url, data=None, token=None):
    headers = {"Authorization": f"bearer {token or os.environ['GH_TOKEN']}", "User-Agent": "profile-cards"}
    if data is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=30) as r:
        return json.load(r)


def graphql(query, variables, token=None):
    body = request("https://api.github.com/graphql", {"query": query, "variables": variables}, token)
    if body.get("errors"):
        raise RuntimeError(f"GraphQL error: {body['errors']}")
    return body["data"]


def fetch():
    """The calendar and public numbers, read with the default token so the days match GitHub's own graph.
    restrictedContributionsCount is what this viewer can't open: the owner's private contributions,
    which the profile shares as counts."""
    head = graphql("""query($login: String!) { user(login: $login) { createdAt
        publicRepos: repositories(ownerAffiliations: OWNER, privacy: PUBLIC) { totalCount } } }""",
                   {"login": LOGIN})["user"]
    created = dt.datetime.fromisoformat(head["createdAt"].replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    days, restricted, start = {}, 0, dt.datetime(created.year, 1, 1, tzinfo=dt.timezone.utc)
    while start <= now:
        end = min(dt.datetime(start.year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc), now)
        data = graphql("""query($login: String!, $from: DateTime!, $to: DateTime!) { user(login: $login) {
            contributionsCollection(from: $from, to: $to) { restrictedContributionsCount contributionCalendar {
                weeks { contributionDays { date contributionCount } } } } } }""",
                       {"login": LOGIN, "from": start.isoformat(), "to": end.isoformat()})
        collection = data["user"]["contributionsCollection"]
        restricted += collection["restrictedContributionsCount"]
        for week in collection["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
        start = dt.datetime(start.year + 1, 1, 1, tzinfo=dt.timezone.utc)
    return head["publicRepos"]["totalCount"], days, restricted


def owner_counts():
    """Repository counts with the owner's token, which sees private repositories.
    None without the token, or when it has expired or belongs to someone else."""
    token = os.environ.get("OWNER_GH_TOKEN", "").strip()
    if not token:
        print("no owner token, showing public numbers")
        return None
    try:
        v = graphql("""query { viewer { login
            repos: repositories(ownerAffiliations: OWNER) { totalCount }
            privateRepos: repositories(ownerAffiliations: OWNER, privacy: PRIVATE) { totalCount }
            contributedTo: repositoriesContributedTo(includeUserRepositories: false,
                contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount } } }""", {}, token)["viewer"]
    except Exception as e:  # noqa: BLE001 — fall back to public numbers rather than fail the job
        print(f"owner token unusable, showing public numbers: {e}")
        return None
    if v["login"].lower() != LOGIN:
        print("owner token belongs to another account, showing public numbers")
        return None
    if not v["privateRepos"]["totalCount"]:  # a token without private access would print "0 private"
        print("owner token sees no private repositories (check its access), showing public numbers")
        return None
    return dict(repos=v["repos"]["totalCount"], private=v["privateRepos"]["totalCount"],
                contributed=v["contributedTo"]["totalCount"])


def longest_streak(days):
    longest = run = 0
    for d in sorted(days):
        run = run + 1 if days[d] else 0
        longest = max(longest, run)
    return longest


def public_email():
    try:
        email = (request(f"https://api.github.com/users/{LOGIN}").get("email") or "").strip()
    except Exception as e:  # noqa: BLE001 — keep the README as it is when the API fails
        print(f"email lookup failed: {e}")
        return None
    return email if re.fullmatch(r"[^@\s<>\"']+@[^@\s<>\"']+\.[A-Za-z]{2,}", email) else ""


def instagram_handle():
    """The Instagram account linked on the GitHub profile: None when the lookup fails, "" when there is none."""
    try:
        accounts = request(f"https://api.github.com/users/{LOGIN}/social_accounts")
    except Exception as e:  # noqa: BLE001 — keep the README as it is when the API fails
        print(f"social account lookup failed: {e}")
        return None
    for a in accounts:
        url = a.get("url") or ""
        parts = urllib.parse.urlsplit(url if "//" in url else "https://" + url)
        host = (parts.hostname or "").lower()
        if host == "instagram.com" or host.endswith(".instagram.com") or a.get("provider") == "instagram":
            handle = parts.path.strip("/").split("/")[0]
            # A link the job can't read keeps the README's current pill rather than dropping it.
            return handle if re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle) else None
    return ""


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
    return f"{ko if lang == 'ko' else en}: " + ", ".join(i[3] if len(i) > 3 else i[0] for i in items)


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
    out.append(f'<text class="lb{uid}" x="13" y="85" font-size="{size}" fill="{t["muted"]}">{esc(label)}</text>')
    return out


def label_small(label):
    """A label's size on phones: up to 14px while it still fits the narrowest tile."""
    return round(min(14, (math.floor(TILE_W - GUT) - 26) / text_w(label, 1)), 1)


def tile_trio_svg(theme, rows, k):
    """Three tiles in one image: six across with the other trio on desktop, three across on phones."""
    trio = rows[3 * k:3 * k + 3]
    style = (f"@media (max-width:{PAIR_SMALL}px){{.un{{font-size:13px}}"
             + "".join(f".lb{j}{{font-size:{label_small(r[4])}px}}" for j, r in enumerate(trio)) + "}")
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
    rows = [("total", "#pulse", f"{s['total']:,}", x["contribs"], m["total"], "total"),
            ("longest", "#trophy", str(s["longest"]), unit(s["longest"]), m["longest"], "longest"),
            ("best", "#bolt", f"{s['best']:,}", x["contribs"], m["best"], "best")]
    if s["owner"]:  # the owner's token sees private repositories
        rows += [("repos", "#repo", str(s["repos"]), x["repos"], m["repos"].format(p=s["private"]), "repos"),
                 ("contributed", "#branch", str(s["contributed"]), x["repos"], m["contributed"], "contributed")]
    else:  # the default token sees public repositories only, but the profile shares private contribution counts
        rows += [("repos", "#repo", str(s["public"]), x["repos"], m["public_repos"], "public_repos"),
                 ("contributed", "#lock", f"{s['restricted']:,}", x["contribs"], m["private"], "private")]
    rows.append(("active", "#calendar", str(s["active"]), unit(s["active"]), m["active"], "active"))
    return [(key, g, value, u, label, alts.get(name, label), ramp(i / (len(rows) - 1)))
            for i, (key, g, value, u, label, name) in enumerate(rows)]


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
    band, span = 140, iw - left - right
    out = svg_open(COL, h + 3, title,
                   ".cells>rect{transform-box:fill-box;transform-origin:center;"
                   "animation:pop .55s cubic-bezier(.2,.9,.3,1.25) both}"
                   "@keyframes pop{from{opacity:0;transform:scale(.3)}}"
                   f".sweep{{animation:sweep 6s cubic-bezier(.45,0,.25,1) 1.8s infinite}}"
                   f"@keyframes sweep{{0%{{transform:translateX(0)}}45%,100%{{transform:translateX({span + 2 * band}px)}}}}"
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
    active = []
    for i, (day, count) in enumerate(grid):
        col, row = i // 7, (day.weekday() + 1) % 7
        lv = level(count, cuts)
        box = f'x="{left + col * pitch:.1f}" y="{top + row * pitch:.1f}" width="{cell:.1f}" height="{cell:.1f}" rx="2.5"'
        out.append(f'<rect {box} fill="{t["empty"] if lv < 0 else t["levels"][lv]}" '
                   f'style="animation-delay:{col * .018 + row * .035:.3f}s"/>')
        if lv >= 0:
            active.append(f"<rect {box}/>")
    # A soft band of light crosses the days with contributions every few seconds; at rest it sits left
    # of the grid, so it stays invisible where animation is off.
    out.append(f'<defs><clipPath id="act">{"".join(active)}</clipPath>'
               '<linearGradient id="sheen"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0"/>'
               f'<stop offset=".5" stop-color="#FFFFFF" stop-opacity="{.5 if theme == "light" else .45}"/>'
               '<stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient></defs>'
               f'<g clip-path="url(#act)"><rect class="sweep" x="{left - 2 * band}" y="{top}" width="{band}" '
               f'height="{7 * pitch:.1f}" fill="url(#sheen)"/></g>')
    out.append("</g></g></g></svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- contact pills
INSTAGRAM = ("#F56040", "#E1306C", "#C13584", "#833AB4", "#5851DB")  # Instagram's palette; white text stays at 4.5:1


def pill_svg(label, icon, colors):
    """A gradient capsule with a white glyph and label that reads on light and dark pages, so it can sit in a link.
    A 4px margin on each side gives two pills an 8px gap."""
    w, h = round(text_w(label, 14, bold=True) + 76), 42
    out = svg_open(w + 8, h, label)
    out.append("<defs>" + gradient("pill", colors) + "</defs>")
    out.append('<g transform="translate(4,0)">')
    out.append(f'<rect width="{w}" height="{h}" rx="21" fill="url(#pill)"/>')
    out.append(f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="20.5" fill="none" stroke="#FFFFFF" stroke-opacity=".18"/>')
    out.append(f'<g transform="translate(17,9)"><path d="{MAIL}" fill="#FFFFFF"/></g>' if icon == "mail"
               else glyph(icon, {}, "#FFFFFF", 17, 9, 24, 2.1))
    out.append(f'<text x="{49 + (w - 49 - 22) / 2:.1f}" y="26" text-anchor="middle" font-size="14" font-weight="700" '
               f'fill="#FFFFFF">{esc(label)}</text>')
    out.append("</g></svg>")
    return "\n".join(out), w + 8


# ---------------------------------------------------------------- README blocks
def picture(path, alt):
    """One line with no whitespace, so pictures placed side by side touch and the SVG margins form the gutter."""
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{RAW}{path.format(theme="dark")}">'
            f'<img src="{RAW}{path.format(theme="light")}" alt="{esc(alt)}"></picture>')


def stack_block(lang):
    cards = [picture(f"stack/{lang}-{{theme}}-{p}.svg", "; ".join(group_alt(lang, n) for n in (2 * p, 2 * p + 1)))
             for p in range(len(STACK) // 2)]
    return '<p align="center">\n' + "".join(cards) + "\n</p>"


def activity_block(lang, s):
    x = TEXT[lang]
    note = " (updated daily)" if lang == "en" else " (매일 갱신)"
    rows = tiles(s, lang)
    trios = "".join(picture(f"tiles/{lang}-{{theme}}-{k}.svg", "; ".join(r[5] for r in rows[3 * k:3 * k + 3]) + note)
                    for k in range(2))
    heat = "Contribution calendar for the last year" if lang == "en" else "최근 1년 기여 달력"
    # One paragraph, so the calendar wraps under the tiles with the same 8px gap as the stack rows.
    return '<p align="center">\n' + trios + picture(f"contrib-{lang}-{{theme}}.svg", heat + note) + "\n</p>"


def contact_block(lang, contact):
    """Email and Instagram pills on one line, with no whitespace between the links (their margins make the gap)."""
    (email, ew), (handle, iw) = contact["email"], contact["instagram"]
    links = []
    if email:
        links.append(f'<a href="mailto:{esc(email)}"><img src="{RAW}contact.svg" '
                     f'alt="{esc(TEXT[lang]["email"] + ": " + email)}" width="{ew}"></a>')
    if handle:
        links.append(f'<a href="https://www.instagram.com/{esc(handle)}/"><img src="{RAW}instagram.svg" '
                     f'alt="{esc("Instagram: @" + handle)}" width="{iw}"></a>')
    return '<p align="center">\n' + "".join(links) + "\n</p>" if links else ""


def replace_block(text, name, content):
    return re.sub(rf"(<!-- {name}:start -->\n).*?(<!-- {name}:end -->)",
                  lambda m: m.group(1) + (content + "\n" if content else "") + m.group(2), text, flags=re.S)


def readme_contact(root, pattern):
    """What the README's contact block shows now, so a run that can't read the profile still draws its pills."""
    block = re.search(r"<!-- contact:start -->(.*?)<!-- contact:end -->", (root / "README.md").read_text(encoding="utf-8"), re.S)
    m = re.search(pattern, block.group(1)) if block else None
    return html.unescape(m.group(1)) if m else ""


def sync_readme(root, s, contact):
    changed = False
    for lang, name in (("en", "README.md"), ("ko", "README.ko.md")):
        path = root / name
        text = path.read_text(encoding="utf-8")
        new = replace_block(text, "stack", stack_block(lang))
        new = replace_block(new, "activity", activity_block(lang, s))
        new = replace_block(new, "contact", contact_block(lang, contact))
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed = True
    print("README blocks", "updated" if changed else "unchanged")


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "out")
    for sub in ("stack", "tiles"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    public, days, restricted = fetch()
    today = dt.datetime.now(dt.timezone.utc).date()
    owner = owner_counts()
    s = dict(total=sum(days.values()), longest=longest_streak(days), best=max(days.values(), default=0),
             active=sum(1 for d, c in days.items() if c and dt.date.fromisoformat(d) > today - dt.timedelta(days=365)),
             public=public, restricted=restricted, owner=owner is not None, **(owner or {}))
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
    # None means the lookup failed: keep what the README shows. "" means the profile has none: drop it.
    found = {"email": (public_email(), r'href="mailto:([^"]+)"', "contact.svg", "mail", ACCENT),
             "instagram": (instagram_handle(), r'instagram\.com/([A-Za-z0-9._]+)/', "instagram.svg", "#instagram", INSTAGRAM)}
    contact = {}
    for key, (value, pattern, name, icon, colors) in found.items():
        value = readme_contact(Path("."), pattern) if value is None else value
        width = 0
        if value:
            svg, width = pill_svg(value if key == "email" else "@" + value, icon, colors)
            (out / name).write_text(svg, encoding="utf-8")
        contact[key] = (value, width)
    if "--sync-readme" in sys.argv:
        sync_readme(Path("."), s, contact)
    print(json.dumps(s | {k: v[0] for k, v in contact.items()}))


if __name__ == "__main__":
    main()