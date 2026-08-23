# Base image 連 digest 一起釘住，理由同 Dockerfile.gateway：tag 會被上游覆寫，
# digest 不會。升級 = 改這一行。
FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY render/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/dev_server_utils.py .
COPY shared/api_errors.py .
COPY shared/image_safety.py .
COPY shared/job_store.py .
COPY render/replicate_render.py .
COPY render/replicate_render_api.py .

# 非 root 執行（見 Dockerfile.gateway 的說明）。
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER 10001

EXPOSE 8080

CMD ["uvicorn", "replicate_render_api:app", "--host", "0.0.0.0", "--port", "8080"]
