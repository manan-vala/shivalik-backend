"""Cross-cutting endpoints that belong to no domain module."""

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

telemetry_log = logging.getLogger("shivalik.telemetry")


@extend_schema(
    summary="Liveness probe",
    description="Unauthenticated readiness check for load balancers and CI.",
    responses={200: dict},
    auth=[],
)
@api_view(["GET"])
@permission_classes([AllowAny])  # one of four deliberate public routes
def health(request):
    return Response({"status": "success", "message": "Backend running"})


class TelemetryEventSerializer(serializers.Serializer):
    LEVELS = {"error": logging.ERROR, "warning": logging.WARNING, "info": logging.INFO}

    level = serializers.ChoiceField(choices=sorted(LEVELS), default="info")
    event = serializers.RegexField(r"^[A-Za-z0-9_.:-]+$", max_length=100)
    message = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    url = serializers.CharField(max_length=500, required=False, allow_blank=True)
    stack = serializers.CharField(max_length=8000, required=False, allow_blank=True)
    context = serializers.DictField(required=False)

    def validate_context(self, value):
        # Bounded so one client cannot turn the log into a disk-filling sink.
        if len(str(value)) > 4000:
            raise serializers.ValidationError("Context is too large (4000 characters max).")
        return value


class TelemetryThrottle(UserRateThrottle):
    scope = "telemetry"


@extend_schema(
    summary="Report a frontend event",
    description=(
        "Frontend errors and UI events. Written to the operational log only, "
        "never to the database."
    ),
    request=TelemetryEventSerializer,
    responses={204: None},
)
@api_view(["POST"])
@throttle_classes([TelemetryThrottle])
def telemetry(request):
    serializer = TelemetryEventSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    event = serializer.validated_data
    telemetry_log.log(
        TelemetryEventSerializer.LEVELS[event["level"]],
        "frontend %s",
        event["event"],
        extra={"user_id": request.user.pk, "telemetry": event},
    )
    return Response(status=status.HTTP_204_NO_CONTENT)
