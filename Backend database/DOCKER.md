# Docker Quick Start

Use the repo-root `compose.yaml` and run from the project root:

```bash
docker compose up --build
```

Services:

- Flask app: `http://localhost:8080`
- MySQL: `localhost:3307`
- Redis: `localhost:6380`

Useful commands:

```bash
docker compose down
docker compose down -v
docker compose logs -f web
docker compose exec db mysql -uappuser -papppassword app
```

Notes:

- The app waits for MySQL and Redis before starting.
- Tables are created automatically on container startup.
- CSV seed data is imported automatically on startup.
- `OTP_DEV_MODE=true` in `.env.docker`, so OTP codes are printed to the web container logs for local testing.
- If you want real email sending, set `OTP_DEV_MODE=false` and fill in `SMTP_USER` / `SMTP_PASS`.
- The project also contains `Backend database/docker-compose.yml`, but the repo-root `compose.yaml` is the primary local workflow.
