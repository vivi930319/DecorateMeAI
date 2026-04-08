import os
import socket
import time


def wait_for_port(host: str, port: int, service_name: str, timeout: int = 60) -> None:
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"{service_name} is ready at {host}:{port}")
                return
        except OSError:
            print(f"Waiting for {service_name} at {host}:{port}...")
            time.sleep(2)

    raise TimeoutError(f"Timed out waiting for {service_name} at {host}:{port}")


if __name__ == "__main__":
    wait_for_port(os.getenv("DB_HOST", "db"), int(os.getenv("DB_PORT", "3306")), "MySQL")
    wait_for_port(os.getenv("REDIS_HOST", "redis"), int(os.getenv("REDIS_PORT", "6379")), "Redis")
