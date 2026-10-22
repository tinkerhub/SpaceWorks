"""The public borrow form's headers must survive a cross-origin preflight.

The SPA is served from another origin in a split deployment (Netlify + API host), and the
check-in / account-less submit sends `Idempotency-Key`. A header missing from
`CORS_ALLOW_HEADERS` makes the browser refuse the request before it reaches the view.
"""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@override_settings(CORS_ALLOWED_ORIGINS=["https://spa.example.test"])
def test_borrow_submit_preflight_allows_the_idempotency_key():
    response = APIClient().options(
        "/api/v1/public/any-space/requests",
        HTTP_ORIGIN="https://spa.example.test",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,idempotency-key",
    )

    allowed = response.headers.get("Access-Control-Allow-Headers", "").lower()
    assert response.status_code == 200
    assert "idempotency-key" in allowed
