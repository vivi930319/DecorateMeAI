# Docker 使用方式

## 第一次啟動

如果本機 `5000`、`5432`、`6379` 沒有被占用：

```powershell
cd "C:\Users\TKU\PycharmProjects\PythonProject\Backend database"
docker compose up -d --build
```

瀏覽：

```text
http://127.0.0.1:5000/health
```

## 避免和本機 Flask 撞 port

如果本機已經有 Flask 跑在 `5000`，可改用 `5050`：

```powershell
cd "C:\Users\TKU\PycharmProjects\PythonProject\Backend database"
$env:PORT="5050"
$env:DB_PORT_PUBLISHED="55432"
$env:REDIS_PORT_PUBLISHED="6380"
docker compose up -d --build
```

瀏覽：

```text
http://127.0.0.1:5050/health
```

## 常用指令

查看狀態：

```powershell
docker compose ps
```

查看 app log：

```powershell
docker compose logs -f app
```

停止服務：

```powershell
docker compose down
```

停止並刪除資料 volume：

```powershell
docker compose down -v
```

## 環境變數

Docker Compose 會自動讀取同目錄的 `.env`。如果要建立 Docker 專用設定，可參考：

```text
.env.docker.example
```

正式部署時請務必更換：

- `SECRET_KEY`
- `DB_PASSWORD`
- `SMTP_USER`
- `SMTP_PASS`
