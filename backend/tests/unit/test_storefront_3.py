"""STOREFRONT-3: the owner can hide the shop name next to the logo."""
from app.services import catalog_storefront_service as sf
from app.routers.catalog import CatalogConfigUpdate


def test_name_with_logo_default_on():
    assert sf.public_style({})["show_name_with_logo"] is True
    assert sf.public_style(None)["show_name_with_logo"] is True
    assert sf.public_style({"show_name_with_logo": None})["show_name_with_logo"] is True


def test_name_with_logo_off_only_when_false():
    assert sf.public_style({"show_name_with_logo": False})["show_name_with_logo"] is False
    assert sf.public_style({"show_name_with_logo": "no"})["show_name_with_logo"] is True


def test_config_update_accepts_switch():
    assert CatalogConfigUpdate(show_name_with_logo=False).show_name_with_logo is False
    assert CatalogConfigUpdate().show_name_with_logo is None
