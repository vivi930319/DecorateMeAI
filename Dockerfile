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
app = FaceAnalysis(name='buffalo_l', root='/app/.insightface', providers=['CPUExecutionProvider']);\
app.prepare(ctx_id=-1, det_size=(640,640));\
print('InsightFace models ready at /app/.insightface')"

ENV INSIGHTFACE_HOME=/app

COPY Face_analyzer_BASIC.py .
COPY Face_analyzer_PRO.py .
COPY Ollama_suggestion.py .
COPY dev_server_utils.py .
COPY cloud_start.py .
COPY eyelid_model.onnx .
COPY eyelid_model.onnx.data .
COPY job_store.py .
# replicate_render.py 由組員交付後加入
COPY replicate_render.py* ./

EXPOSE 8080

ENV SERVICE_NAME=basic
ENV PORT=8080

CMD ["python", "cloud_start.py"]
