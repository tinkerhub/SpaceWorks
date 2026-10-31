import pytest

from tests.qr_batch_projection_safety.helpers import projection_lab


@pytest.fixture
def lab(settings):
    return projection_lab(settings)
