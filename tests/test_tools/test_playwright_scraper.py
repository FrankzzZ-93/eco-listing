"""Unit tests for the Playwright scraper's pure helpers.

The browser-driving paths need live Chrome + network, so they're exercised by a
manual spike; this covers the deterministic Amazon image-URL normalization used
to turn gallery thumbnails into full-resolution originals.
"""
from app.tools import playwright_scraper as ps


def test_amz_size_modifier_stripped_to_full_res():
    sub = lambda u: ps._AMZ_SIZE_RE.sub(".", u)
    assert sub("https://m.media-amazon.com/images/I/ABC._AC_US40_.jpg") == \
        "https://m.media-amazon.com/images/I/ABC.jpg"
    assert sub("https://m.media-amazon.com/images/I/XYZ._SX300_SY300_.jpg") == \
        "https://m.media-amazon.com/images/I/XYZ.jpg"
    # already full-res URLs are untouched
    assert sub("https://m.media-amazon.com/images/I/ABC.jpg") == \
        "https://m.media-amazon.com/images/I/ABC.jpg"
