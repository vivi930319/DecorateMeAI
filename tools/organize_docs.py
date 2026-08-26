"""把根目錄的 md 文件依用途分類到 docs/ 底下，並產生一份索引。

為什麼
------
根目錄有 113 份 md，檔名各種命名習慣混在一起（英文全大寫規格書、中文「給某某端」的
需求單、日期結尾的紀錄）。找一份文件要靠記憶，而不是靠看——這對一個要交接、要口試
的專案是實際成本。

分類規則
--------
以**收件人與用途**分，不是以主題分。理由是這批文件多數是寫給別人看的：
「給資料庫端」那疊只有資料庫組會看，混在架構文件裡只會讓兩邊都難找。

CLAUDE.md 與 README.md 留在根目錄——工具和 GitHub 都會去根目錄找它們。

用法
----
    python tools/organize_docs.py            # 預演，只印出會怎麼搬
    python tools/organize_docs.py --apply    # 實際搬移並產生 docs/README.md
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# 留在根目錄的：工具鏈與 GitHub 會固定去根目錄找。
KEEP_AT_ROOT = {"README.md", "CLAUDE.md"}

# 依序比對，第一個命中的規則決定去哪。順序有意義：
# 「給某某端」的收件人規則要排在主題規則前面，否則
# 「給資料庫端_資安修復規格」會被資安規則搶走，而那份是需求單不是資安報告。
RULES: list[tuple[str, str]] = [
    (r"^給資料庫端",                     "對外規格書/資料庫端"),
    (r"^給爬蟲端",                       "對外規格書/爬蟲端"),
    (r"^給演算法端|^演算法端接口",        "對外規格書/演算法端"),
    (r"^給Ollama端|^給lavien",           "對外規格書/Ollama端"),
    (r"^給商品後端|^給推薦組|^給組員",    "對外規格書/商品與推薦"),
    (r"^渲染端接口",                     "對外規格書/渲染端"),
    # 檔名沒有「給」開頭、但收件人仍然寫在名字裡的那幾份。
    (r"資料庫端",                        "對外規格書/資料庫端"),

    # 待修單要排在主題規則前面：OLLAMA_RENDER_PROMPT_FIX 這種檔名會同時命中
    # 「^OLLAMA_」（架構）與「FIX_RECOMMENDATION」（待修），而它是需求單不是架構文件。
    (r"CHANGE_REQUEST|FIX_RECOMMENDATION|問題回報",                    "待修需求與回報"),

    (r"訓練|模型|CNN|DINOv2|分類|交叉驗證|閾值", "模型與訓練"),

    # 架構要排在資安前面：「Admin商品管理**安全**Proxy三方對接規格書」是對接規格，
    # 只因為名字裡有「安全」兩個字就被歸進資安，找的人會在錯的資料夾翻。
    (r"^Gateway|^Ollama|^ollama|^MEMBER_DATABASE_INTEGRATION|^MAKEUP_AI_CALLER"
     r"|^OLLAMA_|^Admin商品管理|^recommendation_system|^frontend-api"
     r"|架構|接口|技術文件|對接規格書|後端功能|PROJECT_STRUCTURE|端對端流程", "系統架構與接口"),

    (r"資安|隱私|SECURITY|CodeReview驗收|安全代理",                     "資安與隱私"),

    (r"簡報|企劃書|Demo|展示|前端文字總表",                            "簡報與展示"),

    (r"交接|搬機|日誌|歷史|現況|待辦|體檢|優化|改善|卡點|工程化|Git|NEWBIE"
     r"|審查|專案修改",                                                "專案管理與交接"),
]

FALLBACK = "其他"

# 程式碼裡有指到文件路徑的地方，搬完要跟著改，否則註解會指向不存在的檔案。
CODE_REFERENCES = [
    ("face/basic_roi_shadow.py", "CNN訓練歷程_BASIC五官分類.md"),
    ("tools/dinov2_cv_experiment.py", "DINOv2_臉部特徵分類模型規格書.md"),
]


def category_of(name: str) -> str:
    for pattern, folder in RULES:
        if re.search(pattern, name):
            return folder
    return FALLBACK


def tracked_files() -> set[str]:
    """git 有在追的檔案要用 git mv，不然歷史會斷成一刪一增。"""
    try:
        out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8")
        return {line.strip() for line in out.stdout.splitlines() if line.strip()}
    except Exception:
        return set()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="實際搬移（預設只預演）")
    args = ap.parse_args()

    tracked = tracked_files()
    plan: dict[str, list[Path]] = {}
    for path in sorted(ROOT.glob("*.md")):
        if path.name in KEEP_AT_ROOT:
            continue
        plan.setdefault(category_of(path.name), []).append(path)

    total = sum(len(v) for v in plan.values())
    print(f"根目錄 md：{total} 份要搬、{len(KEEP_AT_ROOT)} 份留在原地\n")
    for folder in sorted(plan):
        print(f"  docs/{folder}/　（{len(plan[folder])} 份）")
        for path in plan[folder][:4]:
            print(f"      {path.name}")
        if len(plan[folder]) > 4:
            print(f"      …另外 {len(plan[folder]) - 4} 份")

    if not args.apply:
        print("\n這是預演，什麼都沒有搬。確認分類合理後加 --apply。")
        return 0

    moved = 0
    for folder, paths in plan.items():
        target_dir = DOCS / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        for path in paths:
            target = target_dir / path.name
            if path.name in tracked:
                subprocess.run(["git", "mv", path.name, str(target.relative_to(ROOT))],
                               cwd=ROOT, capture_output=True, text=True)
            else:
                shutil.move(str(path), str(target))
            moved += 1

    # 程式碼註解裡的路徑要跟著搬，否則指向的檔案已經不在那裡了。
    for rel, doc in CODE_REFERENCES:
        source = ROOT / rel
        if not source.is_file():
            continue
        text = source.read_text(encoding="utf-8")
        folder = category_of(doc)
        new_ref = f"docs/{folder}/{doc}"
        if doc in text and new_ref not in text:
            source.write_text(text.replace(doc, new_ref), encoding="utf-8")
            print(f"  更新引用：{rel} -> {new_ref}")

    write_index(scan_docs())
    print(f"\n完成：搬了 {moved} 份，索引寫在 docs/README.md")
    return 0


def scan_docs() -> dict[str, list[Path]]:
    """掃 docs/ 底下**實際存在**的文件，而不是「這次搬了哪些」。

    先前這裡傳的是搬移計畫。根目錄清空之後，計畫是空的，於是索引被重建成一份
    空表——把先前一百多筆全部蓋掉，而腳本照樣回報「完成」。
    這種壞法沒有人會當場發現：索引是給人看的，不是給程式讀的。

    索引要反映的是「現在有什麼」，那就只能從現況掃，不能從這次的動作推。
    """
    found: dict[str, list[Path]] = {}
    for path in sorted(DOCS.rglob("*.md")):
        rel = path.relative_to(DOCS)
        if rel.parts[0] in ("agents",) or rel.name == "README.md":
            continue          # agent 設定不是文件；索引自己也不列自己
        folder = str(rel.parent).replace("\\", "/")
        if folder == ".":
            continue
        found.setdefault(folder, []).append(path)
    return found


def write_index(plan: dict[str, list[Path]]) -> None:
    lines = [
        "# 文件索引",
        "",
        "根目錄只留 `README.md` 與 `CLAUDE.md`，其餘依**收件人與用途**分在這裡。",
        "以收件人分而不是以主題分，是因為多數文件是寫給別人看的——",
        "「給資料庫端」那疊只有資料庫組會看，混進架構文件裡會讓兩邊都難找。",
        "",
        "> 由 `tools/organize_docs.py` 產生。新增文件請放進對應資料夾，再重跑一次更新索引。",
        "",
    ]
    for folder in sorted(plan):
        lines.append(f"## {folder}")
        lines.append("")
        for path in sorted(plan[folder], key=lambda p: p.name):
            lines.append(f"- [{path.stem}]({folder}/{path.name})")
        lines.append("")
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
