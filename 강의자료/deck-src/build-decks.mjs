import fs from "node:fs";
import path from "node:path";

const sourceRoot = import.meta.dirname;
const lectureRoot = path.resolve(sourceRoot, "..");
const manifestPath = path.join(sourceRoot, "deck-manifest.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

const sectionPattern = /<section class="slide[^>]*>[\s\S]*?<\/section>/g;
const addSlideMeta = (section, slide) => {
  const guide = slide.guideAudience === "instructor"
    ? `강사 자료 → ${slide.promptId} · 강사용 진행 스크립트의 해당 블록을 사용합니다`
    : slide.promptId
    ? `수강생 자료 → ${slide.promptId} · 해당 번호의 text 블록 전체를 붙여넣으세요`
    : null;
  const withId = section.replace(
    /^<section\s+class=/,
    `<section data-slide-id="${slide.id}" class=`
  );
  return withId.replace(
    /<div class="pagenum">[\s\S]*?<\/div>\s*<\/section>$/,
    `${guide ? `<div class="prompt-guide">${guide}</div>` : ""}<div class="pagenum"></div>\n</section>`
  );
};

const writeIndex = (deckKey, deck) => {
  const rows = deck.modules.flatMap((module) =>
    module.slides.map((slide) =>
      `| ${slide.id} | ${slide.promptId || "—"} | \`${module.file}\` | ${slide.title.replaceAll("|", "\\|")} |`
    )
  );
  const text = [
    `# ${deckKey === "part3" ? "파트 3" : "파트 4"} 슬라이드 인덱스`,
    "",
    "> 이 표와 `deck-manifest.json`은 유지보수용 길잡이입니다. 수강생에게 보이는 발표 파일은 상위 폴더의 HTML입니다.",
    "",
    "| 슬라이드 ID | 연결 프롬프트 | 수정할 원본 모듈 | 화면 제목 |",
    "| --- | --- | --- | --- |",
    ...rows,
    ""
  ].join("\n");
  fs.writeFileSync(path.join(sourceRoot, `${deckKey}-index.md`), text);
};

for (const [deckKey, deck] of Object.entries(manifest.decks)) {
  const head = fs.readFileSync(path.join(sourceRoot, deck.head), "utf8");
  const tail = fs.readFileSync(path.join(sourceRoot, deck.tail), "utf8");
  const sections = [];

  for (const module of deck.modules) {
    const sourcePath = path.join(sourceRoot, module.file);
    const source = fs.readFileSync(sourcePath, "utf8");
    const found = [...source.matchAll(sectionPattern)].map((match) => match[0]);
    if (found.length !== module.slides.length) {
      throw new Error(
        `${module.file}: expected ${module.slides.length} slides, found ${found.length}`
      );
    }
    found.forEach((section, index) => sections.push(addSlideMeta(section, module.slides[index])));
  }

  const output = [
    "<!-- GENERATED FILE. Edit 강의자료/deck-src modules, then run: node 강의자료/deck-src/build-decks.mjs -->",
    head.trimEnd(),
    sections.join("\n\n"),
    tail.trimStart()
  ].join("\n\n");
  fs.writeFileSync(path.join(lectureRoot, deck.output), `${output.trimEnd()}\n`);
  writeIndex(deckKey, deck);
  console.log(`${deckKey}: ${sections.length} slides -> 강의자료/${deck.output}`);
}
