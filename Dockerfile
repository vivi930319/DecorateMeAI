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

COPY Face_analyzer_BASIC.py .
COPY Face_analyzer_PRO.py .
COPY Ollama_suggestion.py .
COPY dev_server_utils.py .
COPY cloud_start.py .
COPY eyelid_model.onnx .
COPY eyelid_model.onnx.data .
# replicate_render.py 由組員交付後加入
COPY replicate_render.py* ./

EXPOSE 8080

ENV SERVICE_NAME=basic
ENV PORT=8080

CMD ["python", "cloud_start.py"]
