"""Dual-layer browser tool: Playwright (fast/cheap) with Codex CLI fallback (smart/resilient)."""

from __future__ import annotations

import logging
from typing import Any

from app.tools.playwright_scraper import PlaywrightScraper, AntiScrapingError
from app.tools.codex_tool import CodexTool, CodexToolError

logger = logging.getLogger(__name__)


class BrowserTool:
    """Unified browser interface for the Research Agent.

    Strategy:
      Layer 1 — Playwright: fast, precise, low-cost structured scraping.
      Layer 2 — Codex CLI: LLM-driven browser for anti-scraping fallback
               and complex interactions (Rufus Q&A expansion, dynamic content).
    """

    def __init__(self):
        self.scraper = PlaywrightScraper()
        self.codex = CodexTool()

    async def scrape_listing(self, asin: str, site: str) -> dict[str, Any]:
        """Get product listing content (title, bullets, description, A+).

        Tries Playwright first; falls back to Codex when:
        - Anti-scraping detected (CAPTCHA, sign-in redirect)
        - Result is too sparse (no bullet points extracted)
        """
        try:
            result = await self.scraper.get_listing(asin, site)
            # Quality check: if Playwright got title but no bullets, page structure is non-standard
            if result.get("title") and not result.get("bullet_points"):
                logger.warning(
                    "Playwright got title but no bullets for %s/%s (non-standard layout), "
                    "falling back to Codex CLI",
                    site, asin,
                )
                return await self._codex_scrape_listing(asin, site)
            logger.info("Listing scraped via Playwright: %s/%s", site, asin)
            return result
        except AntiScrapingError as e:
            logger.warning("Playwright blocked (%s), falling back to Codex CLI", e)
            return await self._codex_scrape_listing(asin, site)
        except Exception as e:
            logger.warning("Playwright error (%s), falling back to Codex CLI", e)
            return await self._codex_scrape_listing(asin, site)

    async def scrape_reviews(
        self, asin: str, site: str, max_pages: int = 3
    ) -> list[dict[str, Any]]:
        """Get customer reviews.

        Tries Playwright first; falls back to Codex on anti-scraping detection.
        """
        try:
            reviews = await self.scraper.get_reviews(asin, site, max_pages=max_pages)
            logger.info("Reviews scraped via Playwright: %s/%s (%d reviews)", site, asin, len(reviews))
            return reviews
        except AntiScrapingError as e:
            logger.warning("Playwright blocked for reviews (%s), falling back to Codex", e)
            return await self._codex_scrape_reviews(asin, site)
        except Exception as e:
            logger.warning("Playwright error for reviews (%s), falling back to Codex", e)
            return await self._codex_scrape_reviews(asin, site)

    async def scrape_rufus(self, asin: str, site: str) -> dict[str, Any]:
        """Get Rufus Q&A content. Always uses Codex CLI (requires interaction)."""
        logger.info("Scraping Rufus Q&A via Codex CLI: %s/%s", site, asin)
        url = f"https://{site}/dp/{asin}"

        try:
            return await self.codex.interact_and_extract(
                url=url,
                steps=[
                    "Look for the 'Customers say' or 'AI-generated from the text of customer reviews' section",
                    "If there is a 'Show more' or expand button, click it to reveal all Q&A content",
                    "Wait for the expanded content to fully load",
                ],
                extract_instruction=(
                    "Extract all Rufus Q&A pairs. For each entry, capture the question/topic "
                    "and the corresponding answer/summary. Return as JSON with key 'qa_pairs' "
                    "containing a list of objects with 'question' and 'answer' fields."
                ),
            )
        except CodexToolError as e:
            logger.error("Codex failed to scrape Rufus: %s", e)
            return {"qa_pairs": [], "error": str(e)}

    async def _codex_scrape_listing(self, asin: str, site: str) -> dict[str, Any]:
        """Fallback: use Codex CLI to scrape listing content."""
        url = f"https://{site}/dp/{asin}"
        schema = {
            "asin": "string",
            "site": "string",
            "title": "string",
            "bullet_points": ["string"],
            "description": "string",
            "a_plus_content": "string",
        }

        try:
            result = await self.codex.browse_and_extract(
                url=url,
                instruction=(
                    "Extract the product listing information: "
                    "product title, all bullet points (feature highlights), "
                    "product description, and A+ content text if present."
                ),
                response_schema=schema,
            )
            result.setdefault("asin", asin)
            result.setdefault("site", site)
            return result
        except CodexToolError as e:
            logger.error("Codex failed to scrape listing: %s", e)
            return {
                "asin": asin,
                "site": site,
                "title": "",
                "bullet_points": [],
                "description": "",
                "a_plus_content": "",
                "error": str(e),
            }

    async def _codex_scrape_reviews(self, asin: str, site: str) -> list[dict[str, Any]]:
        """Fallback: use Codex CLI to scrape reviews."""
        url = f"https://{site}/product-reviews/{asin}"
        try:
            result = await self.codex.browse_and_extract(
                url=url,
                instruction=(
                    "Extract customer reviews from this page. For each review, "
                    "get the title, body text, and star rating (as a number 1-5). "
                    "Return as JSON with key 'reviews' containing a list of objects "
                    "with 'title', 'body', and 'rating' fields. Get up to 20 reviews."
                ),
                response_schema={
                    "reviews": [{"title": "string", "body": "string", "rating": "number"}]
                },
            )
            return result.get("reviews", [])
        except CodexToolError as e:
            logger.error("Codex failed to scrape reviews: %s", e)
            return []

    async def close(self):
        """Clean up browser resources."""
        await self.scraper.close()
