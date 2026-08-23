import os

import uvicorn


SERVICES = {
    "basic": "Face_analyzer_BASIC:app",
    "pro": "Face_analyzer_PRO:app",
    "suggestion": "Ollama_suggestion:app",
}


if __name__ == "__main__":
    service = os.getenv("SERVICE_NAME", "basic").strip().lower()
    app = SERVICES.get(service)
    if not app:
        raise SystemExit(f"Unknown SERVICE_NAME: {service}")
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
