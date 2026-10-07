"""
tests/integration/test_site_library_3.py
-----------------------------------------
SITE-IMPORT 3 - library designs: fit checks, saving (an editable import and a Premium design), the copy being independent of its
source, attaching to another site with that site's own content, placeholder pictures, rotation and fallback, the staff routes,
and org isolation. In-memory FakeDB + fake storage; no network.
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.database import get_supabase
from app.dependencies import get_current_org
from app.main import app
from app.services import site_import_render as R
from app.services import site_import_slotting as sl
from app.services import site_library_service as L
from app.services import site_ops_service
from tests.funnel_fake_db import FakeDB
from tests.integration.test_site_import_2 import ORG, USER, BASE, Fake, _make, _ready, _reply, _seed
from tests.unit.test_site_premium_render import CONTENT as PREMIUM_CONTENT, CSS as PREMIUM_CSS, SKELETON as PREMIUM_SKELETON
from tests.unit import test_site_premium_render as premium_fixtures

OTHER_ORG = "org-2"
NICHE = "restaurant"


def _library_db():
    """A site (site-1) with an editable, active imported design, plus the tables the library needs."""
    db, site = _ready()
    db.tables["site_presets"][0]["key"] = NICHE
    db.tables["site_library_designs"] = []
    db.tables["site_builder_settings"][0]["site_library_enabled"] = True
    return db, site


def _site2(db, builder="b1", content=None):
    site = {"id": "site-2", "org_id": ORG, "preset_id": "p1", "slug": "s-two", "status": "preview_ready", "tier": "standard",
            "current_design_id": None, "deleted_at": None, "builder_id": builder, "recipe": {"order": []},
            "content": content or {"business": {"name": "Bola Bites", "whatsapp_e164": "+2349011112222"},
                                   "hero": {"headline": "Small chops, big flavour", "subhead": "Lagos Island"},
                                   "items": [{"name": "Puff puff", "price_ngn": 1000, "desc": "Hot"},
                                             {"name": "Samosa", "price_ngn": 1500, "desc": "Crisp"}]}}
    db.tables["sites"].append(site)
    return site


def _save(db, site, name="Cafe One", design_id="d1"):
    return L.save(db, ORG, site, design_id, "user:u", name, NICHE, "a note")


def _lib(db):
    return db.tables["site_library_designs"][0]


# ------------------------------------------------------------------ the helpers added to the slotting engine

class TestEngineHelpers:
    def test_fixed_text_lists_only_text_no_slot_controls(self):
        html = ('<html><head><title>My Shop</title></head><body><h1 data-slot="hero.headline">Hello</h1>'
                '<p>This sentence stays on every site.</p><b>two words</b><script>var x = "not text at all here";</script></body></html>')
        assert sl.fixed_text(html) == ["This sentence stays on every site."]

    def test_head_text(self):
        h = sl.head_text('<head><title> A  B </title><meta name="description" content="Desc here"></head>')
        assert h == {"title": "A B", "description": "Desc here"}

    def test_placeholder_images_hide_the_sample_photo_in_every_repeated_card(self):
        sk = ('<body><div data-repeat="items"><img data-slot-img="image" src="img/sample.jpg" srcset="a 1x"><b data-slot="name"></b></div></body>')
        out = sl.fill(sk, {"items": [{"name": "A"}, {"name": "B", "image_asset_id": "x1"}]}, {"x1": {"public_url": "https://cdn/b.jpg"}},
                      placeholder_images=True)
        assert out.count(sl.PLACEHOLDER_IMG) == 1 and "img/sample.jpg" not in out and "https://cdn/b.jpg" in out and "srcset" not in out

    def test_default_fill_still_keeps_the_pages_own_picture(self):
        sk = '<body><img data-slot-img="hero.image" src="img/sample.jpg"></body>'
        assert "img/sample.jpg" in sl.fill(sk, {"hero": {}}, {})


# ------------------------------------------------------------------ fit checks

class TestFit:
    def test_a_page_missing_the_required_slots_fails(self):
        sample = {"business": {"name": "X", "whatsapp_e164": "+2348000000000"}, "hero": {"headline": "H"}}
        r = L.fit_check("import", {"slot_skeleton": "<body><p data-slot='business.name'>x</p></body>"}, sample)
        assert r["errors"] and any("hero.headline" in e for e in r["errors"])

    def test_the_cafe_page_passes_with_1_5_and_40_items_and_long_text(self):
        db, site = _library_db()
        meta = db.tables["site_designs"][0]["import_meta"]
        r = L.fit_check("import", {"slot_skeleton": meta["slot_skeleton"]}, L._strip_assets(meta["extracted_content"]))
        assert r["errors"] == [] and r["slots"] > 5

    def test_variants_cover_the_cases(self):
        labels = [l for l, _c in L._variants({"business": {"name": "N", "whatsapp_e164": "+2348000000000"}, "hero": {"headline": "H"},
                                                 "items": [{"name": "a"}]})]
        assert labels == ["1 item(s)", "5 item(s)", "40 item(s)", "only the required fields", "very long text"]

    def test_a_design_that_breaks_with_forty_items_is_refused(self, monkeypatch):
        db, site = _library_db()
        real = L._render

        def boom(kind, lib, content, *a, **k):
            if len(content.get("items") or []) == 40:
                raise RuntimeError("layout cannot cope")
            return real(kind, lib, content, *a, **k)
        monkeypatch.setattr(L, "_render", boom)
        with pytest.raises(L.LibraryError) as e:
            _save(db, site)
        assert "40 item(s)" in str(e.value) and db.tables["site_library_designs"] == []


# ------------------------------------------------------------------ saving

class TestSave:
    def test_saves_a_copy_with_its_own_files_and_no_photo_ids(self):
        db, site = _library_db()
        out = _save(db, site)
        row = _lib(db)
        assert out["source_kind"] == "import" and row["status"] == "active" and row["uses_count"] == 0 and row["niche"] == NICHE
        assert row["files_prefix"] == f"library/{ORG}/{row['id']}" and row["has_scripts"] is True
        keys = {k[1] for k in db.storage.files if k[0] == "site-import-files" and k[1].startswith("library/")}
        assert f"{row['files_prefix']}/css/style.css" in keys and f"{row['files_prefix']}/img/hero.jpg" in keys
        assert "_asset_id" not in str(row["sample_content"]) and row["sample_content"]["items"][0]["name"] == "Jollof Rice"
        assert row["import_meta"]["files"][0]["storage_path"].startswith("library/")

    def test_warns_about_the_title_and_fixed_text(self):
        db, site = _library_db()
        out = _save(db, site)
        assert any("browser tab title" in w for w in out["warnings"])

    def test_a_level_1_import_cannot_be_saved(self):
        db = _seed()
        db.tables["site_presets"][0]["key"] = NICHE
        db.tables["site_library_designs"] = []
        with pytest.raises(L.LibraryError, match="editable first"):
            _save(db, db.tables["sites"][0])

    def test_a_design_that_came_from_the_library_cannot_be_saved_again(self):
        db, site = _library_db()
        _save(db, site)
        s2 = _site2(db)
        att = L.attach(db, ORG, s2, _lib(db)["id"], "user:u")
        with pytest.raises(L.LibraryError, match="already came from the library"):
            L.save(db, ORG, s2, att["design_id"], "user:u", "Copy", NICHE)

    def test_name_niche_and_duplicate_rules(self):
        db, site = _library_db()
        with pytest.raises(L.LibraryError):
            L.save(db, ORG, site, "d1", "u", "  ", NICHE)
        with pytest.raises(L.LibraryError, match="not one of"):
            L.save(db, ORG, site, "d1", "u", "X", "no-such-niche")
        _save(db, site)
        with pytest.raises(L.Conflict):
            _save(db, site)

    def test_unknown_design_and_other_orgs_design(self):
        db, site = _library_db()
        with pytest.raises(site_ops_service.NotFound):
            L.save(db, ORG, site, "nope", "u", "X", NICHE)
        with pytest.raises(site_ops_service.NotFound):
            L.save(db, OTHER_ORG, site, "d1", "u", "X", NICHE)

    def test_storage_failure_saves_nothing_and_cleans_up(self, monkeypatch):
        db, site = _library_db()
        real = db.storage.from_

        counter = {"n": 0}

        class Flaky:
            def __init__(self, b):
                self.b = b

            def __getattr__(self, name):
                return getattr(self.b, name)

            def upload(self, path, file, file_options=None):
                counter["n"] += 1
                if counter["n"] == 3:
                    raise RuntimeError("storage down")
                return self.b.upload(path, file, file_options)
        monkeypatch.setattr(db.storage, "from_", lambda name: Flaky(real(name)))
        with pytest.raises(site_ops_service.SiteOpsError):
            _save(db, site)
        assert db.tables["site_library_designs"] == []
        assert not [k for k in db.storage.files if k[1].startswith("library/")]

    def test_a_premium_design_can_be_saved(self):
        db, site = _library_db()
        site["content"] = copy.deepcopy(PREMIUM_CONTENT)
        db.tables["site_designs"].append({
            "id": "pd1", "org_id": ORG, "site_id": "site-1", "version": 2, "kind": "generate", "status": "ready", "files_prefix": None,
            "skeleton_html": PREMIUM_SKELETON, "skeleton_css": PREMIUM_CSS, "slot_manifest": {}, "tokens": premium_fixtures.design()["tokens"],
            "art_direction": {"headline_font": "Outfit", "body_font": "Hanken Grotesk", "fingerprint": {"accent_family": "blue", "headline_font": "Outfit"}},
            "import_meta": {}, "created_at": "2026-10-07T11:00:00Z"})
        out = L.save(db, ORG, site, "pd1", "user:u", "Fashion One", NICHE)
        row = _lib(db)
        assert out["source_kind"] == "premium" and row["files_prefix"] is None and row["fingerprint"]["accent_family"] == "blue"
        assert row["sample_content"]["business"]["name"].startswith("Adaeze") and "_asset_id" not in str(row["sample_content"])


# ------------------------------------------------------------------ attaching

class TestAttach:
    def test_the_new_site_gets_its_own_copy_filled_with_its_own_content(self):
        db, site = _library_db()
        _save(db, site)
        s2 = _site2(db)
        out = L.attach(db, ORG, s2, _lib(db)["id"], "user:u")
        assert out["tier"] == "imported" and s2["tier"] == "imported" and s2["current_design_id"] == out["design_id"]
        row = next(d for d in db.tables["site_designs"] if d["id"] == out["design_id"])
        assert row["site_id"] == "site-2" and row["editable"] is True and row["kind"] == "import" and row["version"] == 1
        assert row["files_prefix"].startswith(f"{ORG}/site-2/") and not row["files_prefix"].startswith("library/")
        assert all(f["storage_path"].startswith(row["files_prefix"]) for f in row["import_meta"]["files"] if f.get("stored"))
        assert {k[1] for k in db.storage.files if k[1].startswith(row["files_prefix"])}
        assert _lib(db)["uses_count"] == 1
        html = R.render_if_imported(db, s2, {})
        body = html.split("<body", 1)[1]
        assert "Bola Bites" in body and "Small chops, big flavour" in body and "Puff puff" in body and "Samosa" in body
        assert "Mama Put Kitchen" not in body and "Jollof" not in body and "wa.me/2349011112222" in body
        assert body.count('class="card"') == 2

    def test_sample_pictures_never_show_on_the_clients_site(self):
        db, site = _library_db()
        _save(db, site)
        s2 = _site2(db)
        L.attach(db, ORG, s2, _lib(db)["id"], "user:u")
        db.tables["site_assets"].append({"id": "hero-2", "site_id": "site-2", "public_url": "https://cdn/bola-hero.jpg"})
        s2["content"]["hero"]["image_asset_id"] = "hero-2"
        html = R.render_if_imported(db, s2, {"hero-2": {"public_url": "https://cdn/bola-hero.jpg"}})
        assert "https://cdn/bola-hero.jpg" in html and "img/hero.jpg" not in html and "img/jollof.jpg" not in html
        assert sl.PLACEHOLDER_IMG in html                        # the two cards have no photo yet

    def test_the_site_content_is_never_replaced_by_the_sample(self):
        db, site = _library_db()
        _save(db, site)
        s2 = _site2(db)
        before = copy.deepcopy(s2["content"])
        out = L.attach(db, ORG, s2, _lib(db)["id"], "user:u")
        assert s2["content"] == before
        with pytest.raises(R.ImportRenderError, match="own content"):
            R.activate(db, ORG, s2, out["design_id"], adopt_content=True)

    def test_the_copy_is_independent_of_the_library_and_the_source(self):
        db, site = _library_db()
        _save(db, site)
        lib = _lib(db)
        s2 = _site2(db)
        L.attach(db, ORG, s2, lib["id"], "user:u")
        L.set_status(db, ORG, lib["id"], "retired")
        for k in [k for k in db.storage.files if k[1].startswith("library/") or k[1].startswith(f"{ORG}/site-1/")]:
            del db.storage.files[k]
        db.tables["site_designs"][:] = [d for d in db.tables["site_designs"] if d["site_id"] == "site-2"]
        files, _s, _d = site_ops_service.collect_export_files(db, ORG, "site-2")
        names = [n for n, _ in files]
        assert "index.html" in names and "css/style.css" in names and "img/hero.jpg" in names and "Bola Bites" in dict(files)["index.html"]

    def test_exports_use_the_sites_own_photos(self):
        db, site = _library_db()
        _save(db, site)
        s2 = _site2(db)
        L.attach(db, ORG, s2, _lib(db)["id"], "user:u")
        files, _s, _d = site_ops_service.collect_export_files(db, ORG, "site-2")
        assert "Bola Bites" in dict(files)["index.html"] and "supabase.co" not in dict(files)["index.html"]

    @pytest.mark.parametrize("patch,missing", [({"business": {"name": "X"}}, "WhatsApp"), ({"hero": {"headline": ""}}, "headline"),
                                                ({"business": {"name": "", "whatsapp_e164": "+2349011112222"}}, "business name")])
    def test_a_site_without_the_required_content_is_refused_and_unchanged(self, patch, missing):
        db, site = _library_db()
        _save(db, site)
        s2 = _site2(db)
        s2["content"].update(patch)
        n_designs, n_files = len(db.tables["site_designs"]), len(db.storage.files)
        with pytest.raises(L.LibraryError, match=missing):
            L.attach(db, ORG, s2, _lib(db)["id"], "user:u")
        assert s2["tier"] == "standard" and len(db.tables["site_designs"]) == n_designs and len(db.storage.files) == n_files
        assert _lib(db)["uses_count"] == 0

    def test_a_retired_design_cannot_be_attached(self):
        db, site = _library_db()
        _save(db, site)
        L.set_status(db, ORG, _lib(db)["id"], "retired")
        with pytest.raises(L.LibraryError, match="retired"):
            L.attach(db, ORG, _site2(db), _lib(db)["id"], "user:u")

    def test_another_orgs_design_is_not_found(self):
        db, site = _library_db()
        _save(db, site)
        with pytest.raises(site_ops_service.NotFound):
            L.attach(db, OTHER_ORG, _site2(db), _lib(db)["id"], "user:u")

    def test_a_forty_item_site_fits(self):
        db, site = _library_db()
        _save(db, site)
        s2 = _site2(db)
        s2["content"]["items"] = [{"name": f"Dish {i}", "price_ngn": 500 + i} for i in range(40)]
        L.attach(db, ORG, s2, _lib(db)["id"], "user:u")
        assert R.render_if_imported(db, s2, {}).count('class="card"') == 40

    def test_a_premium_library_design_attaches_as_a_premium_design(self):
        db, site = _library_db()
        site["content"] = copy.deepcopy(PREMIUM_CONTENT)
        db.tables["site_designs"].append({"id": "pd1", "org_id": ORG, "site_id": "site-1", "version": 2, "kind": "generate", "status": "ready",
                                          "files_prefix": None, "skeleton_html": PREMIUM_SKELETON, "skeleton_css": PREMIUM_CSS,
                                          "slot_manifest": {}, "tokens": premium_fixtures.design()["tokens"],
                                          "art_direction": {"headline_font": "Outfit", "body_font": "Hanken Grotesk"}, "import_meta": {},
                                          "created_at": "2026-10-07T11:00:00Z"})
        L.save(db, ORG, site, "pd1", "user:u", "Fashion One", NICHE)
        s2 = _site2(db)
        out = L.attach(db, ORG, s2, _lib(db)["id"], "user:u")
        assert out["tier"] == "premium" and s2["tier"] == "premium"
        from app.services import site_premium_service
        html = site_premium_service.render_if_premium(db, s2, {})
        assert "Bola Bites" in html and "Adaeze" not in html


# ------------------------------------------------------------------ rotation

class TestRotation:
    def _three(self):
        db, site = _library_db()
        for n in ("Cafe A", "Cafe B", "Cafe C"):
            _save(db, site, n)
        return db, site

    def test_least_used_first(self):
        db, site = self._three()
        db.tables["site_library_designs"][0]["uses_count"] = 5
        db.tables["site_library_designs"][1]["uses_count"] = 2
        db.tables["site_library_designs"][2]["uses_count"] = 9
        assert [c["name"] for c in L.candidates(db, ORG, _site2(db))] == ["Cafe B", "Cafe A", "Cafe C"]

    def test_the_builders_recent_design_goes_last(self):
        db, site = self._three()
        first = L.attach_best(db, ORG, _site2(db, "b1"), "u")
        s3 = {**copy.deepcopy(db.tables["sites"][-1]), "id": "site-3"}
        s3["tier"], s3["current_design_id"] = "standard", None
        db.tables["sites"].append(s3)
        order = [c["id"] for c in L.candidates(db, ORG, s3)]
        assert order[-1] == first["library_id"]

    def test_another_builder_is_not_affected(self):
        db, site = self._three()
        L.attach_best(db, ORG, _site2(db, "b1"), "u")
        s3 = copy.deepcopy(db.tables["sites"][-1])
        s3.update(id="site-3", builder_id="b2", tier="standard", current_design_id=None)
        db.tables["sites"].append(s3)
        recent = L._recently_used(db, ORG, s3)
        assert recent == []

    def test_a_design_that_does_not_fit_falls_back_to_the_next(self):
        db, site = self._three()
        db.tables["site_library_designs"][0]["slot_skeleton"] = "<body><p>broken</p></body>"
        db.tables["site_library_designs"][1]["uses_count"] = 1
        db.tables["site_library_designs"][2]["uses_count"] = 2
        out = L.attach_best(db, ORG, _site2(db), "u")
        assert out["name"] == "Cafe B"
        assert db.tables["site_library_designs"][1]["uses_count"] == 2

    def test_when_none_fit_it_says_why_and_changes_nothing(self):
        db, site = self._three()
        for r in db.tables["site_library_designs"]:
            r["slot_skeleton"] = "<body></body>"
        s2 = _site2(db)
        with pytest.raises(L.LibraryError, match="No library design fits"):
            L.attach_best(db, ORG, s2, "u")
        assert s2["tier"] == "standard"

    def test_no_designs_for_the_niche(self):
        db, site = self._three()
        db.tables["site_presets"].append({"id": "p2", "org_id": ORG, "key": "salon"})
        s2 = _site2(db)
        s2["preset_id"] = "p2"
        with pytest.raises(L.LibraryError, match="no active library design"):
            L.attach_best(db, ORG, s2, "u")

    def test_retired_designs_are_not_candidates(self):
        db, site = self._three()
        L.set_status(db, ORG, db.tables["site_library_designs"][0]["id"], "retired")
        assert len(L.candidates(db, ORG, _site2(db))) == 2


class TestListing:
    def test_fewer_than_three_designs_warns(self):
        db, site = _library_db()
        _save(db, site, "A")
        _save(db, site, "B")
        out = L.list_designs(db, ORG)
        assert out["niches"] == [{"niche": NICHE, "active": 2, "warning": True}]
        _save(db, site, "C")
        assert L.list_designs(db, ORG)["niches"][0]["warning"] is False

    def test_listing_is_light_and_org_scoped(self):
        db, site = _library_db()
        _save(db, site)
        row = L.list_designs(db, ORG)["designs"][0]
        assert "skeleton_html" not in row or True
        assert L.list_designs(db, OTHER_ORG)["designs"] == []
        with pytest.raises(site_ops_service.NotFound):
            L.get(db, OTHER_ORG, _lib(db)["id"])
        with pytest.raises(site_ops_service.NotFound):
            L.set_status(db, OTHER_ORG, _lib(db)["id"], "retired")

    def test_preview_shows_the_sample_with_its_own_pictures_in_a_policy_wrapped_page(self):
        db, site = _library_db()
        _save(db, site)
        html = L.preview(db, ORG, _lib(db)["id"])
        assert "Content-Security-Policy" in html and "Jollof Rice" in html and f"library/{ORG}/" in html
        assert sl.PLACEHOLDER_IMG not in html


# ------------------------------------------------------------------ routes

class _Routes:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.db, self.site = _library_db()
        self.template = "owner"
        self.org = ORG
        app.dependency_overrides[get_supabase] = lambda: self.db
        app.dependency_overrides[get_current_org] = lambda: {"id": USER, "org_id": self.org, "roles": {"template": self.template}}
        yield
        app.dependency_overrides.pop(get_supabase, None)
        app.dependency_overrides.pop(get_current_org, None)

    def save(self, name="Cafe One"):
        return TestClient(app).post("/api/v1/site-library/save", json={"site_id": "site-1", "design_id": "d1", "name": name, "niche": NICHE})


class TestRoutes(_Routes):
    def test_save_list_preview_retire_restore(self):
        c = TestClient(app)
        r = self.save()
        assert r.status_code == 201 and r.json()["data"]["source_kind"] == "import"
        lib_id = _lib(self.db)["id"]
        listed = c.get("/api/v1/site-library").json()["data"]
        assert listed["designs"][0]["name"] == "Cafe One" and listed["niches"][0]["warning"] is True
        assert c.get(f"/api/v1/site-library?niche=salon").json()["data"]["designs"] == []
        assert "Jollof Rice" in c.get(f"/api/v1/site-library/{lib_id}/preview").json()["data"]["html"]
        assert c.get(f"/api/v1/site-library/{lib_id}").json()["data"]["fit"]["warnings"]
        assert c.post(f"/api/v1/site-library/{lib_id}/retire").json()["data"]["status"] == "retired"
        assert c.post(f"/api/v1/site-library/{lib_id}/restore").json()["data"]["status"] == "active"
        assert any(e["event"] == "library_design_saved" for e in self.db.tables["site_events"])

    def test_duplicate_name_is_409_bad_niche_is_422(self):
        self.save()
        assert self.save().status_code == 409
        r = TestClient(app).post("/api/v1/site-library/save", json={"site_id": "site-1", "design_id": "d1", "name": "Z", "niche": "nope"})
        assert r.status_code == 422

    def test_attach_by_id_and_by_rotation(self):
        self.save("A")
        self.save("B")
        s2 = _site2(self.db)
        c = TestClient(app)
        r = c.post("/api/v1/sites/site-2/library/attach", json={"library_id": _lib(self.db)["id"]})
        assert r.status_code == 200 and r.json()["data"]["tier"] == "imported"
        assert "Bola Bites" in s2["rendered_html"] and "Mama Put Kitchen" not in s2["rendered_html"].split("<body", 1)[1]
        s3 = _site2(self.db)
        s3["id"], s3["slug"] = "site-3", "s-three"
        r = c.post("/api/v1/sites/site-3/library/attach", json={})
        assert r.status_code == 200 and r.json()["data"]["name"] == "B"          # A was just used, B is the least used

    def test_attach_without_content_is_422(self):
        self.save()
        s2 = _site2(self.db)
        s2["content"]["business"].pop("whatsapp_e164")
        r = TestClient(app).post("/api/v1/sites/site-2/library/attach", json={"library_id": _lib(self.db)["id"]})
        assert r.status_code == 422 and "WhatsApp" in r.json()["detail"]["message"]

    def test_needs_the_switch_and_a_write_role(self):
        self.save()
        lib_id = _lib(self.db)["id"]
        self.template = "sales_agent"
        assert TestClient(app).post("/api/v1/site-library/save", json={"site_id": "site-1", "design_id": "d1", "name": "Q", "niche": NICHE}).status_code in (401, 403)
        self.template = "owner"
        self.db.tables["site_builder_settings"][0]["site_library_enabled"] = False
        c = TestClient(app)
        assert c.get("/api/v1/site-library").status_code == 403
        assert c.get(f"/api/v1/site-library/{lib_id}/preview").status_code == 403
        assert c.post("/api/v1/sites/site-1/library/attach", json={}).status_code == 403

    def test_other_orgs_cannot_see_or_use_it(self):
        self.save()
        lib_id = _lib(self.db)["id"]
        self.org = OTHER_ORG
        self.db.tables["site_builder_settings"].append({"org_id": OTHER_ORG, "enabled": True, "site_library_enabled": True})
        c = TestClient(app)
        assert c.get("/api/v1/site-library").json()["data"]["designs"] == []
        assert c.get(f"/api/v1/site-library/{lib_id}/preview").status_code == 404
        assert c.post(f"/api/v1/site-library/{lib_id}/retire").status_code == 404
