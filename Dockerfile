FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# OpenCV 需要這些系統套件
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY Face_analyzer.py .

EXPOSE 8001

CMD ["uvicorn", "Face_analyzer:app", "--host", "0.0.0.0", "--port", "8001"]