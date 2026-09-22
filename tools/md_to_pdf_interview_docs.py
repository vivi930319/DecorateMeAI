"""把口試問答文件書轉成 PDF。

為什麼不用 pandoc / weasyprint：這台機器上兩者都沒有，而 Chrome 有。
Chrome 的 --print-to-pdf 走的是它自己的排版引擎，中文字型、表格、
程式碼區塊全部不必另外處理——這是在 Windows 上最少依賴的一條路。

用法：
    python tools/md_to_pdf_interview_docs.py                 # 轉全部 Q0*.md
    python tools/md_to_pdf_interview_docs.py Q01 Q06         # 只轉指定幾份
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "技術文件書_詳細版"
OUT = DOCS / "pdf"

CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

# 列印用的樣式。重點不是好看，是**口試現場翻得動**：
#   - 每一個 ═══ 大段落換頁，這樣翻到某一節不會落在頁面中間
#   - 表格不允許跨頁斷裂（break-inside: avoid），斷掉的表格讀不了
#   - 標題不准留在頁尾（break-after: avoid），否則題號和答案會分家
CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }

html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif;
  font-size: 10.5pt;
  line-height: 1.75;
  color: #1b1b1b;
  margin: 0;
}

h1 {
  font-size: 19pt; margin: 0 0 14pt;
  padding-bottom: 8pt; border-bottom: 2.5pt solid #1b1b1b;
}
/* ═══ 開頭的大段落分隔線：每一個都從新的一頁開始 */
h1 + h1, body > h1 ~ h1 { break-before: page; page-break-before: always; }

h2 {
  font-size: 14pt; margin: 18pt 0 8pt;
  padding: 5pt 0 5pt 9pt;
  border-left: 4pt solid #2d5f8b; background: #eef3f8;
  break-after: avoid; page-break-after: avoid;
}
h3 {
  font-size: 12pt; margin: 14pt 0 6pt; color: #173a57;
  break-after: avoid; page-break-after: avoid;
}
p, ul, ol { margin: 6pt 0; orphans: 3; widows: 3; }
li { margin: 2pt 0; }

strong { color: #0f2d45; }

blockquote {
  margin: 9pt 0; padding: 8pt 12pt;
  background: #fbf7ec; border-left: 3.5pt solid #c79a3a;
  font-size: 10pt;
  break-inside: avoid; page-break-inside: avoid;
}
blockquote p { margin: 3pt 0; }

table {
  border-collapse: collapse; width: 100%;
  margin: 9pt 0; font-size: 9.5pt;
  break-inside: avoid; page-break-inside: avoid;
}
th, td { border: 0.6pt solid #9aa7b1; padding: 4pt 6pt; vertical-align: top; }
th { background: #e6ecf2; text-align: left; font-weight: 600; }
tbody tr:nth-child(even) { background: #f7f9fb; }

pre {
  background: #f4f6f8; border: 0.6pt solid #cbd4dc; border-radius: 3pt;
  padding: 8pt 10pt; margin: 9pt 0;
  font-family: Consolas, "Cascadia Mono", "Microsoft JhengHei", monospace;
  font-size: 8.8pt; line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
  break-inside: avoid; page-break-inside: avoid;
}
code {
  font-family: Consolas, "Cascadia Mono", "Microsoft JhengHei", monospace;
  font-size: 9.2pt; background: #eef1f4;
  padding: 0.5pt 3pt; border-radius: 2pt;
}
pre code { background: none; padding: 0; font-size: inherit; }

hr { border: none; border-top: 0.6pt solid #c8d0d7; margin: 14pt 0; }
"""


def render_html(md_path: Path) -> str:
    body = markdown.markdown(
        md_path.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )
    title = md_path.stem
    return (
        "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
        f"<title>{title}</title><style>{CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def find_chrome() -> Path:
    for candidate in CHROME_CANDIDATES:
        if candidate.exists():
            return candidate
    raise SystemExit("找不到 Chrome 或 Edge，無法列印 PDF。")


def to_pdf(chrome: Path, html_path: Path, pdf_path: Path, profile: Path) -> None:
    # --no-pdf-header-footer：Chrome 預設會在頁眉印檔案路徑、頁尾印日期，
    # 那會把本機的絕對路徑印在每一頁上（交出去的文件不該有那個）。
    subprocess.run(
        [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--disable-extensions",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )


def main() -> int:
    wanted = [a.upper() for a in sys.argv[1:]]
    sources = sorted(DOCS.glob("Q0*.md"))
    if wanted:
        sources = [p for p in sources if any(p.name.upper().startswith(w) for w in wanted)]
    if not sources:
        raise SystemExit("沒有符合的 .md 檔案。")

    OUT.mkdir(parents=True, exist_ok=True)
    work = OUT / "_html"
    work.mkdir(exist_ok=True)
    profile = OUT / "_chrome_profile"
    chrome = find_chrome()

    failures = []
    for md_path in sources:
        html_path = work / f"{md_path.stem}.html"
        html_path.write_text(render_html(md_path), encoding="utf-8")
        pdf_path = OUT / f"{md_path.stem}.pdf"
        started = time.time()
        try:
            to_pdf(chrome, html_path, pdf_path, profile)
        except subprocess.CalledProcessError as exc:
            failures.append((md_path.name, (exc.stderr or b"").decode("utf-8", "replace")[-400:]))
            print(f"  FAIL {md_path.name}")
            continue
        if not pdf_path.exists():
            failures.append((md_path.name, "Chrome 沒有產出檔案"))
            print(f"  FAIL {md_path.name}")
            continue
        kb = pdf_path.stat().st_size / 1024
        print(f"  OK   {pdf_path.name}  {kb:,.0f} KB  ({time.time() - started:.1f}s)")

    shutil.rmtree(profile, ignore_errors=True)
    if failures:
        print("\n失敗：")
        for name, err in failures:
            print(f"  {name}: {err}")
        return 1
    print(f"\n輸出目錄：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
