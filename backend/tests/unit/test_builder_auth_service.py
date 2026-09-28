"""
tests/unit/test_builder_auth_service.py
SITE-2B — pure unit tests for services/builder_auth_service.py.
No DB, no FastAPI — just the JWT issue/decode round trip.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from jose import jwt as jose_jwt

from app.services import builder_auth_service


BUILDER_ID = "00000000-0000-0000-0000-000000001111"
ORG_ID = "00000000-0000-0000-0000-000000002222"
OTHER_ORG_ID = "00000000-0000-0000-0000-000000003333"


class TestIssueAndDecode:
    def test_round_trip(self):
        session = builder_auth_service.issue_builder_session(builder_id=BUILDER_ID, org_id=ORG_ID)
        assert "access_token" in session and session["access_token"]
        claims = builder_auth_service.decode_builder_session(session["access_token"])
        assert claims == {"builder_id": BUILDER_ID, "org_id": ORG_ID}

    def test_token_has_builder_audience_and_12h_expiry(self):
        session = builder_auth_service.issue_builder_session(builder_id=BUILDER_ID, org_id=ORG_ID)
        raw = jose_jwt.get_unverified_claims(session["access_token"])
        assert raw["aud"] == "builder"
        assert raw["exp"] - raw["iat"] == 12 * 3600

    def test_garbage_token_returns_none(self):
        assert builder_auth_service.decode_builder_session("not-a-jwt") is None

    def test_empty_token_returns_none(self):
        assert builder_auth_service.decode_builder_session("") is None

    def test_wrong_secret_rejected(self):
        bad = jose_jwt.encode(
            {"sub": BUILDER_ID, "org_id": ORG_ID, "aud": "builder",
             "iat": int(time.time()), "exp": int(time.time()) + 3600},
            "some-other-secret", algorithm="HS256",
        )
        assert builder_auth_service.decode_builder_session(bad) is None

    def test_wrong_audience_rejected(self):
        # Signed with the SAME secret the service actually uses, but aud="staff"
        # — proves a token minted for the staff app could never pass as a builder
        # session even if someone reused the secret by mistake.
        secret = builder_auth_service._secret()
        bad = jose_jwt.encode(
            {"sub": BUILDER_ID, "org_id": ORG_ID, "aud": "staff",
             "iat": int(time.time()), "exp": int(time.time()) + 3600},
            secret, algorithm="HS256",
        )
        assert builder_auth_service.decode_builder_session(bad) is None

    def test_expired_token_rejected(self):
        secret = builder_auth_service._secret()
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        expired = jose_jwt.encode(
            {"sub": BUILDER_ID, "org_id": ORG_ID, "aud": "builder",
             "iat": int((past - timedelta(hours=1)).timestamp()), "exp": int(past.timestamp())},
            secret, algorithm="HS256",
        )
        assert builder_auth_service.decode_builder_session(expired) is None

    def test_missing_org_id_claim_rejected(self):
        secret = builder_auth_service._secret()
        bad = jose_jwt.encode(
            {"sub": BUILDER_ID, "aud": "builder", "iat": int(time.time()), "exp": int(time.time()) + 3600},
            secret, algorithm="HS256",
        )
        assert builder_auth_service.decode_builder_session(bad) is None

    def test_different_builders_get_different_tokens(self):
        a = builder_auth_service.issue_builder_session(builder_id=BUILDER_ID, org_id=ORG_ID)
        b = builder_auth_service.issue_builder_session(builder_id=BUILDER_ID, org_id=OTHER_ORG_ID)
        assert a["access_token"] != b["access_token"]
        assert builder_auth_service.decode_builder_session(a["access_token"])["org_id"] == ORG_ID
        assert builder_auth_service.decode_builder_session(b["access_token"])["org_id"] == OTHER_ORG_ID
