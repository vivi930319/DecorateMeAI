import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


def _normalize_database_url(url: str | None) -> str | None:
    if url and url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+pymysql://", 1)
    return url


DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME", "app")
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

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}@{DB_HOST}/{DB_NAME}"
    )

SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
