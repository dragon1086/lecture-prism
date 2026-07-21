"""Render deterministic README infographic PNG assets.

This is a maintainer utility, not a runtime dependency. The lecture demo path
still uses only the Python standard library.

The five architecture-heavy assets in ``docs/assets/readme`` are curated with
GPT Image 2 (strategy-to-kis, system-result, module guide, optional
integrations, and runtime map). Keep this renderer from overwriting those
reviewed images; regenerate only the deterministic learner aids below.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "readme"
W, H = 1600, 900
FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"

NAVY = "#17233b"
MUTED = "#53627d"
LINE = "#a9bfe8"
BLUE = "#2f66e8"
PURPLE = "#7046ee"
TEAL = "#0791a8"
GREEN = "#0c9274"
ORANGE = "#e07a00"
RED = "#cc334a"
AMBER = "#f2b64b"
PALE_BLUE = "#eaf3ff"
PALE_GREEN = "#eaf8f2"
PALE_PURPLE = "#f1edff"
PALE_ORANGE = "#fff2df"
PALE_RED = "#fff0f2"
WHITE = "#ffffff"


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


F = {
    "title": font(52),
    "subtitle": font(27),
    "h1": font(34),
    "h2": font(28),
    "body": font(22),
    "small": font(18),
    "tiny": font(15),
    "micro": font(12),
    "badge": font(20),
    "num": font(38),
}


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), "#f8fbff")
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(248 * (1 - t) + 232 * t)
        g = int(251 * (1 - t) + 246 * t)
        b = int(255 * (1 - t) + 250 * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    # soft side washes, not decorative blobs
    for x in range(W):
        t = x / W
        if t < 0.42:
            alpha = (0.42 - t) / 0.42
            color = (235, 247, 255)
        else:
            alpha = (t - 0.42) / 0.58
            color = (246, 239, 255)
        if alpha > 0:
            overlay = Image.new("RGBA", (1, H), (*color, int(55 * alpha)))
            img.paste(overlay.convert("RGB"), (x, 0), mask=overlay.split()[-1])
    return img, ImageDraw.Draw(img)


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> tuple[int, int]:
    if not text:
        return 0, 0
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in str(text).split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        line = ""
        for word in words:
            candidate = word if not line else f"{line} {word}"
            if text_size(draw, candidate, fnt)[0] <= max_w:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = word
            else:
                buf = ""
                for ch in word:
                    cand = buf + ch
                    if text_size(draw, cand, fnt)[0] <= max_w:
                        buf = cand
                    else:
                        lines.append(buf)
                        buf = ch
                line = buf
        if line:
            lines.append(line)
    return lines


def center_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    fnt: ImageFont.FreeTypeFont,
    fill: str = NAVY,
    line_gap: int = 6,
) -> None:
    x1, y1, x2, y2 = box
    lines = wrap(draw, text, fnt, x2 - x1 - 24)
    heights = [text_size(draw, line, fnt)[1] for line in lines]
    total = sum(heights) + line_gap * max(0, len(lines) - 1)
    y = y1 + (y2 - y1 - total) / 2
    for line, h in zip(lines, heights):
        w, _ = text_size(draw, line, fnt)
        draw.text((x1 + (x2 - x1 - w) / 2, y), line, font=fnt, fill=fill)
        y += h + line_gap


def left_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_w: int,
    fill: str = NAVY,
    line_gap: int = 6,
) -> int:
    x, y = xy
    for line in wrap(draw, text, fnt, max_w):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += text_size(draw, line, fnt)[1] + line_gap
    return y


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    outline: str,
    fill: str = WHITE,
    width: int = 3,
    radius: int = 28,
    shadow: bool = True,
) -> None:
    if shadow:
        sx1, sy1, sx2, sy2 = box
        draw.rounded_rectangle((sx1 + 8, sy1 + 12, sx2 + 8, sy2 + 12), radius, fill="#dbe5f1")
    draw.rounded_rectangle(box, radius, fill=fill, outline=outline, width=width)


def header(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    rounded(draw, (52, 38, 1548, 148), LINE, fill="#f6f8ff", width=2, radius=26, shadow=False)
    draw.text((62, 52), title, font=F["title"], fill=NAVY)
    draw.text((64, 113), subtitle, font=F["subtitle"], fill=MUTED)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int],
          fill: str = "#8fa8d2", width: int = 5, dashed: bool = False) -> None:
    x1, y1 = start
    x2, y2 = end
    if dashed:
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy)
        if dist == 0:
            return
        ux, uy = dx / dist, dy / dist
        pos = 0
        while pos < dist - 14:
            a = pos
            b = min(pos + 14, dist - 14)
            draw.line((x1 + ux * a, y1 + uy * a, x1 + ux * b, y1 + uy * b), fill=fill, width=width)
            pos += 26
    else:
        draw.line((x1, y1, x2, y2), fill=fill, width=width)
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 16
    pts = [
        (x2, y2),
        (x2 - size * math.cos(ang - 0.45), y2 - size * math.sin(ang - 0.45)),
        (x2 - size * math.cos(ang + 0.45), y2 - size * math.sin(ang + 0.45)),
    ]
    draw.polygon(pts, fill=fill)


def segment(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int],
            fill: str = "#8fa8d2", width: int = 5, dashed: bool = False) -> None:
    x1, y1 = start
    x2, y2 = end
    if dashed:
        dx, dy = x2 - x1, y2 - y1
        dist = math.hypot(dx, dy)
        if dist == 0:
            return
        ux, uy = dx / dist, dy / dist
        pos = 0
        while pos < dist:
            a = pos
            b = min(pos + 14, dist)
            draw.line((x1 + ux * a, y1 + uy * a, x1 + ux * b, y1 + uy * b), fill=fill, width=width)
            pos += 26
    else:
        draw.line((x1, y1, x2, y2), fill=fill, width=width)


def path_arrow(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]],
               fill: str = "#8fa8d2", width: int = 5, dashed: bool = False) -> None:
    if len(points) < 2:
        return
    for start, end in zip(points[:-2], points[1:-1]):
        segment(draw, start, end, fill, width, dashed)
    arrow(draw, points[-2], points[-1], fill, width, dashed)


def circle(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, color: str, text: str) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color, outline=WHITE, width=4)
    center_text(draw, (cx - r, cy - r + 1, cx + r, cy + r + 1), text, F["num"], WHITE)


def pill(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str,
         color: str, fill: str = WHITE, fnt: ImageFont.FreeTypeFont | None = None) -> None:
    rounded(draw, box, color, fill=fill, width=2, radius=20, shadow=False)
    center_text(draw, box, text, fnt or F["badge"], color)


def save(img: Image.Image, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / name, "PNG", optimize=True)


def card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], color: str,
         title: str, body: str, tag: str | None = None, fill: str = WHITE) -> None:
    rounded(draw, box, color, fill=fill)
    x1, y1, x2, y2 = box
    if tag:
        pill(draw, (x1 + 22, y1 + 22, x1 + 150, y1 + 66), tag, color, fill="#f8fbff", fnt=F["small"])
        left_text(draw, (x1 + 170, y1 + 24), title, F["h2"], x2 - x1 - 190)
    else:
        center_text(draw, (x1 + 24, y1 + 24, x2 - 24, y1 + 82), title, F["h2"])
    draw.line((x1 + 32, y1 + 104, x2 - 32, y1 + 104), fill="#d8e1ef", width=2)
    center_text(draw, (x1 + 34, y1 + 116, x2 - 34, y2 - 26), body, F["body"], MUTED)


def hero_learning_map() -> None:
    img, draw = canvas()
    header(draw, "강의 실습 한눈에 보기", "전략을 말하면 에이전트가 실행·수정·검증까지 돕는 학습 흐름")
    steps = [
        (70, BLUE, "1", "전략 입력", "학생", "자연어로 아이디어 설명", "에이전트", "진입·분석·청산·리스크 중 분류", "산출물", "MY_STRATEGY 초안"),
        (360, PURPLE, "2", "프롬프트 요청", "학생", "명령어 대신 요청문 붙여넣기", "에이전트", "수정 범위와 검증 계획 작성", "산출물", "한 파일 중심 작업 계획"),
        (650, TEAL, "3", "데모 실행", "학생", "API 키 없이 첫 실행 확인", "에이전트", "후보→분석→매매→회고 완주", "산출물", "DB·보고서·로그"),
        (940, ORANGE, "4", "결과 해석", "학생", "보고서에서 납득 안 되는 점 찾기", "에이전트", "규칙/프롬프트/리스크 값 보정", "산출물", "전략 수정안"),
        (1230, GREEN, "5", "확장 선택", "학생", "더미·실데이터·리서치·모의 선택", "에이전트", ".env와 설정만 바꿔 재검증", "산출물", "반복 가능한 실습 루프"),
    ]
    for i, (x, color, num, title, a_label, a_text, b_label, b_text, c_label, c_text) in enumerate(steps):
        box = (x, 220, x + 270, 655)
        rounded(draw, box, color, fill=WHITE, width=3, radius=22)
        circle(draw, x + 44, 258, 26, color, num)
        draw.text((x + 82, 238), title, font=F["h2"], fill=NAVY)
        y = 306
        for label, text in [(a_label, a_text), (b_label, b_text), (c_label, c_text)]:
            pill(draw, (x + 24, y, x + 102, y + 30), label, color, fill="#f8fbff", fnt=F["micro"])
            center_text(draw, (x + 112, y - 3, x + 250, y + 52), text, F["tiny"], MUTED, line_gap=2)
            y += 98
            if y < 600:
                draw.line((x + 28, y - 30, x + 242, y - 30), fill="#dbe5f1", width=1)
        if i < len(steps) - 1:
            arrow(draw, (x + 274, 438), (steps[i + 1][0] - 8, 438), "#9cafcf", width=4)
    bottom = [
        (70, 730, 450, 824, GREEN, "첫 성공", "키 없이 mock으로 완주"),
        (505, 730, 885, 824, PURPLE, "학습 방식", "터미널 명령보다 에이전트 프롬프트"),
        (940, 730, 1320, 824, BLUE, "확장 방식", ".env/API 키가 있으면 해당 기능만 켜짐"),
        (1375, 730, 1530, 824, RED, "안전", "실주문\n기본 차단"),
    ]
    for x1, y1, x2, y2, color, title, body in bottom:
        rounded(draw, (x1, y1, x2, y2), color, fill=WHITE, width=3, radius=18)
        draw.text((x1 + 24, y1 + 18), title, font=F["small"], fill=color)
        center_text(draw, (x1 + 20, y1 + 42, x2 - 20, y2 - 10), body, F["small"], NAVY, line_gap=2)
    save(img, "hero-learning-map.png")


def five_minute_start() -> None:
    img, draw = canvas()
    header(draw, "처음 5분 루트", "설치·OAuth·Git보다 먼저 “기본 데모가 돌아간다”를 확인합니다")
    steps = [
        (70, BLUE, "1", "폴더 열기", "확인", "README·강의 문서·docs가 보임", "성공 신호", "에이전트가 프로젝트 구조 설명", "막히면", "현재 폴더를 다시 지정"),
        (380, PURPLE, "2", "Python 확인", "확인", "3.10 이상 또는 가상환경", "성공 신호", "실행할 Python 경로 확인", "막히면", "환경 연결만 요청"),
        (690, TEAL, "3", "데모 실행", "확인", "API 키 없이 main.py 완주", "성공 신호", "후보·분석·매매·회고 출력", "막히면", "mock 폴백으로 재시도"),
        (1000, ORANGE, "4", "결과 확인", "확인", "prism.db와 reports 생성", "성공 신호", "보고서·대시보드에서 확인", "막히면", "누락 파일을 찾아달라고 요청"),
        (1310, GREEN, "5", "다음 수정", "확인", "MY_STRATEGY.md에 내 이론 작성", "성공 신호", "트랙 A/B/C/D 중 하나 수정", "막히면", "한 파일만 바꾸게 요청"),
    ]
    for i, (x, color, num, title, l1, t1, l2, t2, l3, t3) in enumerate(steps):
        box = (x, 224, x + 250, 640)
        rounded(draw, box, color, fill=WHITE, width=3, radius=22)
        circle(draw, x + 42, 258, 25, color, num)
        draw.text((x + 78, 238), title, font=F["body"], fill=NAVY)
        y = 315
        for label, text in [(l1, t1), (l2, t2), (l3, t3)]:
            pill(draw, (x + 20, y, x + 96, y + 30), label, color, fill="#f8fbff", fnt=F["micro"])
            center_text(draw, (x + 106, y - 4, x + 230, y + 58), text, F["tiny"], MUTED, line_gap=2)
            y += 98
        if i < len(steps) - 1:
            arrow(draw, (x + 254, 432), (x + 300, 432), "#9cafcf", width=4)
    rounded(draw, (130, 706, 1470, 822), "#15243d", fill="#15243d", width=0, radius=24, shadow=False)
    draw.text((170, 724), "그대로 붙여넣을 첫 프롬프트", font=F["h2"], fill=WHITE)
    draw.text((170, 772), "“강의 실습 파이프라인을 API 키 없이 데모 모드로 실행하고, DB·보고서·대시보드 결과까지 확인해줘.”", font=F["body"], fill="#dce6f6")
    save(img, "five-minute-start.png")


def pipeline_map() -> None:
    img, draw = canvas()
    header(draw, "강의용 투자 파이프라인", "후보 선정 → 6섹션 분석 → 시뮬레이션 매매 → 회고 → 저장 → 화면 확인")
    items = [
        (42, BLUE, "screening.py", "후보 선정", "입력", "전체 종목/더미 유니버스", "처리", "거래량·시총·모멘텀 필터", "출력", "후보 N개", "수정", "진입 조건"),
        (300, PURPLE, "analysis.py", "6섹션 분석", "입력", "후보 + 가격/뉴스", "처리", "6개 관점\n요약", "출력", "BUY·HOLD\nPASS", "수정", "분석 프롬프트"),
        (558, TEAL, "trading.py", "매매 판단", "입력", "분석 점수/현재가", "처리", "수량·손절\n목표·게이트", "출력", "모의 주문/차단", "수정", "청산·리스크"),
        (816, ORANGE, "feedback.py", "회고", "입력", "매매 결과\n판단 근거", "처리", "잘한 점·고칠 점 추출", "출력", "다음 전략 힌트", "수정", "교훈 규칙"),
        (1074, GREEN, "db.py", "저장소", "입력", "분석·매매·회고", "처리", "SQLite 저장/조회", "출력", "prism.db", "수정", "보통 건드리지 않음"),
        (1332, RED, "dashboard.py", "확인 화면", "입력", "DB + reports", "처리", "카드·표\n보고서 표시", "출력", "눈으로 확인", "수정", "대시보드"),
    ]
    for i, (x, color, tag, title, l1, t1, l2, t2, l3, t3, l4, t4) in enumerate(items):
        rounded(draw, (x, 228, x + 226, 638), color, fill=WHITE, width=3, radius=22)
        pill(draw, (x + 14, 254, x + 212, 300), tag, color, fill="#f8fbff", fnt=F["small"])
        center_text(draw, (x + 18, 318, x + 208, 356), title, F["body"])
        y = 378
        for label, text in [(l1, t1), (l2, t2), (l3, t3), (l4, t4)]:
            pill(draw, (x + 18, y, x + 72, y + 25), label, color, fill="#f8fbff", fnt=F["micro"])
            center_text(draw, (x + 80, y - 5, x + 208, y + 43), text, F["tiny"], MUTED, line_gap=1)
            y += 58
        if i < len(items) - 1:
            arrow(draw, (x + 229, 430), (items[i + 1][0] - 8, 430), "#8fa8d2", width=4)
    path_arrow(draw, [(930, 650), (930, 672), (420, 672), (420, 640)], GREEN, width=5)
    draw.text((500, 696), "피드백 루프: 회고는 다음 전략 수정의 재료가 됩니다", font=F["h2"], fill=GREEN)
    bottom = [
        ((210, 748, 610, 820), GREEN, "기본 성공", "simulation + DB + Markdown 보고서"),
        ((640, 748, 1040, 820), PURPLE, "수강생 수정", "A 진입 / B 분석 / C 청산 / D 리스크 중 하나"),
        ((1070, 748, 1390, 820), RED, "안전 기준", "실제 주문은 별도 플래그 전까지 차단"),
    ]
    for box, color, title, body in bottom:
        rounded(draw, box, color, fill=WHITE, width=2, radius=16, shadow=False)
        draw.text((box[0] + 22, box[1] + 13), title, font=F["small"], fill=color)
        center_text(draw, (box[0] + 18, box[1] + 36, box[2] - 18, box[3] - 8), body, F["small"], NAVY, line_gap=2)
    save(img, "pipeline-map.png")


def module_guide() -> None:
    img, draw = canvas()
    header(draw, "파일별 역할 지도", "처음부터 전체 코드를 다 읽지 말고, 바꾸고 싶은 목적에 맞는 파일 하나부터 봅니다")
    cards = [
        ((76, 220, 514, 455), BLUE, "진입 조건", "screening.py", "후보를 줄이는 필터", "거래량·시총·상승률", "후보 N개가 바뀜"),
        ((576, 220, 1014, 455), PURPLE, "분석 관점", "analysis.py", "6섹션 판단과 의견", "기술·뉴스·전략 프롬프트", "BUY/HOLD/PASS 문장"),
        ((1076, 220, 1514, 455), TEAL, "매매 규칙", "trading.py", "살지·얼마나·언제 나갈지", "손절·익절·리스크", "주문/차단 기록"),
        ((76, 492, 514, 727), ORANGE, "회고", "feedback.py", "판단 결과에서 교훈 추출", "교훈 문장·개선 힌트", "다음 전략 재료"),
        ((576, 492, 1014, 727), GREEN, "저장소", "db.py", "분석·매매·회고 저장", "보통 직접 수정 안 함", "prism.db 조회"),
        ((1076, 492, 1514, 727), RED, "확인 화면", "dashboard.py", "보고서를 눈으로 점검", "표·카드·대시보드", "누락/이상값 발견"),
    ]
    for box, color, title, tag, role, edit, signal in cards:
        rounded(draw, box, color, fill=WHITE, width=3, radius=22)
        x1, y1, x2, y2 = box
        pill(draw, (x1 + 22, y1 + 22, x1 + 158, y1 + 62), tag, color, fill="#f8fbff", fnt=F["small"])
        draw.text((x1 + 182, y1 + 26), title, font=F["h2"], fill=NAVY)
        draw.line((x1 + 32, y1 + 84, x2 - 32, y1 + 84), fill="#d8e1ef", width=2)
        y = y1 + 102
        for label, text in [("역할", role), ("수정", edit), ("확인", signal)]:
            pill(draw, (x1 + 34, y, x1 + 96, y + 24), label, color, fill="#f8fbff", fnt=F["micro"])
            center_text(draw, (x1 + 108, y - 5, x2 - 34, y + 36), text, F["tiny"], MUTED, line_gap=1)
            y += 43
    rounded(draw, (150, 790, 1450, 852), "#15243d", fill="#15243d", width=0, radius=20, shadow=False)
    center_text(draw, (180, 798, 1420, 842), "막히면 “내가 바꾸고 싶은 건 진입·분석·청산·리스크 중 무엇인지 먼저 정리해줘”라고 요청하세요.", F["body"], WHITE)
    save(img, "module-guide.png")


def optional_integrations_safety() -> None:
    img, draw = canvas()
    header(draw, "연동은 나중에 선택", "기본 실습은 더미 폴백으로 시작하고, 준비된 사람만 단계적으로 실제 도구를 켭니다")
    table = (58, 222, 1542, 704)
    rounded(draw, table, LINE, fill=WHITE, width=2, radius=20, shadow=False)
    x_edges = [58, 226, 486, 746, 1006, 1266, 1542]
    y_edges = [222, 276, 348, 430, 512, 594, 704]
    for x in x_edges[1:-1]:
        draw.line((x, table[1], x, table[3]), fill="#dbe5f1", width=2)
    for y in y_edges[1:-1]:
        draw.line((table[0], y, table[2], y), fill="#dbe5f1", width=2)
    headers = [
        ("구분", MUTED),
        ("mock\n기본값", GREEN),
        ("real_data\n실데이터", BLUE),
        ("research\n리서치", PURPLE),
        ("paper\n모의투자", ORANGE),
        ("live\n실전투자", RED),
    ]
    for i, (title, color) in enumerate(headers):
        center_text(draw, (x_edges[i] + 8, 232, x_edges[i + 1] - 8, 266), title, F["small"], color, line_gap=2)
    row_labels = ["설정 위치", "데이터", "보고서", "매매", "안전/폴백"]
    row_values = [
        [".env\nPROFILE=mock", ".env\nDATA=real", ".env\nREPORT=research\nAPI 키 선택", "kis_devlp.yaml\nmode=demo", ".env + kis_devlp\nmode=real"],
        ["더미 가격\n항상 동작", "yfinance\nkospi-kosdaq", "실가격 +\n뉴스/웹 맥락", "실가격 +\n브로커 조회", "실계좌 데이터\n가능 범위"],
        ["lite\n규칙/더미 분석", "lite\n실가격 요약", "research\nPerplexity·Firecrawl", "research\n모의계좌 점검", "research\n운영 보고서"],
        ["simulation\n가상 체결", "simulation\n가상 체결", "simulation\n가상 체결", "demo\n모의 주문", "real*\n이중 플래그 필요"],
        ["키 없어도 완주", "실패하면 mock", "LLM 실패 시\n규칙 분석", "토큰 실패 시\n주문 안 함", "enable + allow\n없으면 live_blocked"],
    ]
    for r, label in enumerate(row_labels):
        y1, y2 = y_edges[r + 1], y_edges[r + 2]
        center_text(draw, (x_edges[0] + 12, y1, x_edges[1] - 12, y2), label, F["small"], NAVY)
        for c, text in enumerate(row_values[r]):
            color = [GREEN, BLUE, PURPLE, ORANGE, RED][c]
            center_text(draw, (x_edges[c + 1] + 10, y1 + 4, x_edges[c + 2] - 10, y2 - 4), text, F["tiny"], color if r == 3 else MUTED, line_gap=2)
    choices = [
        ((92, 738, 390, 820), GREEN, "초급", "mock만 켜도 보고서·DB까지 완주"),
        ((430, 738, 728, 820), BLUE, "데이터 욕심", "실가격은 켜되 주문은 simulation 유지"),
        ((768, 738, 1066, 820), PURPLE, "보고서 욕심", "Perplexity·Firecrawl은 보고서 품질만 확장"),
        ((1106, 738, 1508, 820), RED, "거래 욕심", "demo→real 순서, live는 두 플래그 없으면 차단"),
    ]
    for box, color, title, body in choices:
        rounded(draw, box, color, fill="#fbfdff", width=2, radius=18, shadow=False)
        draw.text((box[0] + 22, box[1] + 15), title, font=F["small"], fill=color)
        center_text(draw, (box[0] + 18, box[1] + 38, box[2] - 18, box[3] - 8), body, F["small"], NAVY, line_gap=2)
    save(img, "optional-integrations-safety.png")


def strategy_harness_lite() -> None:
    img, draw = canvas()
    header(draw, "전략 하네스", "두루뭉술한 전략 설명을 질문·수정·검증 가능한 작업으로 쪼개는 안전장치")
    top = [
        (76, ORANGE, "1", "전략 설명", "애매해도 입력", "예: 거래량 터지고\n강한 종목"),
        (380, PURPLE, "2", "분류", "A/B/C/D 선택", "진입·분석·청산·리스크\n중 하나"),
        (686, BLUE, "3", "최소 수정", "한 파일 중심", "상수·프롬프트·규칙을\n작게 변경"),
        (992, GREEN, "4", "검증", "데모 완주", "main.py·DB·보고서\n결과 확인"),
        (1298, RED, "5", "안전", "실주문 차단", "모의 결과만 리뷰\nlive는 별도 승인"),
    ]
    for x, color, num, title, subtitle, body in top:
        rounded(draw, (x, 232, x + 244, 480), color, fill=WHITE, width=3)
        circle(draw, x + 50, 274, 26, color, num)
        center_text(draw, (x + 90, 248, x + 224, 306), title, F["body"])
        center_text(draw, (x + 42, 318, x + 202, 344), subtitle, F["small"], color)
        draw.line((x + 28, 360, x + 216, 360), fill="#d8e1ef", width=2)
        center_text(draw, (x + 34, 382, x + 210, 454), body, F["small"], MUTED, line_gap=2)
    tracks = [
        ((96, 550, 416, 835), BLUE, "A", "진입 조건", "screening.py", "후보를 좁히는 규칙", "거래량·상승률·시총", "후보 목록 변화"),
        ((472, 550, 792, 835), PURPLE, "B", "분석 관점", "analysis.py", "AI가 보는 체크리스트", "기술·뉴스·전략 문장", "투자의견 변화"),
        ((848, 550, 1168, 835), ORANGE, "C", "청산 규칙", "trading.py", "익절·손절·보유 기간", "목표가·손절·트레일링", "청산 사유 변화"),
        ((1224, 550, 1544, 835), RED, "D", "리스크", "trading.py", "한 번에 얼마나 살지", "포지션 크기·최대 손실", "수량/차단 변화"),
    ]
    for box, color, letter, title, file_name, role, edit, signal in tracks:
        rounded(draw, box, color, fill=WHITE, width=3)
        circle(draw, box[0] + 45, box[1] + 52, 25, color, letter)
        draw.text((box[0] + 88, box[1] + 30), title, font=F["h2"], fill=NAVY)
        draw.text((box[0] + 88, box[1] + 76), file_name, font=F["body"], fill=color)
        y = box[1] + 132
        for label, text in [("역할", role), ("수정", edit), ("검증", signal)]:
            pill(draw, (box[0] + 28, y, box[0] + 88, y + 26), label, color, fill="#f8fbff", fnt=F["micro"])
            center_text(draw, (box[0] + 100, y - 4, box[2] - 22, y + 42), text, F["tiny"], MUTED, line_gap=2)
            y += 50
    save(img, "strategy-harness-lite.png")


def submission_security() -> None:
    img, draw = canvas()
    header(draw, "제출 전 보안 체크", "GitHub에는 학습 코드만, 키·토큰·DB·실계좌 설정은 로컬에만 남깁니다")
    left = (80, 220, 740, 700)
    right = (860, 220, 1520, 700)
    rounded(draw, left, RED, fill=WHITE, width=3)
    rounded(draw, right, GREEN, fill=WHITE, width=3)
    draw.text((120, 258), "절대 올리지 않기", font=F["h1"], fill=RED)
    draw.text((900, 258), "올려도 되는 것", font=F["h1"], fill=GREEN)
    bad = [".env / 실제 API 키", "mcp_agent.secrets.yaml", "kis_devlp.yaml / KIS 토큰", "prism.db / 실행 DB", "*.log / 개인 실행 로그", "reports/ 개인 분석 보고서"]
    good = ["README와 docs 문서", "screening.py / analysis.py 수정", "trading.py 데모 규칙 수정", "MY_STRATEGY.md 예시(비밀 제외)", "테스트와 검증 결과 요약"]
    y = 328
    for item in bad:
        pill(draw, (120, y, 690, y + 48), f"✕  {item}", RED, fill=PALE_RED, fnt=F["body"])
        y += 61
    y = 328
    for item in good:
        pill(draw, (900, y, 1470, y + 48), f"✓  {item}", GREEN, fill=PALE_GREEN, fnt=F["body"])
        y += 61
    rounded(draw, (170, 735, 1430, 830), "#15243d", fill="#15243d", width=0, radius=24, shadow=False)
    center_text(draw, (210, 748, 1390, 817), "Git 명령도 직접 치지 않아도 됩니다. “변경 파일과 비밀값 제외 여부를 확인해줘”라고 에이전트에게 요청하세요.", F["body"], WHITE)
    save(img, "submission-security.png")


def runtime_architecture_map() -> None:
    img, draw = canvas()
    header(draw, "옵션별 전체 아키텍처", ".env가 데이터·리서치·매매 깊이를 고르고, 실패하면 더 안전한 단계로 자동 폴백합니다")

    # Control surface
    rounded(draw, (48, 172, 1548, 228), LINE, fill="#fbfdff", width=2, radius=16, shadow=False)
    control_items = [
        ((70, 184, 430, 216), ".env", "PROFILE · DATA · LLM · REPORT · TRADE", BLUE),
        ((455, 184, 905, 216), "API 키", "OPENAI · PERPLEXITY · FIRECRAWL · KRX/Kakao", PURPLE),
        ((930, 184, 1268, 216), "KIS 설정", "kis_devlp.yaml: demo / real 계좌", ORANGE),
        ((1295, 184, 1528, 216), "안전", "실주문은 이중 플래그 필요", RED),
    ]
    for box, title, desc, color in control_items:
        x1, y1, x2, y2 = box
        pill(draw, (x1, y1, x1 + 86, y2), title, color, fill="#f8fbff", fnt=F["tiny"])
        center_text(draw, (x1 + 94, y1, x2, y2), desc, F["micro"], MUTED, line_gap=2)

    # Profile matrix
    rounded(draw, (48, 248, 375, 790), BLUE, fill=WHITE, width=3, radius=18)
    draw.text((72, 268), "프로필별 동작표", font=F["h2"], fill=NAVY)
    cols = [("프로필", 72), ("데이터", 150), ("보고서", 230), ("매매", 305)]
    for label, x in cols:
        draw.text((x, 315), label, font=F["micro"], fill=MUTED)
    draw.line((70, 340, 352, 340), fill="#d5deeb", width=2)
    rows = [
        ("mock", "더미", "lite", "simulation", GREEN),
        ("real_data", "실가격", "lite", "simulation", BLUE),
        ("research", "실가격+", "research", "simulation", PURPLE),
        ("paper", "실가격+", "research", "demo", ORANGE),
        ("live", "실가격+", "research", "real*", RED),
    ]
    y = 360
    for name, data, report, trade, color in rows:
        pill(draw, (70, y, 142, y + 30), name, color, fill="#f8fbff", fnt=F["micro"])
        draw.text((154, y + 7), data, font=F["micro"], fill=NAVY)
        draw.text((232, y + 7), report, font=F["micro"], fill=NAVY)
        draw.text((306, y + 7), trade, font=F["micro"], fill=NAVY)
        y += 52
    draw.line((70, 625, 352, 625), fill="#d5deeb", width=2)
    notes = [
        ("기본값", "키가 없어도 즉시 완주", GREEN),
        ("선택 키", "있으면 해당 기능만 확장", PURPLE),
        ("실전", "enable + allow 없으면 차단", RED),
    ]
    y = 650
    for label, desc, color in notes:
        pill(draw, (70, y, 132, y + 28), label, color, fill="#f8fbff", fnt=F["micro"])
        draw.text((144, y + 7), desc, font=F["micro"], fill=MUTED)
        y += 38

    # Main pipeline
    stage_y1, stage_y2 = 268, 388
    stages = [
        ((425, stage_y1, 550, stage_y2), BLUE, "1 후보", "screening.py\n데모 유니버스\npykrx 선택"),
        ((585, stage_y1, 730, stage_y2), TEAL, "2 데이터", "data_source.py\n가격·거래량\n뉴스·지수"),
        ((765, stage_y1, 930, stage_y2), PURPLE, "3 분석", "analysis.py\n6섹션 요약\nBUY/HOLD/PASS"),
        ((965, stage_y1, 1120, stage_y2), ORANGE, "4 매매", "trading.py\n수량·손절·목표\n주문 게이트"),
        ((1155, stage_y1, 1295, stage_y2), GREEN, "5 회고", "feedback.py\n매매일지\n개선 힌트"),
        ((1330, stage_y1, 1498, stage_y2), RED, "6 확인", "db.py + reports\n대시보드\nMarkdown"),
    ]
    for i, (box, color, title, body) in enumerate(stages):
        rounded(draw, box, color, fill=WHITE, width=3, radius=18)
        center_text(draw, (box[0] + 8, box[1] + 10, box[2] - 8, box[1] + 42), title, F["small"])
        center_text(draw, (box[0] + 8, box[1] + 46, box[2] - 8, box[3] - 8), body, F["micro"], MUTED, line_gap=4)
        if i < len(stages) - 1:
            arrow(draw, (box[2] + 7, 328), (stages[i + 1][0][0] - 8, 328), "#8fa8d2", width=4)

    # Data lane
    rounded(draw, (415, 430, 770, 608), TEAL, fill="#fbfdff", width=2, radius=18, shadow=False)
    draw.text((435, 448), "데이터 모세혈관", font=F["body"], fill=TEAL)
    data_boxes = [
        ((435, 492, 535, 572), GREEN, "mock", "항상\n동작"),
        ((550, 492, 650, 572), BLUE, "yfinance", "가격\n거래량\n뉴스"),
        ((665, 492, 755, 572), TEAL, "kospi-\nkosdaq", "KRX\nKakao"),
    ]
    for box, color, title, body in data_boxes:
        rounded(draw, box, color, fill=WHITE, width=2, radius=14, shadow=False)
        center_text(draw, (box[0] + 4, box[1] + 6, box[2] - 4, box[1] + 30), title, F["micro"], color)
        center_text(draw, (box[0] + 4, box[1] + 34, box[2] - 4, box[3] - 4), body, F["micro"], MUTED, line_gap=2)
        arrow(draw, ((box[0] + box[2]) // 2, 492), (660, 388), color, width=3, dashed=True)

    # Research lane
    rounded(draw, (800, 430, 1165, 608), PURPLE, fill="#fbfdff", width=2, radius=18, shadow=False)
    draw.text((820, 448), "분석·리서치 확장", font=F["body"], fill=PURPLE)
    research_boxes = [
        ((820, 492, 930, 572), PURPLE, "OpenAI\nOAuth", "분석 문장\n보강"),
        ((946, 492, 1056, 572), PURPLE, "Perplexity", "최신 뉴스\n시장 맥락"),
        ((1072, 492, 1156, 572), PURPLE, "Firecrawl", "웹\n수집"),
    ]
    for box, color, title, body in research_boxes:
        rounded(draw, box, color, fill=WHITE, width=2, radius=14, shadow=False)
        center_text(draw, (box[0] + 4, box[1] + 6, box[2] - 4, box[1] + 34), title, F["micro"], color)
        center_text(draw, (box[0] + 4, box[1] + 38, box[2] - 4, box[3] - 4), body, F["micro"], MUTED, line_gap=2)
        arrow(draw, ((box[0] + box[2]) // 2, 492), (850, 388), color, width=3, dashed=True)

    # Broker lane
    rounded(draw, (1205, 430, 1518, 608), ORANGE, fill="#fbfdff", width=2, radius=18, shadow=False)
    draw.text((1225, 448), "브로커·주문 안전", font=F["body"], fill=ORANGE)
    broker_boxes = [
        ((1225, 492, 1316, 572), ORANGE, "KIS", "demo/real\nkis_devlp"),
        ((1330, 492, 1412, 572), ORANGE, "키움", "REST\n토큰"),
        ((1426, 492, 1500, 572), RED, "게이트", "enable\nallow"),
    ]
    for box, color, title, body in broker_boxes:
        rounded(draw, box, color, fill=WHITE, width=2, radius=14, shadow=False)
        center_text(draw, (box[0] + 4, box[1] + 6, box[2] - 4, box[1] + 30), title, F["micro"], color)
        center_text(draw, (box[0] + 4, box[1] + 34, box[2] - 4, box[3] - 4), body, F["micro"], MUTED, line_gap=2)
        arrow(draw, ((box[0] + box[2]) // 2, 492), (1042, 388), color, width=3, dashed=True)

    # Outputs and feedback loop
    rounded(draw, (415, 635, 1518, 788), GREEN, fill=WHITE, width=2, radius=18)
    draw.text((435, 654), "결과가 남는 곳과 다시 쓰이는 곳", font=F["body"], fill=GREEN)
    outputs = [
        ((435, 700, 568, 755), GREEN, "prism.db", "분석·매매·교훈"),
        ((590, 700, 722, 755), GREEN, "reports/*.md", "6섹션 보고서"),
        ((744, 700, 876, 755), RED, "dashboard", "눈으로 확인"),
        ((898, 700, 1030, 755), ORANGE, "MY_STRATEGY", "다음 수정"),
        ((1052, 700, 1184, 755), BLUE, "tests", "회귀 검증"),
        ((1206, 700, 1492, 755), PURPLE, "수정 루프", "보고서/대시보드 확인 → 전략 보완 → mock에서 재검증"),
    ]
    for box, color, title, body in outputs:
        rounded(draw, box, color, fill="#fbfdff", width=2, radius=14, shadow=False)
        center_text(draw, (box[0] + 4, box[1] + 4, box[2] - 4, box[1] + 27), title, F["micro"], color)
        center_text(draw, (box[0] + 6, box[1] + 30, box[2] - 6, box[3] - 4), body, F["micro"], MUTED, line_gap=2)
    path_arrow(draw, [(965, 635), (965, 620), (790, 620), (790, 410), (835, 388)], GREEN, width=4, dashed=True)

    # Fallback ladder
    rounded(draw, (48, 812, 1548, 866), GREEN, fill=PALE_GREEN, width=2, radius=18, shadow=False)
    draw.text((75, 826), "폴백 규칙", font=F["small"], fill=GREEN)
    fallback = (
        "API 키 없음 → 해당 도구만 끔  |  패키지/네트워크 실패 → mock 데이터  |  LLM 실패 → 규칙/더미 분석  |  "
        "브로커 플래그 없음 → live_blocked  |  기본 성공 기준 → simulation + DB + Markdown 보고서"
    )
    draw.text((165, 829), fallback, font=F["tiny"], fill=NAVY)
    save(img, "runtime-architecture-map.png")


def main() -> None:
    hero_learning_map()
    five_minute_start()
    pipeline_map()
    strategy_harness_lite()
    submission_security()


if __name__ == "__main__":
    main()
