"""Cross-cutting endpoints that belong to no domain module."""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


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
