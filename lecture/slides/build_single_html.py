"""Reveal.js 발표 자료를 외부 의존성이 없는 단일 HTML로 묶는다."""

from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "사전오픈_세미나_슬라이드.html"
OUTPUT = ROOT / "사전오픈_세미나_슬라이드_단일파일.html"


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build() -> Path:
    html = SOURCE.read_text(encoding="utf-8")

    styles = [
        ROOT / "vendor/reveal.js/dist/reveal.css",
        ROOT / "vendor/reveal.js/dist/theme/black.css",
    ]
    for stylesheet in styles:
        relative = stylesheet.relative_to(ROOT).as_posix()
        link = f'<link rel="stylesheet" href="{relative}">'
        css = stylesheet.read_text(encoding="utf-8")
        html = html.replace(link, f"<style>\n{css}\n</style>")

    script_path = ROOT / "vendor/reveal.js/dist/reveal.js"
    script_tag = f'<script src="{script_path.relative_to(ROOT).as_posix()}"></script>'
    javascript = script_path.read_text(encoding="utf-8").replace("</script>", "<\\/script>")
    html = html.replace(script_tag, f"<script>\n{javascript}\n</script>")

    def replace_image(match: re.Match[str]) -> str:
        prefix, src = match.groups()
        if src.startswith(("data:", "http://", "https://")):
            return match.group(0)
        image_path = ROOT / src
        if not image_path.is_file():
            raise FileNotFoundError(f"이미지를 찾을 수 없습니다: {image_path}")
        return f'{prefix}src="{_data_uri(image_path)}"'

    html = re.sub(r'(<img\b[^>]*?\s)src="([^"]+)"', replace_image, html)
    html = html.replace(
        "<head>",
        "<head>\n<!-- 외부 파일 없이 실행되는 패스트캠퍼스 담당자 전달용 단일 HTML -->",
        1,
    )
    OUTPUT.write_text(html, encoding="utf-8")
    return OUTPUT


if __name__ == "__main__":
    result = build()
    print(result)
    print(f"{result.stat().st_size / 1024 / 1024:.2f} MiB")
