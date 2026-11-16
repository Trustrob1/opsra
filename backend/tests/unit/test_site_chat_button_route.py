"""WEBCHAT-SITE-2: the per-site chat button switch (routes)."""
from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi import HTTPException

from app.routers import sites as r


class Q:
    def __init__(self, db): self.db, self.upd = db, None
    def select(self, *a): return self
    def eq(self, *a): return self
    def is_(self, *a): return self
    def limit(self, *a): return self
    def update(self, d): self.upd = d; return self
    def insert(self, d): return self
    def execute(self):
        if self.upd is not None:
            self.db.site.update(self.upd)
        return SimpleNamespace(data=[dict(self.db.site)])


class DB:
    def __init__(self): self.site = {"id": "s1", "org_id": "o1", "chat_button": False}
    def table(self, n): return Q(self)


def org(role="owner"): return {"org_id": "o1", "id": "u1", "roles": {"template": role}}


def test_default_off_then_on_and_off():
    db = DB()
    with mock.patch("app.services.site_chat_button.account_chat", return_value={"link": "x"}):
        assert r.get_chat_button("s1", org=org(), db=db).data == {"enabled": False, "account_ready": True}
        res = r.set_chat_button("s1", r.SiteChatButtonBody(enabled=True), org=org(), db=db)
        assert res.data["enabled"] is True and db.site["chat_button"] is True
        r.set_chat_button("s1", r.SiteChatButtonBody(enabled=False), org=org(), db=db)
        assert db.site["chat_button"] is False


def test_account_not_ready_is_reported():
    with mock.patch("app.services.site_chat_button.account_chat", return_value=None):
        assert r.get_chat_button("s1", org=org(), db=DB()).data["account_ready"] is False


def test_only_owner_or_ops_manager_can_switch():
    with pytest.raises(HTTPException) as e:
        r.set_chat_button("s1", r.SiteChatButtonBody(enabled=True), org=org("sales_agent"), db=DB())
    assert e.value.status_code == 403
