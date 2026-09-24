from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("health/", views.health, name="health"),
    path("v1/telemetry/", views.telemetry, name="telemetry"),
]
