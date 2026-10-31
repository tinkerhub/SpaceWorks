"""Marker v2 explicitly attests the separate full format, with existing hash gates."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import pytest

from apps.backup import producer_capability
from apps.backup.full_format import FULL_FORMAT


def test_marker_v2_requires_explicit_full_claim(installed_producer_capability):
    payload = installed_producer_capability["payload"]
    assert payload["version"] == 2
    assert payload["full_formats"] == [FULL_FORMAT]
    assert producer_capability.parse_capability_marker(payload).full_formats == (FULL_FORMAT,)
    producer_capability.assert_producer_capability()


@pytest.mark.parametrize("change", ["v1", "bool-version", "missing", "empty", "unknown", "mixed", "string"])
def test_old_or_malformed_full_claim_refuses_before_capture(installed_producer_capability, change):
    payload = deepcopy(installed_producer_capability["payload"])
    if change == "v1":
        payload["version"] = 1
    elif change == "bool-version":
        payload["version"] = True
    elif change == "missing":
        payload.pop("full_formats")
    else:
        payload["full_formats"] = {"empty": [], "unknown": ["other-format"],
                                   "mixed": [FULL_FORMAT, "other-format"], "string": FULL_FORMAT}[change]
    with pytest.raises(ValueError):
        producer_capability.parse_capability_marker(payload)


def test_fixed_identity_bootstrap_import_closure_does_not_load_django_settings():
    backend = Path(__file__).resolve().parents[2]
    code = """
import importlib.util, pathlib, sys
sys.path.insert(0, sys.argv[1])
spec = importlib.util.spec_from_file_location('bounded_bootstrap', pathlib.Path(sys.argv[1]) / 'scripts/bootstrap_host_orchestration.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert 'django.conf' not in sys.modules
assert 'apps.backup.models' not in sys.modules
assert callable(module.restore_target_identity)
"""
    result = subprocess.run([sys.executable, "-I", "-c", code, str(backend)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
