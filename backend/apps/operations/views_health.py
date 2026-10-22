import ipaddress

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.operations.serializers import GenericObjectSerializer, HealthSerializer, ReadinessSerializer

# Headers a reverse proxy adds. Caddy, the frontend nginx and Render's edge all set
# X-Forwarded-For, so a request that crossed any of them is never "internal".
_PROXY_HEADERS = ("HTTP_X_FORWARDED_FOR", "HTTP_X_REAL_IP", "HTTP_FORWARDED")


def is_internal_caller(request):
    """A direct, unproxied caller on the deployment network.

    That is the container healthcheck and `update.sh`/`setup.sh` probing
    `localhost:8000` from inside the backend container. Anything that came through
    a public proxy carries a forwarding header the client cannot strip.
    """
    if any(request.META.get(header) for header in _PROXY_HEADERS):
        return False
    try:
        address = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
    except ValueError:
        return False
    return address.is_loopback or address.is_private


class ReadinessThrottle(SimpleRateThrottle):
    """Budget for proxied callers only; internal probes are never throttled."""

    scope = "readiness"

    def get_cache_key(self, request, view):
        if is_internal_caller(request):
            return None
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class HealthView(APIView):
    """Cheap public liveness: the process answers HTTP. Touches no database."""

    permission_classes = [AllowAny]
    serializer_class = GenericObjectSerializer

    @extend_schema(tags=["Health"], summary="Health check", request=None, responses={200: HealthSerializer})
    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"})


class ReadinessView(APIView):
    """Strict readiness. The status code is the contract for every caller; only a
    direct internal caller also gets the failure reason and the custody counts."""

    permission_classes = [AllowAny]
    serializer_class = GenericObjectSerializer
    throttle_classes = [ReadinessThrottle]

    @extend_schema(
        tags=["Health"],
        summary="Readiness check",
        description=(
            "Internal deployment probe. Proxied callers receive only `status` and are "
            "rate limited; the bundled public proxies deny this route."
        ),
        request=None,
        responses={
            200: ReadinessSerializer,
            429: OpenApiResponse(description="Rate limited (proxied callers only)."),
            503: OpenApiResponse(response=ReadinessSerializer, description="Not ready."),
        },
    )
    def get(self, request, *args, **kwargs):
        from django.conf import settings
        from apps.backup.host_readiness import HostReadinessError, assert_host_ready

        internal = is_internal_caller(request)
        try:
            assert_host_ready(settings.SPACEWORKS_HOST_MARKER_PATH)
        except HostReadinessError as exc:
            body = {"status": "unavailable"}
            if internal:
                body["detail"] = str(exc)
            return Response(body, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        from apps.encryption.readiness import assert_ready
        from apps.backup.readiness import archive_custody_readiness
        assert_ready()
        if not internal:
            return Response({"status": "ready"})
        return Response(
            {
                "status": "ready",
                "database": "ok",
                "archive_custody": archive_custody_readiness(),
            }
        )
