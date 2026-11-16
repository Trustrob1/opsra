from app.services import site_chat_button as scb


def test_inject_before_last_body_once():
    btn = scb.button_html("https://opsra.com.ng/c/wc_abcdefgh?s=site", "#028090")
    html = "<html><body><p>hi</p></BODY></html>"
    out = scb.inject(html, btn)
    assert out.index(scb.MARK) < out.lower().index("</body>")
    assert scb.inject(out, btn) == out                      # never twice
    assert scb.inject("<p>no body tag</p>", btn).endswith(btn)


def test_button_is_script_free_and_escaped():
    btn = scb.button_html('https://x.y/c/k?s=site"><script>alert(1)</script>', "red;}", "left", "Chat <b>us</b>")
    assert "<script" not in btn.lower() and "&lt;b&gt;" in btn and "#028090" in btn and "left:16px" in btn
    assert "onclick" not in btn.lower() and "<style" not in btn.lower()      # inline style attribute only (works under strict policies)


class _Q:
    def __init__(self, rows): self.rows = rows
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self): return type("R", (), {"data": self.rows})


class _DB:
    """webchat_keys and sites answer from their own rows."""
    def __init__(self, key=True, site_flag=True):
        self.rows = {"webchat_keys": [{"key": "wc_abcdefgh"}] if key else [],
                     "sites": [{"chat_button": site_flag}] if site_flag is not None else []}
    def table(self, n): return _Q(self.rows[n])


def _patch_chat(cfg):
    import app.services.webchat_service as wc
    import app.services.webchat_plan_service as plan
    from unittest import mock
    from contextlib import ExitStack
    st = ExitStack()
    st.enter_context(mock.patch.object(wc, "get_config", return_value=cfg))
    st.enter_context(mock.patch.object(plan, "apply", side_effect=lambda db, o, c: c))
    return st


SITE = {"org_id": "o", "id": "s1"}


def test_files_only_html_changed_bytes_and_str():
    with _patch_chat({"enabled": True, "brand_color": "#112233"}):
        files = [("index.html", "<body></body>"), ("about.html", b"<body>x</body>"), ("images/a.jpg", b"\xff\xd8"), ("robots.txt", "x")]
        out = dict(scb.add_to_files(_DB(), SITE, files))
    assert scb.MARK in out["index.html"] and scb.MARK in out["about.html"].decode()
    assert out["images/a.jpg"] == b"\xff\xd8" and out["robots.txt"] == "x"
    assert "#112233" in out["index.html"] and "?s=site" in out["index.html"]


def test_site_switch_off_means_no_button_even_when_account_chat_is_on():
    with _patch_chat({"enabled": True}):
        assert scb.resolve(_DB(site_flag=False), "o", "s1") is None          # the agency case: client sites stay clean
        assert scb.resolve(_DB(site_flag=None), "o", "s1") is None           # site not found
        assert scb.resolve(_DB(site_flag=True), "o", None) is None           # no site id
        assert scb.add(_DB(site_flag=False), SITE, "<body></body>") == "<body></body>"
        assert scb.resolve(_DB(site_flag=True), "o", "s1") is not None


def test_off_when_chat_off_or_no_key_or_error():
    with _patch_chat({"enabled": False}):
        assert scb.resolve(_DB(), "o", "s1") is None
    with _patch_chat({"enabled": True}):
        assert scb.resolve(_DB(key=False), "o", "s1") is None
    class Boom:
        def table(self, n): raise RuntimeError("down")
    assert scb.resolve(Boom(), "o", "s1") is None
    assert scb.add(Boom(), SITE, "<body></body>") == "<body></body>"
