import os
import secrets
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.header import Header


def generate_otp(length: int = 6) -> str:
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def redis_key(email: str) -> str:
    return f"otp:{email}"


def attempt_key(email: str) -> str:
    return f"otp_attempt:{email}"


def _generate_pretty_otp_html(otp_code: str, expire_minutes: int, logo_cid: str | None = None) -> str:
    """產出 Decorate Me 品牌 OTP HTML Email。"""
    logo_html = (
        f'<img src="cid:{logo_cid}" width="128" alt="Decorate Me" '
        'style="display:block;width:128px;height:auto;margin:0 auto 12px;border:0;outline:none;">'
        if logo_cid else
        '<div style="font-size:28px;letter-spacing:2px;font-weight:700;color:#70483e;">Decorate Me</div>'
    )
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin:0;padding:0;background:#f7f1ed;font-family:Arial,'Microsoft JhengHei',sans-serif;color:#473732;">
        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout:fixed;background:#f7f1ed;padding:42px 12px;">
            <tr>
                <td align="center">
                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width:520px;background:#fffdfb;border-radius:20px;overflow:hidden;box-shadow:0 10px 30px rgba(86,53,43,.12);border:1px solid #eadbd2;">
                        <tr>
                            <td align="center" style="background:#fff8f4;padding:28px 24px 18px;border-bottom:1px solid #f0e2da;">
                                {logo_html}
                                <p style="margin:0;font-size:12px;letter-spacing:1px;color:#9a7669;">YOUR PERSONAL BEAUTY COMPANION</p>
                            </td>
                        </tr>

                        <tr>
                            <td style="padding:34px 34px 30px;text-align:center;">
                                <p style="margin:0 0 10px;color:#a87765;font-size:12px;letter-spacing:2px;font-weight:bold;">SECURITY VERIFICATION</p>
                                <h2 style="color:#473732;margin:0 0 12px;font-size:22px;font-weight:700;">確認您的電子郵件</h2>
                                <p style="color:#75635c;margin:0 0 25px;font-size:14px;line-height:1.75;">
                                    請在 <strong style="color:#9b624f;">{expire_minutes} 分鐘內</strong> 輸入以下六位數驗證碼，
                                    完成 Decorate Me 的安全驗證。
                                </p>
                                <div style="background:#f7ebe5;border:1px solid #ddb9aa;border-radius:14px;padding:19px 10px;margin:0 0 24px;">
                                    <span style="font-size:36px;font-weight:bold;color:#5e4036;letter-spacing:9px;font-family:'Courier New',monospace;display:inline-block;margin-left:9px;">{otp_code}</span>
                                </div>
                                <p style="color:#9a857b;margin:0;font-size:12px;line-height:1.75;">
                                    請勿將驗證碼提供給任何人。若非本人操作，請直接忽略本郵件。
                                </p>
                            </td>
                        </tr>

                        <tr>
                            <td align="center" style="background:#70483e;padding:18px 25px;">
                                <p style="color:#f8eae2;margin:0;font-size:11px;line-height:1.7;">
                                    此為系統自動發送郵件，請勿直接回覆。<br>© 2026 Decorate Me Team.
                                </p>
                            </td>
                        </tr>

                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """


def send_otp_email(to_email: str, otp_code: str, expire_seconds: int) -> None:
    if os.getenv("OTP_DEV_MODE", "false").lower() == "true":
        # Development mode suppresses SMTP delivery, but never prints OTPs or addresses.
        print("[OTP DEV MODE] OTP delivery suppressed", flush=True)
        return

    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    if not smtp_user or not smtp_pass:
        raise RuntimeError("SMTP credentials are not configured")

    expire_minutes = expire_seconds // 60

    # related 包含內嵌 Logo；alternative 則提供純文字與 HTML 相容版本。
    msg = MIMEMultipart("related")

    # 🌟 使用 Header 包裝，確保中文主旨與寄件者不會被 Gmail 判讀失敗
    msg["Subject"] = Header(f"【Decorate Me】您的驗證碼為 {otp_code}", "utf-8")
    msg["From"] = f"Decorate Me <{smtp_user}>"
    msg["To"] = to_email

    # 1. 純文字版本
    text_content = f"【Decorate Me】您的驗證碼為：{otp_code}，請於 {expire_minutes} 分鐘內輸入。"
    part1 = MIMEText(text_content, "plain", "utf-8")

    logo_path = os.getenv("OTP_LOGO_PATH", os.path.join(os.path.dirname(__file__), "static", "brand", "decorate-me-logo.jpg"))
    logo_cid = "decorate-me-logo"
    has_logo = os.path.isfile(logo_path)
    html_content = _generate_pretty_otp_html(otp_code, expire_minutes, logo_cid if has_logo else None)
    part2 = MIMEText(html_content, "html", "utf-8")
    alternative = MIMEMultipart("alternative")
    alternative.attach(part1)
    alternative.attach(part2)
    msg.attach(alternative)
    if has_logo:
        with open(logo_path, "rb") as logo_file:
            logo_part = MIMEImage(logo_file.read(), _subtype="jpeg")
        logo_part.add_header("Content-ID", f"<{logo_cid}>")
        logo_part.add_header("Content-Disposition", "inline", filename="decorate-me-logo.jpg")
        msg.attach(logo_part)

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", 587))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        # 🌟 使用 send_message 代替 sendmail，讓 Python 自動處理 MIME 邊界與 UTF-8 編碼
        server.send_message(msg)
