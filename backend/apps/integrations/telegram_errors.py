"""Turn a failed Telegram Bot API call into a reason a Space Manager can act on.

The test alert is a diagnostic: "Telegram rejected the message" for every failure sends the
operator guessing between a mistyped token, a wrong chat ID, a bot that was never added to
the group and a server with no route to Telegram. Each of those has a distinct fix, and the
Bot API says which one it is (`error_code` + `description`), so the message names it.

Nothing here carries the token: it lives in the request URL, never in the response body or
in these strings.
"""

import json

REJECTED = "rejected"
BAD_TOKEN = "bad_token"
CHAT_NOT_FOUND = "chat_not_found"
NOT_IN_CHAT = "not_in_chat"
RATE_LIMITED = "rate_limited"
UNREACHABLE = "unreachable"
TOKEN_UNREADABLE = "token_unreadable"

DETAILS = {
    BAD_TOKEN: (
        "Telegram didn't accept the bot token. Copy the full token from BotFather again "
        "and save it."
    ),
    CHAT_NOT_FOUND: (
        "Telegram couldn't find that group chat. Check the chat ID (group IDs usually start "
        "with -100) and that the bot has been added to the group."
    ),
    NOT_IN_CHAT: (
        "The bot isn't allowed to post in that chat. Add the bot to the group, then try "
        "again."
    ),
    RATE_LIMITED: "Telegram is limiting this bot right now. Wait a minute and try again.",
    UNREACHABLE: (
        "Couldn't reach Telegram from this server. Check its internet access and try again."
    ),
    TOKEN_UNREADABLE: (
        "The saved bot token can't be read on this server: its encryption key is missing "
        "or has changed. Ask the platform administrator, then save the token again."
    ),
    REJECTED: "Telegram rejected the message.",
}

_DESCRIPTION_LIMIT = 200


def read_description(http_error) -> str:
    """The Bot API's own `description`, or "" when the body is not its JSON shape."""
    try:
        body = json.loads(http_error.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return ""
    description = body.get("description") if isinstance(body, dict) else ""
    return str(description or "")[:_DESCRIPTION_LIMIT]


def classify_http_failure(status_code, description="") -> str:
    lowered = (description or "").lower()
    # 404 is what the Bot API answers for a token that is not even well-formed, 401 for
    # a well-formed one it does not know: both mean "fix the token".
    if status_code in (401, 404):
        return BAD_TOKEN
    if status_code == 429:
        return RATE_LIMITED
    if "chat not found" in lowered:
        return CHAT_NOT_FOUND
    if status_code == 403:
        return NOT_IN_CHAT
    return REJECTED


def failure_detail(reason, description="") -> str:
    detail = DETAILS.get(reason, DETAILS[REJECTED])
    if reason == REJECTED and description:
        return f"{detail} Telegram said: {description}"
    return detail
