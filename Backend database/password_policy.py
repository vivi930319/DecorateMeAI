"""One password policy shared by web forms and JSON APIs."""

PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 128
PASSWORD_POLICY_MESSAGE = "密碼需為 6～128 碼"


def password_policy_error(value) -> str | None:
    if not isinstance(value, str):
        return PASSWORD_POLICY_MESSAGE
    if not PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH:
        return PASSWORD_POLICY_MESSAGE
    return None
