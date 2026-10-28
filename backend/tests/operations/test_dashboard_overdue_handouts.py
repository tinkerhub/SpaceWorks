from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.operations import views_dashboard
from tests.return_helpers import make_space, make_user

pytestmark = pytest.mark.django_db


def test_overdue_handout_counts_once_and_reviewed_loan_still_counts():
    makerspace = make_space("dashboard-overdue-handout")
    requester = make_user("dashboard-overdue-requester", access_status=User.AccessStatus.ACTIVE)
    overdue = timezone.now() - timedelta(days=1)

    def issued_request():
        return HardwareRequest.objects.create(
            makerspace=makerspace,
            requester=requester,
            requester_username=requester.username,
            status=HardwareRequest.Status.ISSUED,
            return_due_at=overdue,
        )

    issued_request()  # reviewed loan, no PublicToolLoan
    handout = issued_request()  # self-checkout/direct handouts stamp both due dates
    PublicToolLoan.objects.create(
        makerspace=makerspace,
        request=handout,
        requester=requester,
        target_type="direct",
        target_id=handout.id,
        target_label="Handout",
        due_at=overdue,
    )

    assert views_dashboard.build_dashboard(makerspace)["overdue_loans"] == 2
