"""Actual fresh installer with synthetic release, Docker and setup transports.

No network, Docker daemon, sudo, package installation or setup script is invoked.
The real archive extraction, checker, ownership, directory move and modes execute.
"""

import fcntl
import os
import pty
import select
import signal
import subprocess
import tarfile
import termios
import time


RELEASE = "v1.2.3-main.1.0123456789ab"


def executable(path, body):
    path.write_text("#!/bin/sh\nset -eu\n" + body)
    path.chmod(0o755)


def fresh_install(source, workspace, *, nonroot=False):
    bins = workspace / "wire"
    bins.mkdir(mode=0o755)
    archive = workspace / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as writer:
        writer.add(source, arcname="release")
    archive.chmod(0o644)
    executable(bins / "curl", '''case "$*" in
  *releases/latest*) printf '%s\\n' '{"tag_name":"v1.2.3-main.1.0123456789ab"}' ;;
  *archive/refs/tags/v1.2.3-main.1.0123456789ab.tar.gz*)
    while [ "$#" -gt 0 ]; do
      if [ "$1" = -o ]; then cp "$SPACEWORKS_TEST_RELEASE_TAR" "$2"; exit 0; fi
      shift
    done
    exit 91 ;;
  *) exit 92 ;;
esac
''')
    executable(bins / "docker", '''case "$*" in
  'compose version'|'info') exit 0 ;;
  *) echo 'UNEXPECTED DOCKER EFFECT' >&2; exit 93 ;;
esac
''')
    executable(bins / "df", "printf '%s\\n' 'Filesystem 1024-blocks Used Available Capacity Mounted on' 'synthetic 999999999 0 999999999 0% /'\n")
    executable(bins / "bash", '''[ "$1" = -c ] || exit 94
case "$2" in *'bash setup.sh') printf '%s\\n' 'synthetic setup transport reached'; exit 0 ;; *) exit 95 ;; esac
''')
    target = workspace / "new-install"
    env = {"PATH": str(bins) + ":/usr/local/bin:/usr/bin:/bin", "SPACEWORKS_DIR": str(target),
        "SPACEWORKS_TEST_RELEASE_TAR": str(archive), "SPACEWORKS_REPOSITORY": "SpaceWorks-HQ/SpaceWorks"}
    master, slave = pty.openpty()
    def terminal():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        if nonroot:
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
    process = subprocess.Popen(["/bin/bash", str(source / "install.sh")], env=env, cwd="/",
        stdin=slave, stdout=slave, stderr=slave, preexec_fn=terminal, close_fds=True)
    os.close(slave)
    output = bytearray()
    deadline = time.monotonic() + 30
    try:
        while process.poll() is None:
            if time.monotonic() > deadline:
                os.killpg(process.pid, signal.SIGKILL)
                raise AssertionError("Synthetic fresh install transport timed out")
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        while select.select([master], [], [], 0)[0]:
            try:
                chunk = os.read(master, 65536)
                if not chunk:
                    break
                output.extend(chunk)
            except OSError:
                break
        return process.wait(timeout=10), output.decode(errors="replace"), target
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
        os.close(master)
