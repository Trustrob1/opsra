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


def test_files_only_html_changed_bytes_and_str():
    class Q:
        def __init__(self, rows): self.rows = rows
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": self.rows})
    class DB:
        def table(self, n): return Q([{"key": "wc_abcdefgh"}])
    import app.services.webchat_service as wc
    import app.services.webchat_plan_service as plan
    from unittest import mock
    with mock.patch.object(wc, "get_config", return_value={"enabled": True, "site_button": True, "brand_color": "#112233"}), \
         mock.patch.object(plan, "apply", side_effect=lambda db, o, c: c):
        files = [("index.html", "<body></body>"), ("about.html", b"<body>x</body>"), ("images/a.jpg", b"\xff\xd8"), ("robots.txt", "x")]
        out = dict(scb.add_to_files(DB(), {"org_id": "o"}, files))
    assert scb.MARK in out["index.html"] and scb.MARK in out["about.html"].decode()
    assert out["images/a.jpg"] == b"\xff\xd8" and out["robots.txt"] == "x"
    assert "#112233" in out["index.html"] and "?s=site" in out["index.html"]


def test_off_when_chat_off_or_button_off_or_no_key_or_error():
    import app.services.webchat_service as wc
    from unittest import mock
    class Q:
        def __init__(self, rows): self.rows = rows
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": self.rows})
    class DB:
        def __init__(self, rows): self.rows = rows
        def table(self, n): return Q(self.rows)
    assert scb.resolve(DB([]), "o") is None
    with mock.patch.object(wc, "get_config", return_value={"enabled": False}):
        assert scb.resolve(DB([{"key": "k"}]), "o") is None
    with mock.patch.object(wc, "get_config", return_value={"enabled": True, "site_button": False}):
        assert scb.resolve(DB([{"key": "k"}]), "o") is None
    class Boom:
        def table(self, n): raise RuntimeError("down")
    assert scb.resolve(Boom(), "o") is None
    assert scb.add(Boom(), {"org_id": "o"}, "<body></body>") == "<body></body>"


def test_default_and_sanitise():
    import app.services.webchat_service as wc
    assert wc.DEFAULT_CONFIG["site_button"] is True
    assert wc.sanitise_config({"site_button": False})["site_button"] is False
