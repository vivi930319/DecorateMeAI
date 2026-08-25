"""切出固定的保留測試集，作為跨版本比較的唯一基準。

為什麼需要這個
----------------
5-fold 的分數不能跨版本比較。資料一變，folds 就跟著重切，等同換了一份考卷——
issue #24 已經寫過這件事。2026-08-06 又證實影響範圍是**全部部位**，不只被改動的
那一個：`data/roi_cache/rois.npz` 是單一共用影像清單，五個部位從同一批影像裁 ROI，
所以從眼型刪掉 17 張重複，五個部位的 folds 全部重切。

固定保留集解掉這件事：一組照片永遠不參與訓練，每一版模型都在同一份考卷上評分。

設計上的三個決定
----------------
1. **用 sha256 當鍵，不用路徑。**
   `identity_map.json` 就是用絕對路徑當鍵，結果 2026-08-06 把 101 張照片從
   `細長眼` 搬到 `鳳眼` 之後全部查不到，那些樣本被當成 identity=-1、一律留在 train，
   眼型有 15% 的資料從此不曾當過考題，而且沒有任何地方報錯。
   sha256 認的是內容，搬資料夾、改檔名、換機器都不會失效。

2. **按 identity 切，同一個人整組落同一邊。**
   資料是從影劇截圖蒐集的，同一個藝人常有多張。隨機切分會讓模型靠「認人」拿分，
   分數虛高。identity=-1（聚類失敗）一律留在 train，不污染保留集。

3. **輸出檔進版控。** 這份切分一旦定案就不該再改，否則又回到「換考卷」的問題。
   換機器時 clone 下來就是同一份，不必也不該重跑本腳本。

用法
----
    # 首次建立（之後不要再跑，除非確定要作廢舊基準）
    .venv-train\\Scripts\\python.exe tools\\build_holdout_split.py

    # 資料增加後想把新資料也納入保留集：改 --version 產生新版本，
    # 舊版本保留，並在訓練紀錄裡寫明從哪一版換到哪一版
    .venv-train\\Scripts\\python.exe tools\\build_holdout_split.py --version v2
"""
import argparse
import collections
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

INDEX = ROOT / "data" / "roi_cache" / "index.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description="切出固定的保留測試集")
    p.add_argument("--ratio", type=float, default=0.20, help="每個類別要保留的比例")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--version", default="v1")
    p.add_argument("--min-per-class", type=int, default=8,
                   help="每個類別至少要有幾張進保留集，湊不到就警告")
    args = p.parse_args()

    out = ROOT / "data" / "roi_cache" / f"holdout_split_{args.version}.json"
    if out.exists():
        print(f"{out.name} 已存在。保留集一旦定案就不應覆蓋——"
              f"要換基準請用 --version 產生新版本。")
        return 1

    records = json.loads(INDEX.read_text(encoding="utf-8"))["records"]
    print(f"index.json 共 {len(records)} 筆")

    # 先把每筆的 sha256 與相對路徑算出來。相對路徑只是給人看的，程式一律認 sha256。
    rows = []
    for r in records:
        path = Path(r["path"])
        if not path.exists():
            print(f"  略過（檔案不存在）：{path.name}")
            continue
        part, label = next(iter(r["labels"].items()))
        rows.append({
            "sha256": sha256_of(path),
            "relpath": str(path.relative_to(ROOT)).replace("\\", "/"),
            "part": part,
            "label": label,
            "identity": int(r.get("identity", -1)),
        })
    print(f"可用樣本 {len(rows)}")

    unmapped = sum(1 for r in rows if r["identity"] == -1)
    if unmapped:
        print(f"  [注意] identity=-1 有 {unmapped} 張（{100*unmapped/len(rows):.1f}%），"
              f"這些一律留在 train。比例偏高代表 identity_map 過期，"
              f"請先跑 tools/build_identity_map.py")

    # 按 (部位, 類別) 統計每個 identity 貢獻多少張，才能在保留集裡讓每類都有代表。
    by_pc = collections.defaultdict(lambda: collections.defaultdict(list))
    for i, r in enumerate(rows):
        by_pc[(r["part"], r["label"])][r["identity"]].append(i)

    rng = random.Random(args.seed)
    holdout_ids = set()
    # 逐類挑 identity，直到該類的保留張數達標。identity 是全域的，所以某一類挑走的
    # identity 也會把它在別類的照片一起帶走——這是刻意的，不然同一個人會跨邊。
    for (part, label), id_map in sorted(by_pc.items()):
        total = sum(len(v) for v in id_map.values())
        target = max(args.min_per_class, int(round(total * args.ratio)))
        taken = sum(len(id_map[i]) for i in id_map if i in holdout_ids)
        candidates = [i for i in id_map if i != -1 and i not in holdout_ids]
        rng.shuffle(candidates)
        for ident in candidates:
            if taken >= target:
                break
            # 至少留一個 identity 給 train，避免把整類抽空
            if len([i for i in id_map if i not in holdout_ids]) <= 1:
                break
            holdout_ids.add(ident)
            taken += len(id_map[ident])

    for r in rows:
        r["split"] = "holdout" if r["identity"] in holdout_ids else "train"

    payload = {
        "version": args.version,
        "seed": args.seed,
        "ratio": args.ratio,
        "n_total": len(rows),
        "n_holdout": sum(1 for r in rows if r["split"] == "holdout"),
        "n_identities_holdout": len(holdout_ids),
        "note": "鍵是 sha256，不是路徑。搬機或搬資料夾都不影響。這份切分定案後不要重跑。",
        "samples": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n已寫出 {out.relative_to(ROOT)}")
    print(f"保留集 {payload['n_holdout']} / {payload['n_total']} 張"
          f"（{100*payload['n_holdout']/payload['n_total']:.1f}%），"
          f"涵蓋 {len(holdout_ids)} 個 identity\n")
    print(f"{'部位':<12}{'類別':<10}{'train':>7}{'holdout':>9}")
    print("-" * 40)
    warn = []
    for (part, label) in sorted(by_pc):
        sel = [r for r in rows if r["part"] == part and r["label"] == label]
        h = sum(1 for r in sel if r["split"] == "holdout")
        print(f"{part:<12}{label:<10}{len(sel)-h:>7}{h:>9}")
        if h < args.min_per_class:
            warn.append(f"{part}/{label} 只有 {h} 張")
    if warn:
        print("\n[注意] 下列類別的保留樣本偏少，該類分數會很不穩：")
        for w in warn:
            print(f"    {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
