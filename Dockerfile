# Base image 連 digest 一起釘住：只寫 tag 的話，同一份 Dockerfile 今天與下個月會
# build 出不同的東西（上游 tag 會被覆寫）。升級就換 digest，那是一次進得了 review 的變更。
FROM python:3.10-slim@sha256:c1e4e6c01eb489c422288b2de34b0761ca316f7a2d98e2c33f47659a73ed108a

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# OpenCV 需要這些執行期系統套件（libgl1／libglib2.0-0／libgomp1）。
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 編譯工具只在安裝期間存在：insightface 之類的套件需要它們才裝得起來，但裝完就
# 該消失。留一套 gcc 在正式映像裡，等於替任何進得了容器的人準備好編譯環境。
# 裝與清必須在同一個 RUN，否則檔案還是留在下層 layer 裡。
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

# 預先下載 InsightFace buffalo_l 模型到 /app/.insightface（WORKDIR 內，路徑確定存在）
RUN python -c "\
import os; os.environ['INSIGHTFACE_HOME']='/app';\
from insightface.app import FaceAnalysis;\
app = FaceAnalysis(name='buffalo_l', root='/app/.insightface', allowed_modules=['detection','landmark_3d_68'], providers=['CPUExecutionProvider']);\
app.prepare(ctx_id=-1, det_size=(384,384));\
print('InsightFace models ready at /app/.insightface')"

ENV INSIGHTFACE_HOME=/app
ENV MAX_IMAGE_SIZE=1024
ENV INSIGHT_DET_SIZE=384
ENV INSIGHT_ALLOWED_MODULES=detection,landmark_3d_68

COPY Face_analyzer_BASIC.py .
COPY Face_analyzer_PRO.py .
COPY Ollama_suggestion.py .
COPY dev_server_utils.py .
COPY api_errors.py .
COPY image_safety.py .
COPY cloud_start.py .
COPY job_store.py .
COPY face_roi.py .
# 在 Linux 上是 no-op（路徑本來就是 ASCII），但 Face_analyzer_BASIC 會 import 它，
# 少了這行 image 會在 import 階段就掛掉。
COPY mediapipe_ascii.py .
COPY basic_roi_shadow.py .
# 五官判斷回饋的驗證與儲存。BASIC 與 PRO 都 import 它，少了一樣是 import 階段就掛。
# 它會讀 models/basic_features_roi/*_classes.json 當合法類別表——那批檔案在下面一起複製。
COPY face_feedback.py .
COPY face_corrections.py .
# face_corrections 需要 canonical_label（把已淘汰的類別名換成合併後的現行名稱）。
# 少了這支，容器會在 import 階段就 ModuleNotFoundError 起不來 —— 2026-07-31 踩過。
# 白名單放行（.dockerignore／.gcloudignore）只決定檔案上不上得來，
# **要進映像還是得在這裡 COPY**，兩件事都要做。
COPY analysis_package.py .
# 幾何決策樹的推論路徑與特徵定義。2026-07-30 起 RULE_TREE_PARTS 是空的，
# 它不再提供任何正式答案；保留是為了讓回滾路徑可用（把部位加回去就能生效）。
COPY basic_rule_trees.py .
COPY rule_features.py .
# ROI CNN 模型（5 個部位各約 6MB）＋ DINOv2 backbone 與線性分類頭。
# 2026-07-30 起這些就是**正式答案**：臉型／眉型／鼻型／唇型走 CNN，眼型走 DINOv2。
# 缺檔時 basic_roi_shadow 會自動停用，不影響服務啟動。
COPY models/basic_features_roi/ ./models/basic_features_roi/
# replicate_render.py 尚未交付；預設 backend image 不直接複製不存在檔案

# 非 root 執行。容器被打進來時，root 讓攻擊者可以裝套件、改系統檔、寫任意路徑。
# 模型與程式都是 build 期間以 root 寫入、之後只需要讀，所以這個帳號不必擁有它們。
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER 10001

EXPOSE 8080

ENV SERVICE_NAME=basic
ENV PORT=8080

CMD ["python", "cloud_start.py"]
