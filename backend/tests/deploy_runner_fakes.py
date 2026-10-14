"""Run the host installer against an isolated home and fake external tools."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path("/workspace") if Path("/workspace/install.sh").exists() else Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or "bash"
TOKEN = "one-time-registration-sensitive-test-token"
REMOVE_TOKEN = "one-time-removal-sensitive-test-token"


def executable(path, source):
    path.write_text(source, encoding="utf-8", newline="\n")
    path.chmod(0o755)


class RunnerHost:
    def __init__(self, path):
        self.path = path
        self.scripts = path / "scripts"
        self.scripts.mkdir()
        for name in ("install-deploy-runner.sh", "env-file.sh", "host-image.sh", "retire-update-polling.sh"):
            shutil.copy(ROOT / "scripts" / name, self.scripts / name)
        (path / ".env").write_text("SPACEWORKS_REPOSITORY=example/Fork\n", encoding="utf-8")
        self.root = subprocess.check_output([BASH, "-c", "pwd"], cwd=path, text=True).strip()
        self.home = path / "home"
        self.home.mkdir()
        self.runner = self.home / "spaceworks-actions-runner"
        self.bin = path / "bin"
        self.bin.mkdir()
        self.calls = path / "calls"
        self.env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                    "HOME": f"{self.root}/home", "CALLS": f"{self.root}/calls",
                    "RUNNER_TOKEN": TOKEN, "RUNNER_REMOVE_TOKEN": REMOVE_TOKEN,
                    "SPACEWORKS_REPOSITORY": "", "SPACEWORKS_RUNNER_ACCEPT_RISK": "",
                    "FAKE_UID": "1000", "FAKE_ARCH": "x86_64", "FAKE_OS": "Linux",
                    "FAKE_SYSTEMD": "1", "FAKE_POLICY": "all_external_contributors"}
        # Bash's directory test is a builtin. Intercept just the real-systemd probe;
        # all other file and directory tests still consult the isolated filesystem.
        executable(path / "bash-env", '''test() {
  if [[ "$#" == 2 && "$1" == -d && "$2" == /run/systemd/system ]]; then
    [[ "$FAKE_SYSTEMD" == 1 ]]; else builtin test "$@"; fi
}
''')
        self.env["BASH_ENV"] = f"{self.root}/bash-env"
        self.fake("id", '''case "$1" in -u) echo "$FAKE_UID";; -un) echo install-owner;; *) echo 1000;; esac''')
        self.fake("uname", '''case "$1" in -m) echo "$FAKE_ARCH";; *) echo "$FAKE_OS";; esac''')
        self.fake("hostname", "echo production")
        self.fake("python3", '"$FAKE_PYTHON" "$@"')
        self.env["FAKE_PYTHON"] = Path(sys.executable).as_posix()
        self.env["FAKE_RUNNER"] = self.runner.as_posix()
        # Git Bash mkdir -p probes inaccessible Windows ancestors in a managed
        # sandbox; Python creates the same target within the allowed workspace.
        self.fake("mkdir", '''if [[ "$*" == "-p $HOME/spaceworks-actions-runner" ]]; then
  "$FAKE_PYTHON" -c 'import os; from pathlib import Path; Path(os.environ["FAKE_RUNNER"]).mkdir(exist_ok=True)'
else /usr/bin/mkdir "$@"; fi''')
        self.fake("systemctl", "exit 0")
        self.fake("sudo", '''printf 'sudo|%s\\n' "$*" >> "$CALLS"; "$@"''')
        self.fake("gh", '''printf 'gh|%s\\n' "$*" >> "$CALLS"; echo "$FAKE_POLICY"; exit "${FAKE_GH_FAIL:-0}"''')
        self.fake("curl", '''printf 'curl|%s\\n' "$*" >> "$CALLS"
while [[ "$#" -gt 0 ]]; do
  if [[ "$1" == -o || "$1" == --output ]]; then touch "$2"; shift; fi
  shift
done
''')
        self.fake("sha256sum", '''input="$(cat)"; printf 'sha256sum|%s|%s\\n' "$*" "$input" >> "$CALLS"
exit "${FAKE_CHECKSUM_FAIL:-0}"
''')
        self.fake("tar", '''printf 'tar|%s\\n' "$*" >> "$CALLS"
destination="$PWD"
while [[ "$#" -gt 0 ]]; do
  if [[ "$1" == -C ]]; then destination="$2"; shift; fi
  shift
done
cp "$FAKE_CONFIG" "$destination/config.sh"
cp "$FAKE_SVC" "$destination/svc.sh"
"$FAKE_PYTHON" -c 'import sys; from pathlib import Path; Path(sys.argv[1]).mkdir(parents=True, exist_ok=True)' "$destination/bin"
printf '#!/usr/bin/env bash\\nprintf "deps|%%s\\\\n" "$*" >> "$CALLS"\\n' > "$destination/bin/installdependencies.sh"
chmod +x "$destination/bin/installdependencies.sh"
''')
        self.fake("crontab", '''if [[ "$1" == -l ]]; then
  printf '1 2 * * * %s/scripts/update.sh # Space Works automatic production update\\n' "$FAKE_ROOT"
  echo '3 4 * * * keep-other-job'
else cat > "$FAKE_ROOT/retained-cron"; fi
''')
        executable(path / "fake-config", '''#!/usr/bin/env bash
printf 'config|%s\\n' "$*" >> "$CALLS"
# Upstream tools may print credentials; the installer suppresses their output.
printf '%s\\n' "${ACTIONS_RUNNER_INPUT_TOKEN:-}"
printf '%s\\n' "${ACTIONS_RUNNER_INPUT_TOKEN:-}" >&2
if [[ "${ACTIONS_RUNNER_INPUT_TOKEN:-}" != "$EXPECTED_TOKEN" ]]; then exit 88; fi
if [[ "$1" == remove ]]; then rm -f .runner; else
  printf '{"gitHubUrl":"https://github.com/example/Fork"}\\n' > .runner
fi
''')
        executable(path / "fake-svc", '''#!/usr/bin/env bash
printf 'svc|%s\\n' "$*" >> "$CALLS"
case "$1" in install) touch .service;; uninstall) rm -f .service;; esac
''')
        self.env.update(FAKE_CONFIG=f"{self.root}/fake-config", FAKE_SVC=f"{self.root}/fake-svc",
                        FAKE_ROOT=self.root, EXPECTED_TOKEN=TOKEN)

    def fake(self, name, body):
        executable(self.bin / name, "#!/usr/bin/env bash\n" + body + "\n")

    def configured(self, repository="example/Fork", service=True):
        self.runner.mkdir()
        shutil.copy(self.path / "fake-config", self.runner / "config.sh")
        shutil.copy(self.path / "fake-svc", self.runner / "svc.sh")
        (self.runner / ".runner").write_text(
            '{"gitHubUrl":"https://github.com/' + repository + '"}\n', encoding="utf-8")
        (self.runner / ".env").write_text("KEEP=value\nSPACEWORKS_INSTALL_DIR=/old\n", encoding="utf-8")
        if service:
            (self.runner / ".service").touch()

    def run(self, *args, **env):
        result = subprocess.run([BASH, str(self.scripts / "install-deploy-runner.sh"), *args],
                                cwd=self.path, env={**self.env, **env},
                                capture_output=True, text=True, timeout=30)
        # Secrets must not occur in output, argv traces or any persisted file.
        for token in (TOKEN, REMOVE_TOKEN):
            assert token not in result.stdout + result.stderr
            for file in self.path.rglob("*"):
                if file.is_file():
                    assert token.encode() not in file.read_bytes(), file
        return result

    def recorded(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []
