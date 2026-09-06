"""Clone the live Firebase Hosting version and replace only the password-reset JS.

The Hosting REST API reuses every unchanged content hash from the current
version, so this deploy cannot accidentally remove the site's images or other
assets just because the original frontend source tree is not present locally.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests


PROJECT_ID = "decorate-me"
SITE_ID = "decorate-me"
API_ROOT = "https://firebasehosting.googleapis.com/v1beta1"
PUBLIC_ROOT = "https://decorate-me.web.app"


def access_token() -> str:
    gcloud = shutil.which("gcloud")
    if not gcloud:
        raise RuntimeError("gcloud is unavailable")
    result = subprocess.run(
        [gcloud, "auth", "print-access-token"],
        capture_output=True,
        text=True,
        check=True,
    )
    token = result.stdout.strip()
    if not token:
        raise RuntimeError("gcloud returned an empty access token")
    return token


def api_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "x-goog-user-project": PROJECT_ID,
    }


def checked(response: requests.Response) -> requests.Response:
    if not response.ok:
        raise RuntimeError(
            f"Firebase Hosting API failed: {response.status_code} "
            f"{response.text[:500]}"
        )
    return response


def replace_function(source: str, signature: str, replacement: str) -> str:
    """Replace one top-level JavaScript function without a JS formatter."""
    start = source.find(signature)
    if start < 0:
        raise RuntimeError(f"Missing frontend function: {signature}")
    brace = source.find("{", start + len(signature))
    if brace < 0:
        raise RuntimeError(f"Missing opening brace: {signature}")

    depth = 0
    quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    index = brace
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
        elif block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                index += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "'\"`":
            quote = char
        elif char == "/" and nxt == "/":
            line_comment = True
            index += 1
        elif char == "/" and nxt == "*":
            block_comment = True
            index += 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[:start] + replacement + source[index + 1 :]
        index += 1
    raise RuntimeError(f"Unterminated frontend function: {signature}")


def patch_api(source: str) -> str:
    newline = "\r\n" if "\r\n" in source else "\n"
    config_marker = "            verifyOtpPath: '/auth/verify-otp',"
    if "forgotPasswordPath" not in source:
        if config_marker not in source:
            raise RuntimeError("Missing ApiConfig OTP marker")
        source = source.replace(
            config_marker,
            config_marker
            + newline
            + "            forgotPasswordPath: '/auth/forgot-password',"
            + newline
            + "            resetPasswordPath: '/auth/reset-password',",
            1,
        )

    if "async requestPasswordResetOTP(email)" not in source:
        insert_marker = "    async verifyOTP(email, otp) {"
        position = source.find(insert_marker)
        if position < 0:
            raise RuntimeError("Missing Api.verifyOTP insertion marker")
        methods = """
    async requestPasswordResetOTP(email) {
        const gateway = this.config.services.aiGateway;
        try {
            const res = await fetch(`${gateway.baseUrl}${gateway.forgotPasswordPath}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ email })
            });
            if (!res.ok) throw await this._memberApiError(res, '驗證碼寄送失敗');
            return res.json();
        } catch (err) {
            if (err?.status) throw err;
            throw new Error('無法連線到會員服務，請稍後再試。');
        }
    },

    async resetPasswordWithOTP(email, otp, newPassword, confirmPassword) {
        const gateway = this.config.services.aiGateway;
        try {
            const res = await fetch(`${gateway.baseUrl}${gateway.resetPasswordPath}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ email, otp, newPassword, confirmPassword })
            });
            if (!res.ok) throw await this._memberApiError(res, '密碼重設失敗');
            return res.json();
        } catch (err) {
            if (err?.status) throw err;
            throw new Error('無法連線到會員服務，請稍後再試。');
        }
    },

""".replace("\n", newline)
        source = source[:position] + methods + source[position:]
    return source


def patch_router(source: str) -> str:
    newline = "\r\n" if "\r\n" in source else "\n"

    replacements = {
        "async function sendForgotOTP()": """async function sendForgotOTP() {
    const email = document.getElementById('forgotEmail').value.trim();
    if (!email) { showAlert('請輸入 Email'); return; }
    try {
        const result = await Api.requestPasswordResetOTP(email);
        Router.forgotEmail = email;
        Router.forgotOtp = null;
        showToast(result?.message || '驗證碼已發送');
        showForgotVerify(email);
    } catch (err) {
        showAlert(err?.message || '驗證碼寄送失敗，請稍後再試', { type: 'error' });
    }
}""",
        "function showForgotVerify(email)": """function showForgotVerify(email) {
    var masked = maskEmail(email);
    document.getElementById('auth-layer').innerHTML = [
        '<div class="auth-overlay"><div class="auth-card">',
        '<h2>輸入驗證碼</h2>',
        '<p class="subtitle">已將 6 位數驗證碼發送至<br>' + masked + '<br>請於 5 分鐘內輸入。</p>',
        '<div class="input-group"><label>驗證碼</label><input type="text" id="forgotOtp" inputmode="numeric" maxlength="6" placeholder="6 位數驗證碼"></div>',
        '<button class="btn-gold btn-full" onclick="doVerifyForgotOTP()" style="margin-top:8px;">下一步</button>',
        '<button class="btn-outline btn-full" onclick="resendForgotOTP()" style="margin-top:12px;">重新發送驗證碼</button>',
        '<div style="margin-top:16px;"><span class="auth-link" onclick="showForgotPassword()">回上一頁</span></div>',
        '</div></div>'
    ].join('');
    setTimeout(function(){ var i=document.getElementById('forgotOtp'); if(i) i.focus(); }, 80);
}""",
        "async function doVerifyForgotOTP()": """async function doVerifyForgotOTP() {
    var code = document.getElementById('forgotOtp').value.trim();
    if (!/^\\d{6}$/.test(code)) {
        showAlert('驗證碼固定為 6 位數字', { type: 'error' });
        return;
    }
    Router.forgotOtp = code;
    showResetPassword();
}""",
        "async function resendForgotOTP()": """async function resendForgotOTP() {
    if (!Router.forgotEmail) return;
    try {
        const result = await Api.requestPasswordResetOTP(Router.forgotEmail);
        showToast(result?.message || '驗證碼已重新發送');
    } catch (err) {
        showAlert(err?.message || '驗證碼寄送失敗，請稍後再試', { type: 'error' });
    }
}""",
        "function doResetPassword()": """async function doResetPassword() {
    var p1 = document.getElementById('resetPwd').value;
    var p2 = document.getElementById('resetPwd2').value;
    if (!p1 || !p2) { showAlert('請填寫新密碼'); return; }
    if (p1.length < 6 || p1.length > 128) { showAlert('密碼需為 6～128 碼'); return; }
    if (p1 !== p2) { showAlert('兩次輸入的新密碼不一致', { type: 'error' }); return; }
    if (!Router.forgotEmail || !/^\\d{6}$/.test(Router.forgotOtp || '')) {
        showAlert('驗證碼資料已遺失，請重新申請', { type: 'error', onOk: showForgotPassword });
        return;
    }
    try {
        const result = await Api.resetPasswordWithOTP(
            Router.forgotEmail,
            Router.forgotOtp,
            p1,
            p2
        );
        Router.forgotEmail = null;
        Router.forgotOtp = null;
        showAlert(result?.message || '密碼已更新，請使用新密碼登入', {
            type: 'success',
            onOk: showLogin
        });
    } catch (err) {
        showAlert(err?.message || '密碼重設失敗，請稍後再試', { type: 'error' });
    }
}""",
    }
    for signature, replacement in replacements.items():
        source = replace_function(
            source,
            signature,
            replacement.replace("\n", newline),
        )
    return source


def validate_javascript(label: str, source: str) -> None:
    node = shutil.which("node")
    if not node:
        bundled = (
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
            / "bin"
            / "node.exe"
        )
        node = str(bundled) if bundled.is_file() else None
    if not node:
        raise RuntimeError("Node.js is required for JavaScript syntax validation")
    result = subprocess.run(
        [node, "--check", "-"],
        input=source,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"{label} JavaScript is invalid: {result.stderr[:1000]}")


def current_release(session: requests.Session) -> dict:
    response = checked(
        session.get(
            f"{API_ROOT}/sites/{SITE_ID}/releases",
            params={"pageSize": 1},
            timeout=30,
        )
    ).json()
    releases = response.get("releases") or []
    if not releases:
        raise RuntimeError("Firebase Hosting has no current release")
    return releases[0]


def version_files(session: requests.Session, version_name: str) -> dict[str, str]:
    files: dict[str, str] = {}
    page_token = ""
    while True:
        params = {"pageSize": 1000}
        if page_token:
            params["pageToken"] = page_token
        page = checked(
            session.get(
                f"{API_ROOT}/{version_name}/files",
                params=params,
                timeout=30,
            )
        ).json()
        for item in page.get("files") or []:
            files[item["path"]] = item["hash"]
        page_token = page.get("nextPageToken") or ""
        if not page_token:
            return files


def compressed_asset(source: str) -> tuple[str, bytes]:
    body = gzip.compress(source.encode("utf-8"), compresslevel=9, mtime=0)
    return hashlib.sha256(body).hexdigest(), body


def deploy() -> dict:
    token = access_token()
    session = requests.Session()
    session.headers.update(api_headers(token))

    release = current_release(session)
    current_version = release["version"]
    files = version_files(session, current_version["name"])
    if "/js/api.js" not in files or "/js/router.js" not in files:
        raise RuntimeError("Current Hosting version is missing api.js or router.js")

    cache_buster = int(time.time())
    api_source = checked(
        requests.get(f"{PUBLIC_ROOT}/js/api.js?otpfix={cache_buster}", timeout=30)
    ).text
    router_source = checked(
        requests.get(f"{PUBLIC_ROOT}/js/router.js?otpfix={cache_buster}", timeout=30)
    ).text
    api_source = patch_api(api_source)
    router_source = patch_router(router_source)

    required_markers = (
        "forgotPasswordPath: '/auth/forgot-password'",
        "async requestPasswordResetOTP(email)",
        "async resetPasswordWithOTP(email, otp, newPassword, confirmPassword)",
    )
    if not all(marker in api_source for marker in required_markers):
        raise RuntimeError("Patched api.js is missing password-reset methods")
    if "const result = await Api.requestPasswordResetOTP(email);" not in router_source:
        raise RuntimeError("Patched router.js is not using the password-reset OTP endpoint")
    if "Auth.setProfile(Object.assign({}, base, { password: p1 }))" in router_source:
        raise RuntimeError("Patched router.js still stores the password locally")
    validate_javascript("api.js", api_source)
    validate_javascript("router.js", router_source)

    api_hash, api_body = compressed_asset(api_source)
    router_hash, router_body = compressed_asset(router_source)
    files["/js/api.js"] = api_hash
    files["/js/router.js"] = router_hash

    created = checked(
        session.post(
            f"{API_ROOT}/sites/{SITE_ID}/versions",
            json={
                "config": current_version.get("config") or {},
                "labels": {"source": "password-reset-otp-fix"},
            },
            timeout=30,
        )
    ).json()
    version_name = created["name"]
    populated = checked(
        session.post(
            f"{API_ROOT}/{version_name}:populateFiles",
            json={"files": files},
            timeout=90,
        )
    ).json()
    new_assets = {api_hash: api_body, router_hash: router_body}
    required_hashes = populated.get("uploadRequiredHashes") or []
    unexpected = [value for value in required_hashes if value not in new_assets]
    if unexpected:
        raise RuntimeError(
            f"Hosting requested {len(unexpected)} unexpected existing assets; aborting release"
        )
    upload_url = populated["uploadUrl"].rstrip("/")
    upload_headers = api_headers(token)
    upload_headers["Content-Type"] = "application/octet-stream"
    for value in required_hashes:
        checked(
            requests.post(
                f"{upload_url}/{value}",
                headers=upload_headers,
                data=new_assets[value],
                timeout=90,
            )
        )

    checked(
        session.patch(
            f"{API_ROOT}/{version_name}",
            params={"updateMask": "status"},
            json={"status": "FINALIZED"},
            timeout=30,
        )
    )
    released = checked(
        session.post(
            f"{API_ROOT}/sites/{SITE_ID}/releases",
            params={"versionName": version_name},
            timeout=30,
        )
    ).json()

    verify_api = checked(
        requests.get(f"{PUBLIC_ROOT}/js/api.js?verify={int(time.time())}", timeout=30)
    ).text
    verify_router = checked(
        requests.get(f"{PUBLIC_ROOT}/js/router.js?verify={int(time.time())}", timeout=30)
    ).text
    return {
        "previousVersion": current_version["name"],
        "version": version_name,
        "release": released.get("name"),
        "fileCount": len(files),
        "uploadedFileCount": len(required_hashes),
        "apiVerified": "forgotPasswordPath: '/auth/forgot-password'" in verify_api,
        "routerVerified": (
            "await Api.requestPasswordResetOTP(email)" in verify_router
            and "await Api.resetPasswordWithOTP(" in verify_router
            and "Auth.setProfile(Object.assign({}, base, { password: p1 }))"
            not in verify_router
        ),
    }


if __name__ == "__main__":
    try:
        print(json.dumps(deploy(), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"DEPLOY_FAILED: {exc}", file=sys.stderr)
        raise
