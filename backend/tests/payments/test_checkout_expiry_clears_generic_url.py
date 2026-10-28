"""An expired Stripe Checkout session must not be handed out again.

The Stripe branch of `create_checkout_url` writes the session into BOTH the historic
`stripe_checkout_*` columns and the generic `checkout_url`/`external_order_id`, and the
early return reads the generic column first. Both expiry paths -- the
`checkout.session.expired` webhook and the credential-rotation close -- must clear the
generic pair too, or the dead link is returned forever.
"""

import pytest

from apps.payments.credential_validation import update_payment_settings
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.services import create_checkout_url
from apps.payments.services_webhooks import apply_webhook_event
from tests.payments.test_payment_settings_validation import pending_raw_settings


pytestmark = pytest.mark.django_db

DEAD_URL = "https://checkout.stripe.test/dead"


def _seed_both_urls(slug):
    makerspace, manager, payment_settings = pending_raw_settings(slug)
    payment = Payment.objects.get(makerspace=makerspace)
    Payment.objects.filter(pk=payment.pk).update(
        stripe_checkout_url=DEAD_URL,
        checkout_url=DEAD_URL,
        external_order_id=f"cs_{slug}",
        online_rail=Payment.OnlineRail.CHECKOUT,
    )
    return makerspace, manager, payment


def _stub_new_session(monkeypatch):
    created = []
    monkeypatch.setattr(
        "apps.payments.services.member_payment_return_url",
        lambda _makerspace: "https://space.example/member",
    )
    monkeypatch.setattr(
        "apps.payments.services.stripe_client.create_checkout_session",
        lambda _source, **params: created.append(params)
        or {"id": "cs_replacement", "url": "https://checkout.stripe.test/new"},
    )
    return created


def _assert_new_session_minted(payment, created):
    assert create_checkout_url(payment.id) == "https://checkout.stripe.test/new"
    assert len(created) == 1
    payment.refresh_from_db()
    assert payment.checkout_url == "https://checkout.stripe.test/new"
    assert payment.stripe_checkout_url == "https://checkout.stripe.test/new"
    assert payment.external_order_id == "cs_replacement"
    assert payment.stripe_checkout_session_id == "cs_replacement"


def test_expired_webhook_clears_generic_url_so_a_new_session_is_minted(monkeypatch):
    makerspace, _manager, payment = _seed_both_urls("expiry-generic-webhook")

    apply_webhook_event(
        makerspace,
        {
            "id": "evt_expiry_generic",
            "type": "checkout.session.expired",
            "data": {"object": {"id": "cs_expiry-generic-webhook"}},
        },
    )

    payment.refresh_from_db()
    assert payment.stripe_checkout_session_expired_at is not None
    assert payment.checkout_url == ""
    assert payment.external_order_id is None
    _assert_new_session_minted(payment, _stub_new_session(monkeypatch))


def test_credential_rotation_close_clears_generic_url(monkeypatch):
    # Driven through the locked service, which is the path that persists the closure;
    # the API boundary refuses rotation outright while a raw session is pending.
    makerspace, _manager, payment = _seed_both_urls("expiry-generic-rotation")
    monkeypatch.setattr(
        "apps.payments.stripe_client.checkout_session_is_closed",
        lambda *_args: True,
    )

    update_payment_settings(
        MakerspacePaymentSettings.objects.get(makerspace=makerspace),
        {"stripe_secret_key": "sk_raw_rotated"},
    )

    payment.refresh_from_db()
    assert payment.stripe_checkout_session_expired_at is not None
    assert payment.checkout_url == ""
    assert payment.external_order_id is None
    _assert_new_session_minted(payment, _stub_new_session(monkeypatch))
