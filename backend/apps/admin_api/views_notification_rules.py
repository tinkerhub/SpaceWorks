from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_notification_rules import (
    NotificationRulesPatchSerializer,
    NotificationRulesResponseSerializer,
)
from apps.audit import services as audit
from apps.integrations import notification_catalog, notification_rules
from apps.integrations.dispatch_channels import channel_module_blocks
from apps.integrations.recipients_selection import feature_available
from apps.integrations.models import (
    EmailNotificationMute,
    NotificationChannel,
    NotificationFeature,
    NotificationPreference,
)
from apps.admin_api.views_email_templates_common import _stream_module_available
from apps.makerspaces.platform import feature_enabled
from apps.makerspaces.servability import servable_queryset


def _channel_offered(makerspace, channel):
    """Whether the matrix offers a column for this channel.

    Chat channels follow their module key. Native push has no module key of its own: it
    is the `mobile.push` feature (which also needs the `mobile` module), and with it off
    `deliver_native_push` sends nothing -- so a column would store an inert preference.
    """
    if channel == NotificationChannel.NATIVE_PUSH:
        return feature_enabled(makerspace, "mobile.push")
    return not channel_module_blocks(makerspace, channel)


@extend_schema(tags=["Makerspaces"], summary="List or update makerspace notification rules")
class NotificationRulesView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def _makerspace(self, request, makerspace_id):
        return get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                servable_queryset(),
                field="id",
            ),
            pk=makerspace_id,
        )

    def _catalog(self, makerspace):
        catalog = []
        for (stream, audience), events in notification_rules.EVENT_CATALOG.items():
            if not _stream_module_available(makerspace, stream):
                continue
            targets = [
                target
                for target in notification_rules.valid_targets_for_stream(stream)
                if notification_rules.TARGETS.get(target) == audience
            ]
            catalog.append(
                {
                    "stream": stream,
                    "audience": audience,
                    "targets": targets,
                    "events": list(events),
                }
            )
        return catalog

    def _response_data(self, makerspace):
        mutes = list(
            EmailNotificationMute.objects.filter(makerspace=makerspace)
            .order_by("stream", "audience", "target", "event")
            .values("target", "stream", "event", "audience")
        )
        # Load every override row ONCE (feature, channel -> enabled) and resolve each of
        # the 20 cells in memory. Calling is_notification_enabled per cell would issue 20
        # serial NotificationPreference queries on every GET/PATCH response.
        override_rows = {
            (feature, channel): enabled
            for feature, channel, enabled in NotificationPreference.objects.filter(
                makerspace=makerspace
            ).values_list("feature", "channel", "enabled")
        }
        # A channel whose module is uninstalled is OMITTED, not rendered-and-disabled.
        # The matrix turns this list straight into columns, and a tickable Discord column
        # on a space without the Discord module would accept the tick, store the
        # preference, and then silently SKIP every send -- a misconfiguration the operator
        # has no way to see. Omitting the column makes that state unreachable, the same
        # reasoning as pruning a sidebar entry rather than permission-hiding it.
        available = [
            channel
            for channel in NotificationChannel
            if _channel_offered(makerspace, channel.value)
        ]
        channels = [
            {"key": channel.value, "label": channel.label} for channel in available
        ]
        # A feature whose module is off is omitted for the same reason as a channel: its
        # row could be ticked and stored and then would never fire.
        available_features = [
            feature for feature in NotificationFeature if feature_available(makerspace, feature)
        ]
        features = [
            {
                "key": feature.value,
                "label": feature.label,
                "events": list(notification_catalog.FEATURE_EVENTS[feature]),
            }
            for feature in available_features
        ]
        preferences = [
            {
                "feature": feature.value,
                "channel": channel.value,
                "enabled": override_rows.get(
                    (feature.value, channel.value),
                    notification_catalog.default_state(feature, channel),
                ),
                "source": (
                    "override"
                    if (feature.value, channel.value) in override_rows
                    else "default"
                ),
            }
            for feature in available_features
            # Same list as the columns, or the response would carry preference cells for
            # a channel the matrix renders no column for.
            for channel in available
        ]
        return {
            "catalog": self._catalog(makerspace),
            "mutes": mutes,
            "channels": channels,
            "features": features,
            "preferences": preferences,
        }

    def _validation_error(self, makerspace, change):
        target = change["target"]
        stream = change["stream"]
        if not _stream_module_available(makerspace, stream):
            return f"Stream '{stream}' is not installed for this makerspace."
        event = change["event"]
        audience = change["audience"]
        expected_audience = notification_rules.TARGETS.get(target)
        if audience != expected_audience:
            return f"Invalid audience '{audience}' for target '{target}'."
        if target not in notification_rules.valid_targets_for_stream(stream):
            return f"Invalid target '{target}' for stream '{stream}'."
        if not notification_rules.is_event_mutable(stream, audience, event):
            return f"Event '{event}' is not mutable for stream '{stream}' and audience '{audience}'."
        return None

    @extend_schema(responses={200: NotificationRulesResponseSerializer})
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = self._makerspace(request, makerspace_id)
        return Response(self._response_data(makerspace), status=status.HTTP_200_OK)

    @extend_schema(
        request=NotificationRulesPatchSerializer,
        responses={
            200: NotificationRulesResponseSerializer,
            400: OpenApiResponse(description="Invalid notification rule or preference change."),
            404: OpenApiResponse(description="Makerspace not found."),
        },
    )
    def patch(self, request, makerspace_id, *args, **kwargs):
        makerspace = self._makerspace(request, makerspace_id)
        payload = NotificationRulesPatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        changes = payload.validated_data.get("changes", [])
        preference_changes = payload.validated_data.get("preferences", [])

        desired_mutes = {}
        for change in changes:
            error = self._validation_error(makerspace, change)
            if error:
                return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
            key = (
                change["target"],
                change["stream"],
                change["event"],
                change["audience"],
            )
            desired_mutes[key] = change["muted"]

        desired_preferences = {}
        for preference in preference_changes:
            if not feature_available(makerspace, preference["feature"]):
                return Response(
                    {"detail": f"Feature '{preference['feature']}' is not installed for this makerspace."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not _channel_offered(makerspace, preference["channel"]):
                return Response(
                    {"detail": f"Channel '{preference['channel']}' is not available for this makerspace."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            key = (preference["feature"], preference["channel"])
            desired_preferences[key] = preference["enabled"]

        applied = []
        with transaction.atomic():
            for (target, stream, event, audience), muted in desired_mutes.items():
                if muted:
                    _, created = EmailNotificationMute.objects.get_or_create(
                        makerspace=makerspace,
                        target=target,
                        stream=stream,
                        event=event,
                        defaults={"audience": audience, "created_by": request.user},
                    )
                    changed = created
                else:
                    deleted_count, _ = EmailNotificationMute.objects.filter(
                        makerspace=makerspace,
                        target=target,
                        stream=stream,
                        event=event,
                        audience=audience,
                    ).delete()
                    changed = deleted_count > 0
                if changed:
                    applied.append(
                        {
                            "target": target,
                            "stream": stream,
                            "event": event,
                            "audience": audience,
                            "muted": muted,
                        }
                    )

            applied_preferences = []
            for (feature, channel), enabled in desired_preferences.items():
                NotificationPreference.objects.update_or_create(
                    makerspace=makerspace,
                    feature=feature,
                    channel=channel,
                    defaults={"enabled": enabled, "updated_by": request.user},
                )
                applied_preferences.append(
                    {"feature": feature, "channel": channel, "enabled": enabled}
                )

            if applied:
                audit.record(
                    request.user,
                    "email.notification_rules_updated",
                    makerspace=makerspace,
                    target=makerspace,
                    meta={"changes": applied},
                )
            if applied_preferences:
                audit.record(
                    request.user,
                    "notification.preferences_updated",
                    makerspace=makerspace,
                    target=makerspace,
                    meta={"preferences": applied_preferences},
                )

        return Response(self._response_data(makerspace), status=status.HTTP_200_OK)
