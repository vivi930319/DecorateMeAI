import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import redis

from otp_utils import generate_otp, redis_key, send_otp_email, attempt_key

load_dotenv()
app = Flask(__name__)

# Redis 連線
r = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD") or None,
    decode_responses=True
)
OTP_EXPIRE = int(os.getenv("OTP_EXPIRE_SECONDS", 300))


# API-送出 OTP
@app.route("/send-otp", methods=["POST"])
def send_otp():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email 不得為空"}), 400

    # 防止短時間內重複送
    ttl = r.ttl(redis_key(email))
    if ttl != -2 and ttl > (OTP_EXPIRE - 60):
        return jsonify({"error": "請稍後再重新發送"}), 429

    otp = generate_otp()

    # setex,key, 秒數, 值
    r.setex(redis_key(email), OTP_EXPIRE, otp)

    try:
        send_otp_email(email, otp, OTP_EXPIRE)
        return jsonify({"message": "驗證碼已寄出"}), 200
    except Exception as e:
        r.delete(redis_key(email))   # 寄信失敗就清掉，讓用戶可以重試
        return jsonify({"error": str(e)}), 500


# API-驗證 OTP
@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()
    otp   = data.get("otp",   "").strip()

    stored = r.get(redis_key(email))

    if stored is None:
        return jsonify({"success": False, "error": "驗證碼不存在或已逾時"}), 400

    attempts = r.incr(attempt_key(email))
    r.expire(attempt_key(email), OTP_EXPIRE)
    if attempts > 5:
        r.delete(redis_key(email))
        return jsonify({"success": False, "error": "嘗試次數過多，請重新申請"}), 429

    if otp != stored:
        return jsonify({"success": False, "error": "驗證碼錯誤"}), 400

    # 驗證成功，刪除，一次性
    r.delete(redis_key(email))
    r.delete(attempt_key(email))
    return jsonify({"success": True, "message": "驗證成功"}), 200


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)
