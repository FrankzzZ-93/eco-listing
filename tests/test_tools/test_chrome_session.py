"""Unit tests for the real-Chrome scraping engine's pure helpers.

The browser-driving paths need a live Chrome + network, so they're exercised by
the manual spike rather than here; these cover the deterministic logic.
"""
from app.tools import chrome_session as cs


def test_jparse_handles_str_obj_and_garbage():
    assert cs._jparse('{"a": 1}') == {"a": 1}
    assert cs._jparse('[1, 2, 3]') == [1, 2, 3]
    assert cs._jparse({"already": "parsed"}) == {"already": "parsed"}
    assert cs._jparse([1, 2]) == [1, 2]
    assert cs._jparse("not json at all") is None
    assert cs._jparse(None) is None


def test_normalize_reviews_drops_empty_and_coerces_rating():
    raw = [
        {"title": "Great", "body": "Loved it", "rating": 5},
        {"title": "", "body": "", "rating": 0},        # empty -> dropped
        {"body": "body only"},                          # kept (has body)
        {"title": "title only"},                        # kept (has title)
        "garbage",                                       # non-dict -> dropped
    ]
    out = cs._normalize_reviews(raw)
    assert len(out) == 3
    # a present rating is coerced to float; a missing one falls back to 0
    assert out[0] == {"title": "Great", "body": "Loved it", "rating": 5.0}
    assert out[1] == {"title": "", "body": "body only", "rating": 0}
    assert out[2] == {"title": "title only", "body": "", "rating": 0}


def test_availability_helpers_return_bool():
    assert isinstance(cs.chrome_available(), bool)
    assert isinstance(cs.ReviewScraper.available(), bool)
    assert isinstance(cs.LoginManager.available(), bool)


def test_scrapers_share_one_chrome_session_singleton():
    # Both the review scraper and login manager must drive the SAME persistent
    # Chrome context (one user_data_dir can only be opened once).
    rs = cs.ReviewScraper()
    lm = cs.LoginManager()
    assert rs._session is lm._session is cs.ChromeSession.instance()


def test_review_views_are_star_sort_pairs():
    assert cs._REVIEW_VIEWS
    for view in cs._REVIEW_VIEWS:
        assert len(view) == 2 and all(isinstance(x, str) for x in view)
