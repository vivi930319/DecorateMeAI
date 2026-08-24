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
for _name in ("face", "shared", "gateway", "render", "suggestion"):
    _path = _ROOT / _name
    if _path.is_dir():
        _s = str(_path)
        if _s not in sys.path:
            sys.path.insert(0, _s)

# repo 根目錄也放進去，讓腳本之間可以互相 import（例如 train_pro_nose_side 會用
# train_basic_cnn_roi 的 build_model）。
_root_s = str(_ROOT)
if _root_s not in sys.path:
    sys.path.insert(0, _root_s)
