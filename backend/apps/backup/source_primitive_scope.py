"""Checkout scope: enumerate first, classify every file, never inspect secrets."""

from datetime import date
from pathlib import Path
import os

from .source_primitive_fingerprint import SourcePrimitiveCoverageError, bytes_digest


PRUNED = {
    ".git", ".aws", ".ssh", ".agents", ".codex", ".claude", ".impeccable",
    "node_modules", "venv", ".venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".cache", "dist", "build", "coverage",
    ".vite", ".vitest", ".idea", ".vscode", ".zed", ".worktrees",
    ".DS_Store", ".coverage", "htmlcov", ".hypothesis", ".tox", "staticfiles",
}
LANGUAGES = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "typescript", ".jsx": "typescript", ".mjs": "typescript",
    ".cjs": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".yml": "container", ".yaml": "container", ".sql": "sql",
    ".ps1": "opaque", ".html": "opaque", ".j2": "opaque",
    ".jinja": "opaque", ".jinja2": "opaque", ".tpl": "opaque",
    ".wasm": "binary",
}
DATA_EXTENSIONS = {
    ".json", ".toml", ".ini", ".cfg", ".conf", ".txt", ".xml",
    ".css", ".map", ".lock", ".in", ".service", ".timer", ".svg",
}
DOCUMENT_EXTENSIONS = {".md", ".rst", ".pdf"}
AUDIT_REPORT_EXTENSIONS = {".txt", ".log", ".xml", ".json", ".csv"}
PUBLIC_ENV_TEMPLATES = {
    ".env.example", ".env.production.example", "backend/.env.example",
    "frontend/.env.example",
}
ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".webm", ".otf",
}
DATA_NAMES = {
    "VERSION", "LICENSE", "NOTICE", ".gitignore", ".gitattributes",
    ".dockerignore", ".prettierignore", ".nvmrc", ".python-version",
    ".editorconfig", ".npmrc", ".prettierrc", ".browserslistrc",
}


def private_name(name):
    lowered = name.lower()
    credential_data = "credential" in lowered and Path(lowered).suffix not in LANGUAGES
    return (lowered.startswith(".env") or lowered in {"credentials", "secrets"}
            or credential_data or lowered.endswith((".pem", ".key", ".p12"))
            or lowered.startswith("id_rsa") or lowered.startswith("id_ed25519"))


def _dated_audit_report(path):
    parts = path.parts
    if (len(parts) < 4 or parts[:2] != ("docs", "audits")
            or path.suffix.lower() not in AUDIT_REPORT_EXTENSIONS):
        return False
    try:
        return date.fromisoformat(parts[2]).isoformat() == parts[2]
    except ValueError:
        return False


def classify(relative):
    path = Path(relative)
    parts = path.parts
    # Exact public FILE templates only; private directory pruning stays intact.
    if path.as_posix() in PUBLIC_ENV_TEMPLATES:
        return "production-input", "opaque"
    if any(private_name(part) for part in parts):
        return "private-excluded", None
    if (parts[:1] in (("tests",), ("__tests__",))
            or parts[:2] == ("backend", "tests")
            or (parts[:1] == ("frontend",) and ("__tests__" in parts
                or any(tag in path.name for tag in (".test.", ".spec."))))):
        return "test-excluded", None
    if parts[:2] == ("docs", "source-audit") and path.suffix == ".json":
        return "review-ledger", None
    if path.suffix.lower() in DOCUMENT_EXTENSIONS or _dated_audit_report(path):
        return "documentation", None
    if path.suffix.lower() in ASSET_EXTENSIONS:
        return "static-asset", None
    if path.name.startswith("Dockerfile") or path.name.startswith("Caddyfile"):
        return "production-source", "container"
    if path.suffix.lower() in LANGUAGES:
        return "production-source", LANGUAGES[path.suffix.lower()]
    if path.suffix.lower() in DATA_EXTENSIONS or path.name in DATA_NAMES:
        return "production-input", "opaque"
    # Unknown files are review candidates, not silently classified as documents.
    return "unsupported-source", "opaque"


def collect_scope(root):
    root = Path(root).resolve()
    inventory, sources = [], {}
    for base, directories, filenames in os.walk(root, followlinks=False):
        retained = []
        for name in sorted(directories):
            path = Path(base, name)
            rel = path.relative_to(root).as_posix()
            if name in PRUNED or private_name(name):
                # Presence of local caches/private files is not release input.
                # The exclusion policy itself is source-bound in the census.
                continue
            elif path.is_symlink():
                raise SourcePrimitiveCoverageError(f"scope symlink directory: {rel}")
            else:
                retained.append(name)
        directories[:] = retained
        for name in sorted(filenames):
            path = Path(base, name)
            rel = path.relative_to(root).as_posix()
            if name in PRUNED or rel == "frontend/tsconfig.tsbuildinfo":
                continue
            classification, language = classify(rel)
            row = {"path": rel, "classification": classification, "language": language}
            if classification == "private-excluded":
                continue
            if path.is_symlink():
                raise SourcePrimitiveCoverageError(f"scope symlink file: {rel}")
            if language:
                try:
                    raw = path.read_bytes()
                    # Binary executables still get whole-unit opaque review.
                    text = raw.hex() if language == "binary" else raw.decode("utf-8")
                except (OSError, UnicodeError) as exc:
                    raise SourcePrimitiveCoverageError(f"unreadable source: {rel}") from exc
                row["digest"] = bytes_digest(raw)
                sources[rel] = (language, text)
            inventory.append(row)
    return sorted(inventory, key=lambda row: row["path"]), sources
