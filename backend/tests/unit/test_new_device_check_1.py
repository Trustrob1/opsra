"""_check_new_device: a first-time IP must reach the insert + alert path even though
postgrest's maybe_single().execute() returns None when nothing matches."""
from unittest.mock import MagicMock

from app.routers import auth


class _Q:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op = "select"

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def maybe_single(self): return self
    def insert(self, row): self.op = "insert"; self.db.inserts.append((self.table, row)); return self
    def update(self, row): self.op = "update"; self.db.updates.append((self.table, row)); return self

    def execute(self):
        if self.op == "select" and self.table == "user_devices":
            return self.db.device_result            # None = what postgrest 0.16 gives for no match
        if self.op == "select":
            return MagicMock(data=None)
        return MagicMock(data=[{}])


class _DB:
    def __init__(self, device_result):
        self.device_result = device_result
        self.inserts, self.updates = [], []

    def table(self, name): return _Q(self, name)


def _call(db):
    auth._check_new_device(db, "u1", "o1", "Trust", None, "1.2.3.4", "agent")


def test_new_ip_inserts_device_and_notification():
    db = _DB(device_result=None)
    _call(db)
    tables = [t for t, _ in db.inserts]
    assert "user_devices" in tables and "notifications" in tables
    assert not db.updates


def test_known_ip_only_refreshes_last_seen():
    db = _DB(device_result=MagicMock(data={"id": "d1"}))
    _call(db)
    assert db.inserts == []
    assert db.updates and db.updates[0][0] == "user_devices"


def test_empty_list_result_is_a_new_ip():
    db = _DB(device_result=MagicMock(data=[]))
    _call(db)
    assert "user_devices" in [t for t, _ in db.inserts]
