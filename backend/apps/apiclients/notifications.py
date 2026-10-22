import logging

from apps.integrations.dispatch_channels import channel_module_blocks
from apps.integrations.email import send_makerspace_email
from apps.integrations.models import NotificationChannel
from apps.integrations.telegram import send_message

logger = logging.getLogger(__name__)


def notify_api_key_request_resolved(api_key_request):
    status = api_key_request.status
    makerspace = api_key_request.makerspace
    requester = api_key_request.requester
    label = api_key_request.label

    subject = f"{makerspace.name} API access request {status}"
    body = (
        f"Your API access request '{label}' for {makerspace.name} was {status}."
    )
    if api_key_request.resolution_note:
        body = f"{body}\n\nNote: {api_key_request.resolution_note}"
    body = f"{body}\n\nNo API secret is included in this notification."

    try:
        if requester and requester.email:
            send_makerspace_email(
                makerspace,
                subject,
                body,
                [requester.email],
                stream="api",
                event="api_key_request_resolved",
                audience="requester",
            )
    except Exception:
        logger.warning(
            "api_key_request_email_notification_failed",
            extra={"api_key_request_id": api_key_request.pk},
            exc_info=True,
        )

    try:
        # Same channel/module gate as every lifecycle alert: a space without the
        # `telegram` module gets no Telegram message, even with a bot configured.
        if not channel_module_blocks(makerspace, NotificationChannel.TELEGRAM):
            send_message(
                makerspace,
                f"API access request '{label}' was {status} for {requester or 'requester'}.",
            )
    except Exception:
        logger.warning(
            "api_key_request_telegram_notification_failed",
            extra={"api_key_request_id": api_key_request.pk},
            exc_info=True,
        )
