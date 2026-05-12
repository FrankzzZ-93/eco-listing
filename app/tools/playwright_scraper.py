"""Playwright-based structured scraper for Amazon product pages."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PwTimeout

from app.config import settings

logger = logging.getLogger(__name__)


class AntiScrapingError(Exception):
    """Raised when Amazon returns a CAPTCHA or blocks the request."""


class PlaywrightScraper:
    """Fast, precise scraper using CSS selectors for Amazon pages.

    Designed for structured data extraction where page layout is known.
    """

    def __init__(self):
        self._browser: Browser | None = None

    async def _get_browser(self) -> Browser:
        if self._browser is None or not self._browser.is_connected():
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(
                headless=settings.browser_headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
        return self._browser

    async def _new_page(self) -> Page:
        browser = await self._get_browser()
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()
        return page

    async def get_listing(self, asin: str, site: str) -> dict[str, Any]:
        """Scrape main listing content: title, bullet points, description."""
        url = f"https://{site}/dp/{asin}"
        page = await self._new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._random_delay()
            await self._check_captcha(page)

            title = await self._safe_text(page, "#productTitle")
            bullet_points = await self._get_bullet_points(page)
            description = await self._safe_text(page, "#productDescription")
            a_plus = await self._get_a_plus_content(page)

            return {
                "asin": asin,
                "site": site,
                "title": title,
                "bullet_points": bullet_points,
                "description": description,
                "a_plus_content": a_plus,
            }
        finally:
            await page.close()

    async def get_reviews(self, asin: str, site: str, max_pages: int = 3) -> list[dict[str, Any]]:
        """Scrape customer reviews from the reviews page."""
        base_url = f"https://{site}/product-reviews/{asin}"
        reviews: list[dict[str, Any]] = []
        page = await self._new_page()

        try:
            for page_num in range(1, max_pages + 1):
                url = f"{base_url}?pageNumber={page_num}"
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await self._random_delay()
                await self._check_captcha(page)

                review_elements = await page.query_selector_all("[data-hook='review']")
                if not review_elements:
                    break

                for el in review_elements:
                    title_el = await el.query_selector("[data-hook='review-title'] span")
                    body_el = await el.query_selector("[data-hook='review-body'] span")
                    rating_el = await el.query_selector("[data-hook='review-star-rating'] span")

                    review_title = await title_el.inner_text() if title_el else ""
                    review_body = await body_el.inner_text() if body_el else ""
                    rating_text = await rating_el.inner_text() if rating_el else ""

                    rating = 0.0
                    if rating_text:
                        try:
                            rating = float(rating_text.split(" ")[0])
                        except (ValueError, IndexError):
                            pass

                    reviews.append({
                        "title": review_title.strip(),
                        "body": review_body.strip(),
                        "rating": rating,
                    })

                await self._random_delay()

            return reviews
        finally:
            await page.close()

    async def _get_bullet_points(self, page: Page) -> list[str]:
        # Try multiple selectors to handle different Amazon page layouts
        selectors = [
            "#feature-bullets li span.a-list-item",
            "#feature-bullets .a-list-item",
            "#featurebullets_feature_div .a-list-item",
        ]

        elements = []
        for sel in selectors:
            elements = await page.query_selector_all(sel)
            if elements:
                break

        skip_prefixes = (
            "Make sure",
            "International products have separate",
            "Manufacturer warranty may not",
            "Learn more about",
        )

        results = []
        for el in elements:
            text = (await el.inner_text()).strip()
            if text and not any(text.startswith(p) for p in skip_prefixes):
                results.append(text)
        return results

    async def _get_a_plus_content(self, page: Page) -> str:
        el = await page.query_selector("#aplus")
        if el:
            return (await el.inner_text()).strip()
        return ""

    async def _safe_text(self, page: Page, selector: str) -> str:
        try:
            el = await page.wait_for_selector(selector, timeout=5000)
            if el:
                return (await el.inner_text()).strip()
        except PwTimeout:
            pass
        return ""

    async def _check_captcha(self, page: Page) -> None:
        captcha = await page.query_selector("form[action='/errors/validateCaptcha']")
        if captcha:
            raise AntiScrapingError("Amazon CAPTCHA detected")

        title_el = await page.query_selector("title")
        if title_el:
            title_text = await title_el.inner_text()
            blocked_titles = ("Robot Check", "Sorry!", "Amazon Sign-In", "Sign-In")
            if any(t in title_text for t in blocked_titles):
                raise AntiScrapingError(f"Amazon anti-scraping: {title_text}")

        # Check for sign-in form redirect
        signin_form = await page.query_selector("form[name='signIn']")
        if signin_form:
            raise AntiScrapingError("Amazon sign-in redirect detected")

    @staticmethod
    async def _random_delay():
        await asyncio.sleep(random.uniform(1.5, 4.0))

    async def close(self):
        if self._browser and self._browser.is_connected():
            await self._browser.close()
            self._browser = None
