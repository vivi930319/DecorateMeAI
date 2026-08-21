# 使用官方輕量版 Python 環境
FROM python:3.11-slim

# 設定容器內的工作目錄
WORKDIR /app

# 讓 Python log 直接輸出，並避免產生 .pyc
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安裝 PostgreSQL client library
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 複製套件清單並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    # pywin32 is a Windows-only dependency used by local tooling; omit it in
    # the Linux container image.
    && iconv -f UTF-16 -t UTF-8 requirements.txt | grep -v '^pywin32==' > /tmp/requirements-linux.txt \
    && pip install --no-cache-dir -r /tmp/requirements-linux.txt

# 複製專案內的所有程式碼到容器中
COPY . .

# 宣告 Flask 預設對外開放的 Port
EXPOSE 5000

# 等 PostgreSQL / Redis ready 後，用 gunicorn 啟動 Flask
CMD ["sh", "-c", "python wait_for_services.py && gunicorn -b 0.0.0.0:${PORT:-5000} app:app"]
