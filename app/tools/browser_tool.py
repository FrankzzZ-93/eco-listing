"""Dual-layer browser tool: Playwright (fast/cheap) with Codex CLI fallback (smart/resilient).

Reviews can additionally be scraped via the logged-in ``browser-act`` engine
(see :class:`~app.tools.browser_act_scraper.BrowserActScraper`), selected by the
``review_engine`` setting in :mod:`app.app_settings`. The browser-act scraper is
shared as ``self.browser_act`` so the captcha-submit endpoint can drive the same
live session that a paused run left parked on a verification page.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from app.config import settings
from app.errors import CaptchaRequiredError, LoginRequiredError
from app.tools.playwright_scraper import PlaywrightScraper, AntiScrapingError
from app.tools.codex_tool import CodexTool, CodexToolError

logger = logging.getLogger(__name__)


class BrowserTool:
    """Unified browser interface for the Research Agent.

    Strategy:
      Layer 0 — browser-act: logged-in, session-persistent review scraping
               (primary for reviews when configured). Surfaces captchas.
      Layer 1 — Playwright: fast, precise, low-cost structured scraping.
      Layer 2 — Codex CLI: LLM-driven browser for anti-scraping fallback
               and complex interactions (Alex Q&A expansion, dynamic content).
    """

    def __init__(self):
        self.scraper = PlaywrightScraper()
        self.codex = CodexTool()
        # Lazily constructed shared browser-act review scraper. Kept as a single
        # instance so a parked captcha session can be resumed by the API layer.
        self._browser_act: Optional[Any] = None

    @property
    def browser_act(self):
        """Shared ReviewScraper instance (constructed on first access)."""
        if self._browser_act is None:
            from app.tools.browser_act_scraper import ReviewScraper
            from app import app_settings

            headed = not app_settings.get_scrape_param("browser_headless", True)
            proxy_region = app_settings.get_account().get("proxy_region", "")
            self._browser_act = ReviewScraper(headed=headed, proxy_region=proxy_region)
        return self._browser_act

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
        self,
        asin: str,
        site: str,
        max_pages: int = 3,
        run_id: str | None = None,
        target_count: int = 20,
    ) -> list[dict[str, Any]]:
        """Get customer reviews.

        When the ``review_engine`` setting is ``browser_act`` and browser-act is
        available, scrape from the logged-in browser-act session first. A
        ``CaptchaRequiredError`` from that engine is deliberately NOT caught —
        it propagates to the research node so the run pauses and the web UI can
        pop a captcha modal. Other failures fall back to Playwright -> Codex.
        """
        engine = self._review_engine()
        if engine == "browser_act":
            scraper = self.browser_act
            if scraper.available():
                screenshot_dir = (
                    os.path.join(settings.artifacts_dir, run_id) if run_id else None
                )
                try:
                    reviews = await scraper.get_reviews(
                        asin,
                        site,
                        max_pages=max_pages,
                        target_count=target_count,
                        screenshot_dir=screenshot_dir,
                    )
                    if reviews:
                        logger.info(
                            "Reviews scraped via browser-act: %s/%s (%d reviews)",
                            site, asin, len(reviews),
                        )
                        return reviews
                    logger.warning(
                        "browser-act returned 0 reviews for %s/%s, falling back",
                        site, asin,
                    )
                except CaptchaRequiredError:
                    # Surface to the caller (research node) — do not retry/fallback.
                    raise
                except LoginRequiredError as e:
                    logger.warning("browser-act login required (%s), falling back", e)
                except Exception as e:
                    logger.warning("browser-act review scrape error (%s), falling back", e)

        try:
            reviews = await self.scraper.get_reviews(asin, site, max_pages=max_pages)
            if reviews:
                logger.warning("Reviews scraped via Playwright: %s/%s (%d reviews)", site, asin, len(reviews))
                return reviews
            logger.warning(
                "Playwright returned 0 reviews for %s/%s (page loaded but no review elements), "
                "falling back to Codex",
                site, asin,
            )
            return await self._codex_scrape_reviews(asin, site)
        except AntiScrapingError as e:
            logger.warning("Playwright blocked for reviews (%s), falling back to Codex", e)
            return await self._codex_scrape_reviews(asin, site)
        except Exception as e:
            logger.warning("Playwright error for reviews (%s), falling back to Codex", e)
            return await self._codex_scrape_reviews(asin, site)

    async def scrape_alex(
        self, asin: str, site: str, run_id: str | None = None
    ) -> dict[str, Any]:
        """Get Alex (Rufus "Looking for specific info?") suggested questions.

        "Alex" is this project's name for Amazon's Rufus AI shopping assistant.
        Returns ``{"questions": [str, ...]}`` — the AI-suggested shopper
        questions the listing pipeline optimizes against.

        When ``review_engine`` is ``browser_act`` and available, read it from the
        browser-act session first (fast, no LLM). A ``CaptchaRequiredError``
        propagates so the run can pause; other failures or an empty result fall
        back to the Codex CLI engine.
        """
        if self._review_engine() == "browser_act":
            scraper = self.browser_act
            if scraper.available():
                screenshot_dir = (
                    os.path.join(settings.artifacts_dir, run_id) if run_id else None
                )
                try:
                    result = await scraper.get_alex(
                        asin, site, screenshot_dir=screenshot_dir
                    )
                    if result.get("questions"):
                        logger.info(
                            "Rufus questions scraped via browser-act: %s/%s (%d)",
                            site, asin, len(result["questions"]),
                        )
                        return result
                    logger.warning(
                        "browser-act returned 0 Rufus questions for %s/%s, falling back to Codex",
                        site, asin,
                    )
                except CaptchaRequiredError:
                    raise
                except LoginRequiredError as e:
                    logger.warning("browser-act login required for Alex (%s), falling back", e)
                except Exception as e:
                    logger.warning("browser-act Alex scrape error (%s), falling back", e)

        return await self._codex_scrape_alex(asin, site)

    async def _codex_scrape_alex(self, asin: str, site: str) -> dict[str, Any]:
        """Fallback: use Codex CLI to scrape Rufus suggested questions."""
        logger.info("Scraping Rufus questions via Codex CLI: %s/%s", site, asin)
        url = f"https://{site}/dp/{asin}"

        try:
            result = await self.codex.interact_and_extract(
                url=url,
                steps=[
                    "Scroll down the product page to the 'Alexa AI — Looking for "
                    "specific info?' (Rufus) widget, which sits near the reviews",
                    "Wait for the AI-suggested question pills/chips to fully load",
                ],
                extract_instruction=(
                    "Extract every AI-suggested shopper question shown in the Rufus "
                    "'Looking for specific info?' widget (the clickable question "
                    "pills). Ignore any sponsored items. Return JSON with key "
                    "'questions' containing a flat list of the question strings."
                ),
            )
            qs = result.get("questions") if isinstance(result, dict) else None
            questions = [q for q in qs if isinstance(q, str)] if isinstance(qs, list) else []
            return {"questions": questions}
        except CodexToolError as e:
            logger.error("Codex failed to scrape Rufus questions: %s", e)
            return {"questions": [], "error": str(e)}

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

        instruction = (
            "Extract customer reviews for this Amazon product. "
            "IMPORTANT: Amazon often blocks direct access to review pages and requires sign-in. "
            "If the direct page at {url} is blocked or requires sign-in, use web search "
            "to find reviews for this product (search for the ASIN or product name + 'reviews'). "
            "You can also try using curl with a browser User-Agent header to fetch the page. "
            "For each review, get the title, body text, and star rating (as a number 1-5). "
            "Return as JSON with key 'reviews' containing a list of objects "
            "with 'title', 'body', and 'rating' fields. Get up to 20 reviews."
        ).format(url=url)

        schema = {"reviews": [{"title": "string", "body": "string", "rating": "number"}]}

        for attempt in range(2):
            try:
                result = await self.codex.browse_and_extract(
                    url=url,
                    instruction=instruction,
                    response_schema=schema,
                )
                reviews = result.get("reviews", [])
                logger.warning(
                    "Codex review attempt %d for %s: got %d reviews, keys=%s",
                    attempt + 1, asin, len(reviews), list(result.keys()),
                )
                if reviews:
                    return reviews
                if attempt == 0:
                    logger.warning(
                        "Codex returned 0 reviews for %s (attempt 1), raw: %s — retrying with search-first strategy",
                        asin, str(result)[:500],
                    )
                    instruction = (
                        f"Find customer reviews for Amazon product ASIN {asin} on {site}. "
                        "Do NOT try to open the Amazon review page directly — it will require sign-in. "
                        f"Instead, use web search to find reviews (search for '{asin} amazon customer reviews'). "
                        "Extract at least 10 reviews with title, body text, and star rating (1-5). "
                        "Return JSON with key 'reviews' containing a list of objects "
                        "with 'title', 'body', and 'rating' fields."
                    )
            except CodexToolError as e:
                logger.error("Codex failed to scrape reviews (attempt %d): %s", attempt + 1, e)
                if attempt == 0:
                    continue
                return []

        logger.warning("All Codex review attempts returned 0 for %s", asin)
        return []

    @staticmethod
    def _review_engine() -> str:
        try:
            from app import app_settings

            return app_settings.get_review_engine()
        except Exception:
            return "builtin"

    async def close(self):
        """Clean up browser resources."""
        await self.scraper.close()
        if self._browser_act is not None:
            try:
                await self._browser_act.close()
            except Exception:
                logger.debug("browser-act close failed", exc_info=True)
