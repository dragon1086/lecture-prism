import fs from "node:fs";
import path from "node:path";

const sourceRoot = import.meta.dirname;
const lectureRoot = path.resolve(sourceRoot, "..");
const manifestPath = path.join(sourceRoot, "deck-manifest.json");
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

const sectionPattern = /<section class="slide[^>]*>[\s\S]*?<\/section>/g;
const addSlideId = (section, id) => section.replace(
  /^<section\s+class=/,
  `<section data-slide-id="${id}" class=`
);

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
    found.forEach((section, index) => sections.push(addSlideId(section, module.slides[index].id)));
  }

  const output = [
    "<!-- GENERATED FILE. Edit 강의자료/deck-src modules, then run: node 강의자료/deck-src/build-decks.mjs -->",
    head.trimEnd(),
    sections.join("\n\n"),
    tail.trimStart()
  ].join("\n\n");
  fs.writeFileSync(path.join(lectureRoot, deck.output), `${output}\n`);
  writeIndex(deckKey, deck);
  console.log(`${deckKey}: ${sections.length} slides -> 강의자료/${deck.output}`);
}
