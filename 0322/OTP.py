import os, smtplib, random, string
from flask import Flask, request, jsonify
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import redis

load_dotenv()
app = Flask(__name__)

# ── Redis 連線
r = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD") or None,
    decode_responses=True
)
OTP_EXPIRE = int(os.getenv("OTP_EXPIRE_SECONDS", 300))


def generate_otp(length=6):
    return ''.join(random.choices(string.digits, k=length))

def redis_key(email):
    return f"otp:{email}"

def send_otp_email(to_email, otp_code):
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "您的驗證碼"
    msg["From"]    = smtp_user
    msg["To"]      = to_email

    html = f"""
    <html><body>
      <h2>您的一次性驗證碼</h2>
      <p style="font-size:32px;font-weight:bold;letter-spacing:8px;">{otp_code}</p>
      <p>此驗證碼 <strong>{OTP_EXPIRE // 60} 分鐘</strong>內有效，請勿分享給他人。</p>
    </body></html>
    """
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"),
                      int(os.getenv("SMTP_PORT", 587))) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())


# ── API：送出 OTP
@app.route("/send-otp", methods=["POST"])
def send_otp():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email 不得為空"}), 400

    # 防止短時間內重複送
    ttl = r.ttl(redis_key(email))
    if ttl and ttl > (OTP_EXPIRE - 60):
        return jsonify({"error": "請稍後再重新發送"}), 429

    otp = generate_otp()

    # setex,key, 秒數, 值
    r.setex(redis_key(email), OTP_EXPIRE, otp)

    try:
        send_otp_email(email, otp)
        return jsonify({"message": "驗證碼已寄出"}), 200
    except Exception as e:
        r.delete(redis_key(email))   # 寄信失敗就清掉，讓用戶可以重試
        return jsonify({"error": str(e)}), 500


# ── API：驗證 OTP
@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()
    otp   = data.get("otp",   "").strip()

    stored = r.get(redis_key(email))

    if stored is None:
        return jsonify({"success": False, "error": "驗證碼不存在或已逾時"}), 400

    if otp != stored:
        return jsonify({"success": False, "error": "驗證碼錯誤"}), 400

    # 驗證成功，刪除，一次性
    r.delete(redis_key(email))
    return jsonify({"success": True, "message": "驗證成功"}), 200


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)
