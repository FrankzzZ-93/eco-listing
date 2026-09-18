from app import app_settings


def test_listing_limits_defaults():
    limits = app_settings._normalize({})["listing_limits"]
    assert limits["title_max_chars"] == 75
    assert limits["item_highlights_max_chars"] == 125
    assert limits["title_min_chars"] == 0


def test_listing_limits_override_and_invalid_values_ignored():
    raw = {
        "listing_limits": {
            "title_max_chars": 80,
            "item_highlights_max_chars": 0,  # max must be > 0 -> ignored
            "bullets_total_min_bytes": -1,  # negative -> ignored
            "description_min_chars": 0,  # 0 disables a minimum -> kept
            "st_max_bytes": "249",  # wrong type -> ignored
        }
    }
    limits = app_settings._normalize(raw)["listing_limits"]
    assert limits["title_max_chars"] == 80
    assert limits["item_highlights_max_chars"] == 125
    assert limits["bullets_total_min_bytes"] == 700
    assert limits["description_min_chars"] == 0
    assert limits["st_max_bytes"] == 249


def test_min_at_or_above_max_is_disabled():
    raw = {"listing_limits": {"title_max_chars": 75, "title_min_chars": 120}}
    limits = app_settings._normalize(raw)["listing_limits"]
    assert limits["title_min_chars"] == 0


def test_public_view_exposes_listing_limits():
    view = app_settings.public_view(app_settings._normalize({}))
    assert view["listing_limits"]["title_max_chars"] == 75
