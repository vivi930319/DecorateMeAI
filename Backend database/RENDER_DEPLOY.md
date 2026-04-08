# Render Deployment

This backend now lives under `Backend database`, and the repo-level
`render.yaml` already points Render at that directory.

## Render service settings

- Root Directory: `Backend database`
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Health Check Path: `/healthz`

If you deploy from the Render dashboard manually, use the same values above.
If you deploy from the repo blueprint, keep [`render.yaml`](../render.yaml)
as the source of truth.

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

## Important note about database reachability

Your previous database host `100.108.90.126` is a private network address and
usually cannot be reached by Render directly.

To make the deployment work, use one of these options:

1. Move the database to a public MySQL service.
2. Expose your current MySQL server with a public IP and firewall rules.
3. Keep the backend local and deploy only inside your own network.

## Health check

After deployment, open `/healthz`.

It should return `{"status":"ok"}`.
