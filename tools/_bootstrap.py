# -*- coding: utf-8 -*-
"""讓 training/ 底下的腳本找得到服務碼。

2026-08-23 起原始碼分成 face/ gateway/ render/ shared/ suggestion/。容器裡是扁平的
（Dockerfile 用 `COPY face/x.py .`），所以服務自己的 import 不受影響；但 training/ 與
tools/ 的腳本是直接用 `python training/xxx.py` 執行的，工作目錄在 repo 根，
sys.path 裡沒有那幾個資料夾，於是 `import mediapipe_ascii` 會 ModuleNotFoundError。

要求每個人記得先 export PYTHONPATH 是行不通的——忘記的症狀是腳本跑到一半才炸，
而且訊息看起來像少裝了套件。所以由腳本自己補上：

    import _bootstrap  # noqa: F401

放在其他 import 之前。這支模組本身不做任何事，只有 side effect。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# 順序無所謂，這幾個資料夾裡沒有同名模組（重複的話 Dockerfile 的扁平 COPY 早就會撞名）。
#
# training 也在清單裡：tools/ 的腳本會直接 import 訓練腳本的東西
# （find_label_errors 用 train_basic_cnn_roi 的 build_model、to_tensor 等）。
# training/ 底下的腳本彼此 import 不需要這一條——`python training/x.py` 會自動
# 把腳本自己的目錄放進 sys.path[0]——但從 tools/ 跨過去就沒有那個便利。
# 2026-08-23 的重構把 train_basic_cnn_roi.py 從 repo 根移進 training/ 之後，
# find_label_errors.py 就一直是壞的（ModuleNotFoundError），直到 08-24 才被跑到。
for _name in ("face", "shared", "gateway", "render", "suggestion", "training"):
    _path = _ROOT / _name
    if _path.is_dir():
        _s = str(_path)
        if _s not in sys.path:
            sys.path.insert(0, _s)

# repo 根目錄也放進去，讓 `import tools.x` / `import training.x` 這種帶套件名的
# 寫法也能運作。
_root_s = str(_ROOT)
if _root_s not in sys.path:
    sys.path.insert(0, _root_s)


# 印不出來的字元不該讓整支腳本死掉。
#
# Windows 主控台預設 cp950，而這些腳本的訊息裡有 ≥ ≈ ↔ ✓ ✗ − 這類符號
# （光是 tools/ 與 training/ 就有 19 處）。cp950 編不出來時 print 會拋
# UnicodeEncodeError，**而且往往是在工作做完之後才炸在最後一行說明上**——
# 2026-08-26 就發生過兩次：一次是訓練腳本死在「警告使用者」那一行，什麼都沒跑；
# 一次是告警政策都建好了、卻死在「記得去點驗證信」那句話上。
#
# 逐一把符號換掉是打地鼠：下一個人寫訊息時還是會用。改成 errors="replace"——
# 編碼維持主控台原本的設定（中文照樣正確顯示），只有真的編不出來的字元變成 "?"。
# 少一個符號，比整支腳本消失好。
#
# argparse 的 RawDescriptionHelpFormatter 會把 docstring 原樣印出來，
# 所以 `--help` 也走這條路——那正是好幾支腳本的符號所在的地方。
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")
    except Exception:
        # 重導到檔案或管線時可能沒有這個能力。印不出來也不該讓 import 失敗。
        pass
