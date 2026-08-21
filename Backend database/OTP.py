"""Deprecated compatibility entry point.

Do not deploy this module as a separate OTP service.  OTP routes are owned by
app.py so they share the same validation, hashing, rate limits and Gateway
authentication.
"""

from app import app


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
