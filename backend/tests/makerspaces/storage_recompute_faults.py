"""Narrow cursor transport hooks; every lock/verification SQL reaches PostgreSQL."""
from apps.tenant_migration import gate_locks


class ConnectionProbe:
    def __init__(self, raw, *, before_update=None, after_update=None,
                 before_commit=None, after_commit=None):
        self.raw = raw
        self.before_update, self.after_update = before_update, after_update
        self.before_commit, self.after_commit = before_commit, after_commit
        self.statements, self.commits, self.rollbacks = [], 0, 0
        self.cursor_backend = None

    @property
    def autocommit(self):
        return self.raw.autocommit

    @autocommit.setter
    def autocommit(self, value):
        self.raw.autocommit = value

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def cursor(self):
        return CursorProbe(self, (self.cursor_backend or self.raw).cursor())

    def commit(self):
        self.commits += 1
        if self.before_commit:
            self.before_commit(self)
        self.raw.commit()
        if self.after_commit:
            self.after_commit(self)

    def rollback(self):
        self.rollbacks += 1
        return self.raw.rollback()


class CursorProbe:
    def __init__(self, owner, raw):
        self.owner, self.raw = owner, raw

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, *args):
        return self.raw.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.raw, name)

    def execute(self, statement, params=None):
        self.owner.statements.append((statement, params))
        update = statement.lstrip().startswith("UPDATE makerspaces_makerspace")
        if update and self.owner.before_update:
            self.owner.before_update(self.owner, self.raw, statement, params)
        result = self.raw.execute(statement, params)
        if update and self.owner.after_update:
            self.owner.after_update(self.owner, self.raw)
        return result


def instrument(monkeypatch, **hooks):
    original, opened = gate_locks._new_lock_connection, []

    def factory():
        raw = original()
        # Bound real advisory waits, including deliberately queued lock tests.
        with raw.cursor() as cursor:
            cursor.execute("SET statement_timeout = '12s'")
        raw.commit()
        probe = ConnectionProbe(raw, **hooks)
        opened.append(probe)
        return probe

    monkeypatch.setattr(gate_locks, "_new_lock_connection", factory)
    return opened


def updates(probe):
    return [s for s, _ in probe.statements if s.lstrip().startswith("UPDATE makerspaces_makerspace")]
