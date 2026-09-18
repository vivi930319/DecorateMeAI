import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


# `.env` is the normal application configuration. `OTP.env` is a local-only
# SMTP configuration file and is explicitly ignored by Git. Deployment-level
# environment variables always take precedence over either file.
load_dotenv()
load_dotenv(dotenv_path=Path(__file__).with_name("OTP.env"), override=False)


def _normalize_database_url(url: str | None) -> str | None:
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY or SECRET_KEY.startswith("CHANGE_ME"):
    raise RuntimeError("缺少 SECRET_KEY；請在部署環境或本機 .env 設定隨機值。")

if DATABASE_URL:
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
else:
    missing = [
        name
        for name, value in {
            "DB_USER": DB_USER,
            "DB_PASSWORD": DB_PASSWORD,
            "DB_NAME": DB_NAME,
        }.items()
        if not value or value.startswith("CHANGE_ME")
    ]
    if missing:
        raise RuntimeError(
            f"缺少資料庫連線設定：{', '.join(missing)}，請在 .env 或環境變數中設定。"
        )

    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )

SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}
