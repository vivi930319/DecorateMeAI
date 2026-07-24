"""讓 MediaPipe 能在「路徑含非 ASCII 字元」的機器上跑起來。

## 問題

本專案放在 `C:\\Users\\user\\OneDrive - 淡江大學\\Desktop\\PythonProject12`，
venv 自然也在這條路徑底下。MediaPipe 的模型圖（`.binarypb`）是由它的 C++ 層
用系統 mbcs 編碼去開檔的，路徑裡的「淡江大學」在 cp950 轉換後對不回原字串，
於是必定丟：

    FileNotFoundError: The path does not exist:
        ...\\site-packages\\mediapipe/modules/face_landmark/face_landmark_front_cpu.binarypb

檔案其實在，是路徑編碼壞掉。純 Python 層（`cv2.imdecode` + `np.fromfile`）沒事，
所以只有建 landmark 快取這類真的要初始化 FaceMesh 的步驟會炸。

早期能建起快取，是因為專案當時放在 `C:\\Users\\isach\\PycharmProjects\\`——
那是一條純英文路徑。搬到 OneDrive 之後才開始壞。

## 解法

把 `mediapipe` 套件整包複製到一條純 ASCII 的本機路徑，並把它插到 `sys.path`
最前面，讓 `mediapipe.__file__` 變成 ASCII，C++ 層就找得到自己的模型檔。

刻意**不**依賴手動設 `PYTHONPATH`，也不要求誰去記得先跑一支準備腳本：
換機器、重建 venv、升級 mediapipe 之後都會自動重做，不會變成搬機地雷。

## 用法

在 `import mediapipe` **之前**先 import 本模組：

    import mediapipe_ascii  # noqa: F401  # 必須早於 mediapipe
    import mediapipe as mp

路徑本來就是 ASCII 時（Linux、Docker、Cloud Run）本模組什麼都不做。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

__all__ = ["ensure_ascii_mediapipe"]

# 複製後的落腳處。用 LOCALAPPDATA 而不是專案內，因為專案路徑本身就是問題所在。
_DEFAULT_CACHE = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
_CACHE_ROOT = Path(os.environ.get("MEDIAPIPE_ASCII_DIR", _DEFAULT_CACHE / "decorateme" / "mp_ascii"))

# 用來判斷既有副本是否還對得上目前安裝的版本；對不上就重做。
_STAMP = "_source_stamp.txt"


def _is_ascii(text: str) -> bool:
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _locate_installed_mediapipe() -> Path | None:
    """找出目前環境安裝的 mediapipe 套件目錄（不 import 它）。"""
    for entry in sys.path:
        if not entry:
            continue
        candidate = Path(entry) / "mediapipe"
        if (candidate / "__init__.py").is_file():
            return candidate
    return None


def ensure_ascii_mediapipe(verbose: bool = False) -> Path | None:
    """必要時把 mediapipe 複製到 ASCII 路徑並掛進 `sys.path`。

    回傳實際會被 import 的 mediapipe 目錄；不需要處理時回傳原目錄。
    已經 import 過 mediapipe 的話直接放棄（改 sys.path 也來不及了）。
    """
    source = _locate_installed_mediapipe()
    if source is None:
        return None

    # 路徑沒有非 ASCII 字元就不必動——Linux / Docker / Cloud Run 都走這條。
    if _is_ascii(str(source)):
        return source

    if "mediapipe" in sys.modules:
        raise RuntimeError(
            "mediapipe 已經被 import，來不及修正路徑。"
            "請把 `import mediapipe_ascii` 移到 `import mediapipe` 之前。"
        )

    # 每個來源（venv）各自一份副本：專案有 .venv 與 .venv-train 兩個環境，
    # 共用同一個目的地會導致每次切換 venv 都整包重新複製 100MB。
    source_key = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:12]
    target_parent = _CACHE_ROOT / source_key
    target = target_parent / "mediapipe"
    if not _is_ascii(str(target)):
        raise RuntimeError(
            f"連備援路徑 {target} 都含非 ASCII 字元，請用環境變數 "
            "MEDIAPIPE_ASCII_DIR 指定一條純英文路徑。"
        )

    # 來源指紋：mediapipe 升級（__init__.py 時間戳改變）就重做。
    stamp_now = f"{source}\n{(source / '__init__.py').stat().st_mtime_ns}"
    stamp_file = target_parent / _STAMP
    fresh = (
        target.is_dir()
        and stamp_file.is_file()
        and stamp_file.read_text(encoding="utf-8") == stamp_now
    )

    if not fresh:
        if verbose:
            print(f"[mediapipe_ascii] 複製 mediapipe 到 {target} …", flush=True)
        target_parent.mkdir(parents=True, exist_ok=True)
        # 先複製到暫存目錄再換上去。直接 rmtree + copytree 的話，只要有檔案被
        # 佔用（防毒掃描、OneDrive 同步）就會刪一半，接著 copytree 撞
        # FileExistsError，而且留下一份殘缺的副本。
        staging = target_parent / f"mediapipe.tmp{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(source, staging)
        retired = target_parent / f"mediapipe.old{os.getpid()}"
        if target.exists():
            target.replace(retired)
        staging.replace(target)
        shutil.rmtree(retired, ignore_errors=True)
        stamp_file.write_text(stamp_now, encoding="utf-8")
        if verbose:
            print("[mediapipe_ascii] 完成。", flush=True)

    entry = str(target_parent)
    if entry in sys.path:
        sys.path.remove(entry)
    sys.path.insert(0, entry)
    return target


# import 本模組就生效，呼叫端不必多寫一行。
ensure_ascii_mediapipe(verbose=os.environ.get("MEDIAPIPE_ASCII_VERBOSE") == "1")
