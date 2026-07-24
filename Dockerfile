FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# OpenCV 需要這些系統套件
RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
COPY cloud_start.py .
COPY job_store.py .
COPY face_roi.py .
# 在 Linux 上是 no-op（路徑本來就是 ASCII），但 Face_analyzer_BASIC 會 import 它，
# 少了這行 image 會在 import 階段就掛掉。
COPY mediapipe_ascii.py .
COPY basic_roi_shadow.py .
# ROI CNN shadow 模型（5 個部位各約 6MB）。BASIC 用它產生 shadow prediction，
# 正式輸出仍是規則式。缺檔時 basic_roi_shadow 會自動停用，不影響服務啟動。
COPY models/basic_features_roi/ ./models/basic_features_roi/
# replicate_render.py 尚未交付；預設 backend image 不直接複製不存在檔案

EXPOSE 8080

ENV SERVICE_NAME=basic
ENV PORT=8080

CMD ["python", "cloud_start.py"]
