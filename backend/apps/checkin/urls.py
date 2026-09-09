from django.urls import path

from apps.checkin.views import CheckinLookupView

app_name = "checkin"

urlpatterns = [
    path(
        "public/<slug:makerspace_slug>/checkin/lookup",
        CheckinLookupView.as_view(),
        name="lookup",
    ),
]
