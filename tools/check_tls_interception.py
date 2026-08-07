"""這條線路上是不是有人在中間拆 TLS？

為什麼不是查憑證存放區
----------------------
搬機文件第 3 節原本教的是「看 Windows 根憑證裡有沒有 Avast」。那個檢查會騙人：
**關掉 HTTPS 掃描之後，那張根憑證仍然留在存放區**，所以它永遠回報「中了」，
你沒辦法用它確認自己到底修好了沒有。

唯一有意義的檢查是實際連一次，看對方遞過來的憑證是誰簽的。
Google 的憑證由 Google Trust Services 簽；如果簽發者變成防毒軟體，
那就是有人在中間解開重簽。

用法
----
    .venv\\Scripts\\python.exe tools\\check_tls_interception.py

結束碼 0 代表乾淨，1 代表被攔截或連不上——可以放進搬機驗收腳本。
"""
import socket
import ssl
import sys

# 這個專案實際依賴的三個 TLS 端點。只測一個不夠：攔截軟體可以按網域決定要不要拆。
HOSTS = [
    ("storage.googleapis.com", "GCS：資料集與模型"),
    ("secretmanager.googleapis.com", "Secret Manager：API 金鑰"),
    ("pypi.org", "PyPI：套件安裝"),
]

# 簽發者裡出現這些字就是攔截軟體，不是正常的公開 CA。
INTERCEPTORS = ("avast", "avg", "kaspersky", "eset", "bitdefender",
                "norton", "mcafee", "zscaler", "fiddler", "charles", "burp")


def issuer_of(host: str) -> str:
    """取得對方憑證的簽發者。

    刻意用 CERT_NONE：這裡的目的是「看看是誰簽的」，不是「驗證它」。
    真的被攔截時驗證一定失敗，那就什麼都看不到了——而看不到正是我們要查的東西。
    這是這個專案唯一可以不驗證憑證的地方，因為它本身就是憑證的檢查工具。

    必須取 binary_form 自己解析。第一版用 `getpeercert()` 的字典形式，結果三個網域
    全部回報「乾淨」——因為 `verify_mode=CERT_NONE` 時那個字典是**空的**，
    Python 只在驗證成功時才填內容。於是「讀不到」被當成「沒有攔截者」，
    在 Avast 明明還在拆 TLS 的情況下回報一切正常。
    看不見要當成失敗，不能當成通過。
    """
    from cryptography import x509

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, 443), timeout=15) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise ValueError("對方沒有遞出憑證")
    cert = x509.load_der_x509_certificate(der)
    parts = [attr.value for attr in cert.issuer
             if attr.oid in (x509.NameOID.ORGANIZATION_NAME, x509.NameOID.COMMON_NAME)]
    if not parts:
        raise ValueError("憑證裡沒有簽發者名稱")
    return " / ".join(str(p) for p in parts)


def main() -> int:
    intercepted = []
    for host, why in HOSTS:
        try:
            issuer = issuer_of(host)
        except Exception as exc:
            # 讀不到就是查不出來，一律當失敗。「不確定」不可以走成「通過」。
            print(f"  ?  {host:<32} 查不出簽發者：{exc}")
            intercepted.append(host)
            continue
        bad = any(name in issuer.lower() for name in INTERCEPTORS)
        print(f"  {'✗' if bad else '✓'}  {host:<32} 簽發者：{issuer}")
        print(f"     {why}")
        if bad:
            intercepted.append(host)

    print()
    if not intercepted:
        print("乾淨：沒有中間人。gcloud 可以開啟憑證驗證：")
        print("    gcloud config unset auth/disable_ssl_validation")
        return 0

    print(f"被攔截：{'、'.join(intercepted)}")
    print()
    print("在 Avast 介面關閉：設定 → 防護 → 核心防護 → 網頁防護 → 「啟用 HTTPS 掃描」")
    print("注意那是網頁防護底下的**子項目**，關掉網頁防護本身不一定會停止拆 TLS。")
    print("改完再跑這支確認——憑證存放區裡的 Avast 根憑證不會消失，看那個沒有用。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
