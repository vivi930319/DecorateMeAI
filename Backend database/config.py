import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

# 把這裡改成修正 postgres 的常見網址問題 (SQLAlchemy 規定要叫 postgresql://)
def _normalize_database_url(url: str | None) -> str | None:
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url

DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "postgres")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")

if DATABASE_URL:
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
else:
    missing = [key for key, val in {
        "DB_USER": DB_USER,
        "DB_PASSWORD": DB_PASSWORD,
        "DB_HOST": DB_HOST,
    }.items() if not val]
    if missing:
        raise RuntimeError(
            f"缺少資料庫連線設定：{', '.join(missing)}，請在 .env 或環境變數中設定。"
        )

    # 這裡的魔法字串正式改成 PostgreSQL 格式！
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )

SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}