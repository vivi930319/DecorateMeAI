import os
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def generate_otp(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))


def redis_key(email: str) -> str:
    return f"otp:{email}"


def attempt_key(email: str) -> str:
    return f"otp_attempt:{email}"


def send_otp_email(to_email: str, otp_code: str, expire_seconds: int) -> None:
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "您的驗證碼"
    msg["From"] = smtp_user
    msg["To"] = to_email

    html = f"""
    <html><body>
      <h2>您的一次性驗證碼</h2>
      <p style="font-size:32px;font-weight:bold;letter-spacing:8px;">{otp_code}</p>
      <p>此驗證碼 <strong>{expire_seconds // 60} 分鐘</strong>內有效。</p>
    </body></html>
    """
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"),
                      int(os.getenv("SMTP_PORT", 587))) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())
