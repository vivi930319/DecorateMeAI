import json
import os
import socket
import sys
from urllib.error import URLError
from urllib.request import urlopen


def _can_bind(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _health_payload(host: str, port: int):
    try:
        with urlopen(f"http://{host}:{port}/health", timeout=1.5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body)
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return None


def _port_in_use_message(service_name: str, host: str, port: int, env_prefix: str) -> str:
    payload = _health_payload(host, port)
    health_hint = ""
    if isinstance(payload, dict):
        status = payload.get("status")
        running_service = payload.get("service")
        if status == "ok" and running_service:
            health_hint = f"\n看起來 {running_service} 已經在 http://{host}:{port} 正常運行。"

    return (
        f"{service_name} 無法啟動，因為 {host}:{port} 已經被占用。"
        f"{health_hint}\n"
        "你可以選一個做法：\n"
        f"1. 關掉目前占用這個 port 的程式後重試\n"
        f"2. 保留目前服務，直接用瀏覽器打開 http://{host}:{port}/health 確認\n"
        f"3. 臨時改 port：設定環境變數 {env_prefix}_PORT 後再啟動\n"
    )


def run_dev_server(app, service_name: str, env_prefix: str, default_port: int):
    host = os.getenv(f"{env_prefix}_HOST", "127.0.0.1")
    port = int(os.getenv(f"{env_prefix}_PORT", str(default_port)))

    if not _can_bind(host, port):
        print(_port_in_use_message(service_name, host, port, env_prefix), file=sys.stderr)
        raise SystemExit(1)

    import uvicorn

    uvicorn.run(app, host=host, port=port)
