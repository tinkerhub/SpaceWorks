"""Small on-disk migration fixtures; none of their Python or SQL is executed."""

from pathlib import Path


HELPERS = (
    "_0025_expectation_sql.py",
    "_0025_source_shape_sql.py",
    "_0025_sequence_sql.py",
    "_0025_installation_sql.py",
    "_0025_trigger_sql.py",
    "_0025_stage_sql.py",
)
ENTRYPOINT = "backup/migrations/0025_bind_installation.py"
TRIGGER = "backup/migrations/_0025_trigger_sql.py"
NESTED_HELPER = "backup/migrations/lib/guards.py"
DATA = "backup/migrations/data/shape.sql"
INIT = "backup/migrations/lib/__init__.py"
ORPHAN = "helper_only/migrations/unreferenced.bin"
POISON = b"raise AssertionError('migration source must never execute')\n"


def tree_files():
    files = {
        ENTRYPOINT: (
            b"from ._0025_trigger_sql import SQL\n"
            b"from importlib import import_module\n"
            b"def frozen(name):\n"
            b"    return import_module(f'apps.backup.migrations._0025_{name}_sql').SQL\n"
            + POISON
        ),
        "backup/migrations/__init__.py": POISON,
        NESTED_HELPER: POISON,
        INIT: POISON,
        DATA: b"SELECT 'source shape';\n",
        "helper_only/migrations/__init__.py": POISON,
        ORPHAN: b"not imported by any numbered migration\x00\n",
    }
    for name in HELPERS:
        files[f"backup/migrations/{name}"] = (
            b"SQL = 'SELECT 1;'\nREVERSE = 'SELECT 2;'\n" + POISON
        )
    return files


def write_tree(root, files=None):
    root = Path(root).resolve()
    for relative, content in (tree_files() if files is None else files).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def regenerate_marker(installation, settings):
    # Exercise the existing installer -> capability_marker_payload -> fsynced writer.
    from scripts.install_producer_capability import install_capability

    return install_capability(
        marker=installation["marker"].resolve(),
        scripts_dir=installation["scripts"].resolve(),
        entrypoint=installation["entrypoint"].resolve(),
        migrations_dir=installation["migrations"].resolve(),
        verification_key=settings.BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY,
        require_root_owned=False,
    )


def install_tree(installation, settings):
    root = write_tree(installation["migrations"])
    settings.BACKUP_PRODUCER_MIGRATIONS_DIR = str(root)
    regenerate_marker(installation, settings)
    return root
