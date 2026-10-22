"""Send one test email through the makerspace's own mail path.

The Telegram card has had a test alert for a long time; email had none, so a Space Manager
could only find out the SMTP settings were wrong when a borrower's request email failed.
This sends synchronously, through exactly the path lifecycle mail uses (the makerspace
server when one is saved, the platform sender otherwise), records it in the email log like
any other message, and answers with a readable reason when it fails.
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.audit import services as audit
from apps.integrations.dispatch import dispatch_email
from apps.integrations.models import EmailLog
from apps.makerspaces.guards import require_module
from apps.makerspaces.servability import servable_queryset

# EmailLog.error keeps only the exception class (`email_delivery_failed:<Class>`), so the
# class is what is mapped to an operator-facing reason.
_FAILURE_DETAILS = {
    "SMTPAuthenticationError": "The mail server rejected the SMTP username or password.",
    "SMTPSenderRefused": "The mail server refused the sender address. Check the from email.",
    "SMTPRecipientsRefused": "The mail server refused the recipient address.",
    "SMTPConnectError": "Couldn't connect to the mail server. Check the host and port.",
    "SMTPServerDisconnected": (
        "The mail server closed the connection. Check the port and the encryption setting."
    ),
    "SSLError": (
        "The secure connection failed. Port 587 usually needs STARTTLS and port 465 implicit SSL."
    ),
    "ConnectionRefusedError": "The mail server refused the connection. Check the host and port.",
    "TimeoutError": "The mail server didn't answer in time. Check the host and port.",
    "timeout": "The mail server didn't answer in time. Check the host and port.",
    "gaierror": "The mail server's host name couldn't be found.",
    "ValidationError": "The mail server address isn't allowed. Use a public SMTP host.",
}
_GENERIC_FAILURE = "The email couldn't be sent. Check the SMTP settings and try again."


class EmailTestResultSerializer(serializers.Serializer):
    delivered = serializers.BooleanField()
    to = serializers.EmailField()
    detail = serializers.CharField(required=False)
    email_log_id = serializers.IntegerField()


def failure_detail(error):
    return _FAILURE_DETAILS.get((error or "").rsplit(":", 1)[-1], _GENERIC_FAILURE)


@extend_schema(
    tags=["Email logs"],
    summary="Send a test email to yourself",
    request=None,
    responses={
        200: OpenApiResponse(
            response=EmailTestResultSerializer,
            description=(
                "Delivery attempt result. A failed send is an expected outcome of a "
                "diagnostic, so it is `delivered: false` with a readable `detail`."
            ),
        ),
        400: OpenApiResponse(description="Email module off, or your account has no email."),
        404: OpenApiResponse(description="Makerspace not found."),
    },
)
class EmailTestView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["post", "options"]

    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                servable_queryset(),
                field="id",
            ),
            pk=makerspace_id,
        )
        require_module(makerspace, "email")
        to_email = (request.user.email or "").strip()
        if not to_email:
            raise serializers.ValidationError(
                {"detail": "Your account has no email address to send the test to."}
            )
        log = dispatch_email(
            to_email=to_email,
            subject=f"Test email from {makerspace.name}",
            text_body=(
                f"This is a test email from {makerspace.name}.\n\n"
                "If you can read it, notification emails will reach "
                "people through the same mail settings."
            ),
            makerspace=makerspace,
            stream="test",
            event="test_email",
            audience="staff",
            connection="makerspace",
            sync=True,
        )
        delivered = log.status == EmailLog.Status.SENT
        audit.record(
            request.user,
            "email.test_sent",
            makerspace=makerspace,
            target=makerspace,
            meta={"email_log_id": log.pk, "status": log.status},
        )
        body = {"delivered": delivered, "to": to_email, "email_log_id": log.pk}
        if not delivered:
            error = log.error or ""
            # Delivery exceptions are stored as a class name; a quota refusal is already
            # a sentence and is shown as is.
            body["detail"] = (
                failure_detail(error)
                if error.startswith("email_delivery_failed:")
                else (error or _GENERIC_FAILURE)
            )
        return Response(body)
