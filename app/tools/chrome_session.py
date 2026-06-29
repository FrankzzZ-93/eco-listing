"""Logged-in Amazon scraping on a *real* Google Chrome — the free replacement
for the paid ``browser-act`` cloud browser.

Why real Chrome (and not bundled Chromium / browser-use):
  - Driven via Playwright with ``channel="chrome"``, so Amazon sees a genuine
    Chrome fingerprint. In a live spike this passed Amazon's bot defenses with
    zero captchas where bundled Chromium is detected.
  - A persistent ``user_data_dir`` remembers the Amazon login across runs — the
    same "remember login" guarantee browser-act gave, but local and free.

Two hard-won navigation facts (validated against live Amazon):
  1. ``page.goto`` is blocked on these pages (``ERR_BLOCKED_BY_RESPONSE``); an
     in-page ``location.href`` navigation (what a real click does) is allowed.
     So :func:`nav` is used everywhere instead of ``page.goto``.
  2. The sign-in pages block scripted form-fills. So login is performed
     *manually* by the user in the headed window (see :class:`LoginManager`);
     the backend only detects success and never touches the password.

Concurrency: a single process-wide :class:`ChromeSession` owns one persistent
context (one ``user_data_dir`` can only be opened once). Both the scraper and
the login manager share it; an ``asyncio.Lock`` serializes multi-step flows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Optional

from app.config import settings
from app.errors import CaptchaRequiredError, LoginRequiredError

logger = logging.getLogger(__name__)


# --- In-page JavaScript (ported verbatim from the browser-act scraper) ---

_JS_DETECT_CHALLENGE = """(() => {
  const q = (s) => document.querySelector(s);
  const captcha = !!q("form[action*='validateCaptcha'], input#captchacharacters, img[src*='captcha']");
  const signin = !!q("form[name='signIn'], #ap_email, #ap_password, #ap_email_login");
  const otp = !!q("#auth-mfa-otpcode, input[name='otpCode'], #auth-mfa-form");
  const title = document.title || '';
  const robot = /Robot Check|Sorry|verify|captcha/i.test(title);
  return JSON.stringify({captcha, signin, otp, robot, title});
})()"""

_JS_IS_LOGGED_IN = """(() => {
  const el = document.querySelector('#nav-link-accountList-nav-line-1, #nav-link-accountList');
  const txt = (el ? el.innerText : '') || '';
  const loggedIn = !!el && !/sign in|hello, sign in|登录/i.test(txt);
  return JSON.stringify({ loggedIn, txt });
})()"""

_JS_SCROLL_REVIEWS = """(() => {
  const el = document.querySelector(
    "#reviewsMedley, [data-hook='reviews-medley-footer'], #cm-cr-dp-review-list, #cm_cr-review_list, #reviews-medley-footer");
  if (el) { el.scrollIntoView({ block: 'center' }); return true; }
  window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.7));
  return false;
})()"""

_JS_EXTRACT_REVIEWS = """(() => {
  const out = [];
  const pick = (el, sels) => {
    for (const s of sels) {
      const e = el.querySelector(s);
      if (e && (e.innerText || '').trim()) return e.innerText.trim();
    }
    return '';
  };
  document.querySelectorAll("[data-hook='review']").forEach((el) => {
    let title = pick(el, ["[data-hook='review-title']", "[data-hook='reviewTitle']"]);
    title = title.replace(/^[0-9.]+ out of 5 stars/i, '').trim();
    const body = pick(el, [
      "[data-hook='review-body']", "[data-hook='reviewText']", "[data-hook='reviewTextContainer']",
    ]);
    const r = el.querySelector("[data-hook='review-star-rating'], [data-hook='cmps-review-star-rating']");
    let rating = 0;
    if (r) { const m = (r.innerText || '').match(/([0-9.]+)/); if (m) rating = parseFloat(m[1]); }
    out.push({ title: title, body: body, rating: rating });
  });
  return JSON.stringify(out);
})()"""

_JS_EXTRACT_ALEX = """(() => {
  const norm = (s) => (s || "").replace(/\\s+/g, " ").trim();
  const out = { questions: [] };
  let container = document.querySelector("#dpx-rex-nice-widget-container");
  if (!container) {
    const heads = Array.from(document.querySelectorAll("h2, h3, h4, label"));
    const h = heads.find((e) => /looking for specific info/i.test(norm(e.innerText)));
    if (h) {
      let c = h;
      for (let i = 0; i < 8 && c.parentElement; i++) { c = c.parentElement; if (c.id) break; }
      container = c;
    }
  }
  if (!container) return JSON.stringify(out);
  const seen = new Set();
  const push = (raw) => {
    const t = norm(raw);
    if (!t || t.length < 6 || t.length > 200) return;
    if (!/\\?/.test(t)) return;
    if (/^sponsored/i.test(t)) return;
    if (seen.has(t)) return;
    seen.add(t);
    out.questions.push(t);
  };
  container.querySelectorAll("li.dpx-rex-nile-inline-pill-carousel-element").forEach((li) => push(li.innerText));
  if (!out.questions.length) {
    container.querySelectorAll(".dpx-rex-nile-inline-pill-button, li, button, a[role='button']").forEach((el) => push(el.innerText));
  }
  return JSON.stringify(out);
})()"""

_JS_SCROLL_ALEX = (
    "(() => { const b = document.body || document.documentElement; if (!b) return;"
    " const e = document.querySelector('#dpx-rex-nice-widget-container');"
    " (e || b).scrollIntoView({block:'center'});"
    " window.scrollTo(0, (b.scrollHeight || 0) * 0.7); })()"
)

# Distinct (filterByStar, sortBy) review "views". Amazon has lately been
# ignoring these filters (serving the same ~8), so the sweep self-limits via the
# add==0 break — but we keep the list so we transparently benefit again if Amazon
# re-opens deep review access.
_REVIEW_VIEWS: tuple[tuple[str, str], ...] = (
    ("all_stars", "recent"),
    ("all_stars", "helpful"),
    ("five_star", "recent"),
    ("one_star", "recent"),
    ("four_star", "recent"),
    ("three_star", "recent"),
    ("two_star", "recent"),
)


def _jparse(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def _normalize_reviews(raw: list) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in raw or []:
        if isinstance(r, dict) and (r.get("body") or r.get("title")):
            out.append(
                {
                    "title": str(r.get("title", "")).strip(),
                    "body": str(r.get("body", "")).strip(),
                    "rating": float(r.get("rating") or 0) if r.get("rating") else 0,
                }
            )
    return out


def chrome_available() -> bool:
    """True when a real Google Chrome binary is present for ``channel='chrome'``.

    Covers macOS, Linux/WSL2 (``apt install google-chrome-stable``) and native
    Windows install locations.
    """
    for p in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/opt/google/chrome/chrome",
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ):
        if p and os.path.exists(p):
            return True
    return False


async def nav(page, url: str, *, timeout: int = 30000) -> None:
    """Navigate like a real user via in-page ``location.href``.

    ``page.goto`` is blocked by Amazon's edge on a real-Chrome session
    (ERR_BLOCKED_BY_RESPONSE); assigning ``location.href`` performs a genuine
    in-page navigation that is allowed. The assignment destroys the JS execution
    context (that *is* the navigation firing), so the evaluate is expected to
    raise — we swallow it and wait for the new document.
    """
    try:
        await page.evaluate("window.location.href=" + json.dumps(url))
    except Exception:
        pass  # navigation destroys the execution context — expected
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass
    await page.wait_for_timeout(1800)


class ChromeSession:
    """Process-wide singleton owning one persistent real-Chrome context."""

    _instance: Optional["ChromeSession"] = None

    def __init__(self) -> None:
        self._pw = None
        self._ctx = None
        self._browser = None       # set in connect mode (externally-run Chrome)
        self._connected = False
        self.lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> "ChromeSession":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _headless() -> bool:
        # Real Chrome runs HEADED by default: manual login needs a visible window
        # and headed real Chrome is the most bot-resistant (the spike passed
        # Amazon's defenses headed). Only go headless if the operator explicitly
        # opts in via the `chrome_headless` scrape setting (anti-scraping risk;
        # also needs a display in WSL2/server deployments).
        try:
            from app import app_settings

            return bool(app_settings.get_scrape_param("chrome_headless", False))
        except Exception:
            return False

    @staticmethod
    def _cdp_url() -> str:
        """CDP endpoint of an externally-run Chrome, or '' to launch locally."""
        url = ""
        try:
            from app import app_settings

            url = app_settings.get_scrape_param("chrome_cdp_url", "") or ""
        except Exception:
            url = ""
        return (url or settings.chrome_cdp_url or "").strip()

    async def _ensure(self):
        if self._ctx is not None:
            return self._ctx
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        cdp_url = self._cdp_url()
        if cdp_url:
            # CONNECT mode: drive an externally-run real Chrome (e.g. on the
            # Windows host, where the user logged in). page.goto is blocked on a
            # connected session — the engine already navigates via location.href
            # (:func:`nav`), so this works transparently.
            self._browser = await self._pw.chromium.connect_over_cdp(cdp_url)
            self._connected = True
            self._ctx = (
                self._browser.contexts[0]
                if self._browser.contexts
                else await self._browser.new_context()
            )
            logger.info("chrome_session: connected to real Chrome over CDP (%s)", cdp_url)
        else:
            # LAUNCH mode: start a persistent real Chrome locally.
            profile = settings.chrome_profile_dir
            os.makedirs(profile, exist_ok=True)
            launch_args = ["--disable-blink-features=AutomationControlled", "--no-first-run"]
            if sys.platform.startswith("linux"):
                # WSL2 / Linux: the Chrome sandbox commonly can't initialize
                # (user namespaces, small /dev/shm) so headed Chrome fails to
                # launch without these. macOS / Windows keep their sandbox.
                launch_args += ["--no-sandbox", "--disable-dev-shm-usage"]
            self._ctx = await self._pw.chromium.launch_persistent_context(
                user_data_dir=profile,
                channel="chrome",
                headless=self._headless(),
                args=launch_args,
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1440, "height": 1000},
            )
            logger.info(
                "chrome_session: launched real Chrome (profile=%s, platform=%s)",
                profile, sys.platform,
            )
        await self._ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        return self._ctx

    async def page(self):
        """Return the working page in the shared context (reusing an open one)."""
        ctx = await self._ensure()
        for pg in ctx.pages:
            if "amazon." in (pg.url or ""):
                return pg
        return ctx.pages[0] if ctx.pages else await ctx.new_page()

    async def close(self) -> None:
        try:
            # In connect mode the Chrome is externally owned — never close it;
            # stopping the Playwright driver below just disconnects.
            if not self._connected and self._ctx is not None:
                await self._ctx.close()
        except Exception:
            logger.debug("chrome_session ctx close failed", exc_info=True)
        try:
            if self._pw is not None:
                await self._pw.stop()
        except Exception:
            logger.debug("chrome_session pw stop failed", exc_info=True)
        self._ctx = None
        self._pw = None
        self._browser = None
        self._connected = False


async def _screenshot(page, path: str, *, selector: Optional[str] = None) -> Optional[str]:
    """Best-effort screenshot: the element if ``selector`` is given and shootable,
    otherwise the viewport. An element-screenshot failure (hidden / 0-size /
    detached) falls back to a viewport shot rather than yielding no file."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    except Exception:
        return None
    if selector:
        try:
            el = await page.query_selector(selector)
            if el:
                await el.screenshot(path=path)
                return path
        except Exception:
            logger.debug("element screenshot failed, falling back to viewport: %s", path)
    try:
        await page.screenshot(path=path)
        return path
    except Exception:
        logger.debug("screenshot failed: %s", path, exc_info=True)
        return None


async def _load_below_fold(page) -> None:
    """Scroll down in steps so Amazon lazy-renders the reviews medley + Rufus.

    The dp page only renders the reviews/Rufus widgets once they scroll into
    view; a single jump isn't enough, so step down the page with short waits.
    """
    try:
        for frac in (0.3, 0.5, 0.7, 0.85, 1.0):
            await page.evaluate(
                "window.scrollTo(0, Math.floor((document.body?document.body.scrollHeight:0)*%s))" % frac
            )
            await page.wait_for_timeout(900)
        await page.evaluate("window.scrollTo(0, Math.floor((document.body?document.body.scrollHeight:0)*0.6))")
        await page.wait_for_timeout(600)
    except Exception:
        pass


async def _raise_if_blocking(page, *, screenshot_dir: Optional[str], tag: str,
                             subject: str, include_signin: bool = True) -> None:
    info = _jparse(await page.evaluate(_JS_DETECT_CHALLENGE)) or {}
    blocking = bool(info.get("captcha") or info.get("robot") or info.get("otp")
                    or (include_signin and info.get("signin")))
    if not blocking:
        return
    kind = ("登录验证" if info.get("signin") else "二次验证 (OTP)" if info.get("otp")
            else "验证码")
    image_path = ""
    if screenshot_dir:
        image_path = await _screenshot(
            page, os.path.join(screenshot_dir, f"{tag}.png")
        ) or ""
    raise CaptchaRequiredError(
        f"{subject}遇到{kind}，请在已打开的 Chrome 窗口中完成验证后重试",
        image_path=image_path,
        context="scrape",
    )


class ReviewScraper:
    """Scrapes logged-in Amazon reviews + Rufus ("Alex") questions via real Chrome."""

    def __init__(self, **_ignored) -> None:
        # **_ignored keeps the old browser-act constructor kwargs (headed/
        # proxy_region/...) call-compatible during the migration.
        self._session = ChromeSession.instance()

    @staticmethod
    def available() -> bool:
        return chrome_available()

    async def get_reviews(
        self,
        asin: str,
        site: str,
        max_pages: int = 3,
        *,
        target_count: int = 20,
        screenshot_dir: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if not self.available():
            raise LoginRequiredError("未找到本机 Google Chrome，无法使用真实浏览器抓取")

        reviews: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add(items: list) -> int:
            added = 0
            for r in _normalize_reviews(items):
                key = (r["title"] + "\n" + r["body"]).strip()
                if key and key not in seen:
                    seen.add(key)
                    reviews.append(r)
                    added += 1
            return added

        async with self._session.lock:
            page = await self._session.page()

            # 1) Public "top reviews" on the dp page (most reviews live here now).
            await nav(page, f"https://{site}/dp/{asin}")
            await _raise_if_blocking(
                page, screenshot_dir=screenshot_dir, tag=f"verify_{asin}_dp",
                subject=f"抓取 {asin} 评论时", include_signin=False,
            )
            await _load_below_fold(page)
            try:
                await page.evaluate(_JS_SCROLL_REVIEWS)
                await page.wait_for_selector("[data-hook='review']", timeout=8000)
            except Exception:
                pass
            _add(_jparse(await page.evaluate(_JS_EXTRACT_REVIEWS)) or [])
            if screenshot_dir:
                await _screenshot(
                    page, os.path.join(screenshot_dir, f"reviews_{asin}_dp.png"),
                    selector="#reviewsMedley, #cm-cr-dp-review-list, #reviews-medley-footer",
                )

            # 2) /product-reviews/ view sweep (only useful while logged in).
            logged_in = bool(
                (_jparse(await page.evaluate(_JS_IS_LOGGED_IN)) or {}).get("loggedIn")
            )
            if logged_in and len(reviews) < target_count:
                base = f"https://{site}/product-reviews/{asin}"
                for star, sort in _REVIEW_VIEWS:
                    if len(reviews) >= target_count:
                        break
                    for page_num in range(1, max_pages + 1):
                        if len(reviews) >= target_count:
                            break
                        await nav(
                            page,
                            f"{base}?reviewerType=all_reviews&filterByStar={star}"
                            f"&sortBy={sort}&pageNumber={page_num}",
                        )
                        info = _jparse(await page.evaluate(_JS_DETECT_CHALLENGE)) or {}
                        if info.get("captcha") or info.get("robot") or info.get("signin"):
                            await _raise_if_blocking(
                                page, screenshot_dir=screenshot_dir,
                                tag=f"verify_{asin}_{star}_{sort}_p{page_num}",
                                subject=f"抓取 {asin} 评论时",
                            )
                            break
                        added = _add(_jparse(await page.evaluate(_JS_EXTRACT_REVIEWS)) or [])
                        if added and screenshot_dir:
                            await _screenshot(
                                page,
                                os.path.join(screenshot_dir, f"reviews_{asin}_{star}_{sort}_p{page_num}.png"),
                            )
                        # Amazon re-serves the same set for higher pages / ignored
                        # filters; once a view adds nothing new, move on.
                        if added == 0:
                            break

        logger.info("chrome_session scraped %d reviews for %s/%s", len(reviews), site, asin)
        return reviews

    async def get_alex(
        self,
        asin: str,
        site: str,
        *,
        screenshot_dir: Optional[str] = None,
    ) -> dict[str, Any]:
        if not self.available():
            raise LoginRequiredError("未找到本机 Google Chrome，无法使用真实浏览器抓取")

        async with self._session.lock:
            page = await self._session.page()
            await nav(page, f"https://{site}/dp/{asin}")
            try:
                await page.wait_for_selector("body", timeout=5000)
            except Exception:
                pass
            # The Rufus widget lazy-renders only when scrolled into view; jumping
            # to the bottom skips it. Step down gradually and stop as soon as it
            # appears. Each step is guarded: a transient page state (e.g. body
            # briefly null mid-navigation) must not abort the whole Alex step —
            # otherwise we'd skip the evidence screenshot entirely.
            for frac in (0.25, 0.4, 0.55, 0.7, 0.85, 1.0):
                try:
                    await page.evaluate(
                        "window.scrollTo(0, Math.floor((document.body?document.body.scrollHeight:0)*%s))" % frac
                    )
                    await page.wait_for_timeout(1100)
                    if await page.query_selector("#dpx-rex-nice-widget-container"):
                        break
                except Exception:
                    break
            try:
                await page.evaluate(_JS_SCROLL_ALEX)
                await page.wait_for_timeout(1200)
            except Exception:
                pass
            await _raise_if_blocking(
                page, screenshot_dir=screenshot_dir, tag=f"verify_alex_{asin}",
                subject=f"抓取 {asin} 的 Rufus 问题时", include_signin=False,
            )
            raw = await page.evaluate(_JS_EXTRACT_ALEX)
            if screenshot_dir:
                shot = await _screenshot(
                    page, os.path.join(screenshot_dir, f"alex_{asin}.png"),
                    selector="#dpx-rex-nice-widget-container",
                )
            else:
                shot = None

        data = _jparse(raw)
        qs = data.get("questions") if isinstance(data, dict) else None
        questions = [q for q in qs if isinstance(q, str)] if isinstance(qs, list) else []
        logger.info("chrome_session scraped %d Rufus questions for %s/%s", len(questions), site, asin)
        result: dict[str, Any] = {"questions": questions}
        if shot:
            result["screenshot"] = shot
        return result

    async def submit_verification(self, answer: str) -> bool:
        # Manual flow: the user completes any verification directly in the headed
        # Chrome window, so there is nothing to type back. Report current state.
        async with self._session.lock:
            page = await self._session.page()
            info = _jparse(await page.evaluate(_JS_DETECT_CHALLENGE)) or {}
        return not (info.get("captcha") or info.get("robot") or info.get("otp"))

    async def close(self) -> None:
        await self._session.close()


class LoginManager:
    """Establishes / probes the Amazon session. Login is *manual* (the user signs
    in inside the headed real-Chrome window); we never handle credentials."""

    def __init__(self, **_ignored) -> None:
        self._session = ChromeSession.instance()

    @staticmethod
    def available() -> bool:
        return chrome_available()

    async def is_logged_in(self, site: str = "amazon.com", *, launch: bool = True) -> bool:
        if not self.available():
            return False
        async with self._session.lock:
            try:
                # Don't launch a browser merely to probe (e.g. the settings-page
                # status poll on page load): only check a session that's already
                # open. Connect mode (external Chrome) is fine to attach to.
                if not launch and self._session._ctx is None and not self._session._cdp_url():
                    return False
                page = await self._session.page()
                if "amazon." not in (page.url or ""):
                    await nav(page, f"https://{site}/")
                raw = await page.evaluate(_JS_IS_LOGGED_IN)
            except Exception:
                logger.warning("is_logged_in probe failed", exc_info=True)
                return False
        return bool((_jparse(raw) or {}).get("loggedIn"))

    async def open_for_login(self, site: str = "amazon.com") -> None:
        """Open (headed) the Amazon homepage so the user can sign in manually."""
        if not self.available():
            raise LoginRequiredError("未找到本机 Google Chrome，无法打开登录窗口")
        async with self._session.lock:
            page = await self._session.page()
            await nav(page, f"https://{site}/")

    async def close(self) -> None:
        await self._session.close()
