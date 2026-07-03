"""開發用靜態伺服器：所有回應都帶 no-cache header，避免瀏覽器快取舊版 JS/CSS。"""
import http.server, os

PORT = 5500
BIND = "127.0.0.1"

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 關掉 terminal 刷屏

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    with http.server.ThreadingHTTPServer((BIND, PORT), NoCacheHandler) as httpd:
        print(f"Dev server: http://{BIND}:{PORT}  (no-cache mode)", flush=True)
        httpd.serve_forever()
