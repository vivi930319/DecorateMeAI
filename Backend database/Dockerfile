# 使用官方輕量版 Python 3.10 環境
FROM python:3.10-slim

# 設定容器內的工作目錄
WORKDIR /app

# 安裝編譯 PostgreSQL 驅動所需的系統套件，防止 psycopg2 安裝失敗
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /lib/mod/lists/*

# 複製套件清單並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案內的所有程式碼到容器中
COPY . .

# 宣告 Flask 預設要對外開放的 Port (GCP/Zeabur/Render 都適用)
EXPOSE 5000

# 使用生產環境標準的 gunicorn 啟動 Flask，這比 app.run 更穩定，不會卡死
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]