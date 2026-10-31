import re
from pathlib import Path

from tests.host_operator_boundary_helpers import read_sources, scan_docker_boundary

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------
# The privilege boundary: the web process never gets the Docker socket.
# --------------------------------------------------------------------------
#
# This is the reason the update path is split in two at all. Restarting containers means
# talking to the Docker daemon, and the daemon socket is root-equivalent on the host: a
# container holding it can start a privileged container mounting `/`. So the web process,
# which is the part exposed to the internet, only records requests; privileged host
# scripts act on them. Those scripts are never reachable from a request. An RCE in
# Django then buys the attacker the database, which is bad, and
# not the host, which is worse.
#
# These guard the shape of that split rather than any one line of it, because the tempting
# regression is small and looks helpful: mounting the socket "just for the updater", or
# shelling out to `docker compose restart` from a view to save the operator a step.

def _compose_files():
    return sorted([
        *REPO_ROOT.glob("docker-compose*.yml"),
        *REPO_ROOT.glob("docker/compose.*.yml"),
    ])


def test_no_compose_file_hands_a_django_service_the_docker_socket():
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _compose_files()
        if "docker.sock" in path.read_text(encoding="utf-8-sig")
    ]

    assert not offenders, (
        f"{offenders} mount the Docker daemon socket. It is root-equivalent on the host, "
        f"so a container holding it can escape to the host -- which is why updates are "
        f"applied by scripts/update.sh and the web process only records requests."
    )


def test_the_web_process_never_shells_out_to_docker():
    """The application may describe an update; only the host script may perform one."""
    docker_call = re.compile(r"""["']docker\b|\bdocker\s+compose\b|docker_client|from\s+docker\b""")
    offenders, scanned = scan_docker_boundary(read_sources(REPO_ROOT), docker_call)

    assert scanned > 100, f"only scanned {scanned} files -- the walk is not finding apps/"
    assert docker_call.search("subprocess.run(['docker', 'compose', 'up'])"), (
        "the pattern no longer recognises a docker invocation, so this test proves nothing"
    )
    assert not offenders, (
        f"{offenders} invoke Docker from application code. The web process has no socket "
        f"to reach it with, so this cannot work in a real deployment even if it passes "
        f"locally -- put privileged orchestration in a root-only host script."
    )


def test_the_host_script_is_the_thing_that_drives_docker():
    """The negative tests above are only meaningful if the work happens somewhere."""
    update_script = (REPO_ROOT / "scripts" / "update.sh").read_text(
        encoding="utf-8-sig"
    )
    compose_wrapper = (REPO_ROOT / "scripts" / "spaceworks-compose.sh").read_text(
        encoding="utf-8-sig"
    )

    assert 'COMPOSE=("$ROOT/scripts/spaceworks-compose.sh" bundled)' in update_script
    assert 'exec docker compose "${COMPOSE_ARGS[@]}" "$@"' in compose_wrapper
    assert "update_control" not in update_script
