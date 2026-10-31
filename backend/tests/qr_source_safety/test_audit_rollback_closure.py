"""Additional actual HTTP writers roll back after their real service Audit INSERT."""
import pytest

from apps.audit.models import AuditLog
from tests.qr_source_safety.http_helpers import closure_lab, event, prepared
from tests.qr_source_safety.state_helpers import state
from tests.qr_target_safety_helpers import fail_after_insert

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("kind", ["api-revoke", "api-rebind", "api-cross-product", "api-cross-asset",
                                  "api-generate", "native-revoke", "native-rebind",
                                  "native-cross-product", "native-cross-asset", "native-generate"])
def test_actual_service_audit_insert_refusal_rolls_back_whole_http_domain(closure_lab, monkeypatch, kind):
    case = prepared(closure_lab, kind)
    inserted = fail_after_insert(monkeypatch, event(kind))
    before = state()
    with pytest.raises(RuntimeError, match="after real audit INSERT"):
        case.call()
    assert len(inserted) == 1
    assert not AuditLog.objects.filter(pk__in=inserted).exists()
    assert state() == before
