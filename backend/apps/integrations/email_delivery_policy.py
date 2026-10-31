"""Quota refusal is terminal; transport failures already hold their quota slot."""

DAILY_EMAIL_LIMIT_REACHED = "daily_email_limit_reached"
LEGACY_DAILY_EMAIL_LIMIT_REACHED = "Daily email limit reached for this space."


def email_quota_denied(log):
    return log.status == "failed" and log.error in {
        DAILY_EMAIL_LIMIT_REACHED,
        LEGACY_DAILY_EMAIL_LIMIT_REACHED,
    }
