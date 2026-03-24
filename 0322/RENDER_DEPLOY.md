# Render Deployment

## Render service settings

- Root Directory: `PythonProject4/0322`
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`

## Environment variables

Set these in the Render dashboard:

- `SECRET_KEY`
- `DATABASE_URL` or `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_NAME`
- `REDIS_URL` or `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `OTP_EXPIRE_SECONDS`

## Important note about your current database host

Your current database host `100.108.90.126` is a private network address and usually cannot be reached by Render directly.

To make the deployment work, use one of these options:

1. Move the database to a public MySQL service.
2. Expose your current MySQL server with a public IP and firewall rules.
3. Keep the backend local instead of deploying to Render.

## Health check

After deployment, open:

`/healthz`

It should return:

`{"status":"ok"}`
