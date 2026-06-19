"""Logged-in Amazon scraping / login on top of the ``browser-act`` CLI.

Responsibilities are split to follow SRP/ISP — each class has one reason to
change and each consumer depends only on the surface it uses:

- :class:`VerificationHandler` — human-verification (captcha / sign-in / OTP):
  detect, screenshot, raise, and resolve. Shared by both flows below.
- :class:`ReviewScraper` — extract competitor reviews from the logged-in
  account (used by the research pipeline via ``BrowserTool``).
- :class:`LoginManager` — establish / probe the authenticated session (used by
  the account-session manager behind the config UI).

All three drive a persistent ``browser-act`` browser, so the Amazon login
session is remembered across runs. When verification is required they do NOT
retry blindly: they screenshot the challenge, leave the session parked on that
page, and raise :class:`CaptchaRequiredError`; the user's answer is later typed
back into the same live page via ``submit_verification``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from app.errors import CaptchaRequiredError, LoginRequiredError
from app.tools.browser_act import BrowserActClient, browser_act_available

logger = logging.getLogger(__name__)


# --- In-page JavaScript snippets (returned as JSON strings for safe transport) ---

_JS_DETECT_CHALLENGE = """(() => {
  const q = (s) => document.querySelector(s);
  const captcha = !!q("form[action*='validateCaptcha'], input#captchacharacters, img[src*='captcha']");
  const signin = !!q("form[name='signIn'], #ap_email, #ap_password, #ap_email_login");
  const otp = !!q("#auth-mfa-otpcode, input[name='otpCode'], #auth-mfa-form");
  const title = document.title || '';
  const robot = /Robot Check|Sorry|verify|captcha/i.test(title);
  return JSON.stringify({captcha, signin, otp, robot, title});
})()"""

# Distinct (filterByStar, sortBy) "views" of the reviews page. Each surfaces a
# largely different slice, so sweeping them and de-duplicating accumulates far
# more reviews than pagination alone (which Amazon frequently ignores). Ordered
# so the broad/most-useful views come first and per-star filters fill the rest.
_REVIEW_VIEWS: tuple[tuple[str, str], ...] = (
    ("all_stars", "recent"),
    ("all_stars", "helpful"),
    ("five_star", "recent"),
    ("one_star", "recent"),
    ("four_star", "recent"),
    ("three_star", "recent"),
    ("two_star", "recent"),
    ("positive", "helpful"),
    ("critical", "helpful"),
)

# Two Amazon surfaces expose reviews with different data-hooks: the dedicated
# /product-reviews/ page uses kebab-case (review-title / review-body), while the
# public product (dp) page uses camelCase (reviewTitle / reviewText). Try both.
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

# Scroll the reviews section into view so the dp page lazily renders its public
# "Top reviews" list before we extract.
_JS_SCROLL_REVIEWS = """(() => {
  const el = document.querySelector(
    "#reviewsMedley, [data-hook='reviews-medley-footer'], #cm-cr-dp-review-list, #cm_cr-review_list, #reviews-medley-footer");
  if (el) { el.scrollIntoView({ block: 'center' }); return true; }
  window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.7));
  return false;
})()"""

_JS_IS_LOGGED_IN = """(() => {
  const el = document.querySelector('#nav-link-accountList-nav-line-1, #nav-link-accountList');
  const txt = (el ? el.innerText : '') || '';
  const loggedIn = !!el && !/sign in|hello, sign in|登录/i.test(txt);
  return JSON.stringify({ loggedIn, txt });
})()"""

# The bare /ap/signin URL is a 404 ("not a functioning page"); the real sign-in
# entry is the account nav link, which carries the OpenID params. Read its href
# and navigate there.
_JS_SIGNIN_HREF = """(() => {
  const sel = ['#nav-link-accountList', '#nav-signin-tooltip a.nav-action-button',
    'a[data-nav-role="signin"]', 'a.nav-action-signin-button', 'a[href*="/ap/signin"]'];
  for (const s of sel) { const a = document.querySelector(s); if (a && a.href) return a.href; }
  return '';
})()"""

# Amazon's sign-in is a two-step form with stable ids. Click via the DOM so we
# hit the right control regardless of the indexed-state ordering.
_JS_CLICK_CONTINUE = """(() => {
  const el = document.querySelector('#continue input[type=submit], #continue, #auth-continue-button');
  if (el) { el.click(); return true; }
  return false;
})()"""

_JS_CLICK_SIGNIN = """(() => {
  const el = document.querySelector('#signInSubmit, #auth-signin-button');
  if (el) { el.click(); return true; }
  return false;
})()"""

# Extracts the inline Rufus ("Alexa AI — Looking for specific info?") widget on a
# product page. The widget surfaces AI-suggested shopper questions as carousel
# pills; those questions are what the listing-optimization pipeline consumes
# (``alex_questions``). We scope to the widget container so sponsored / returns /
# unrelated "?" copy elsewhere on the page is naturally excluded.
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
    if (!/\\?/.test(t)) return;          // questions only
    if (/^sponsored/i.test(t)) return;   // drop ad-injected pills
    if (seen.has(t)) return;
    seen.add(t);
    out.questions.push(t);
  };

  // Default suggested-question pills.
  container
    .querySelectorAll("li.dpx-rex-nile-inline-pill-carousel-element")
    .forEach((li) => push(li.innerText));
  // Fallbacks if Amazon tweaks the pill markup.
  if (!out.questions.length) {
    container
      .querySelectorAll(".dpx-rex-nile-inline-pill-button, li, button, a[role='button']")
      .forEach((el) => push(el.innerText));
  }
  return JSON.stringify(out);
})()"""


def _parse_json_result(value: Any) -> Any:
    """browser-act ``eval`` may return our JSON string verbatim or pre-parsed."""
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


# --- Human verification (captcha / sign-in / OTP) ---


@dataclass
class ChallengeInfo:
    """A single source of truth for what counts as a blocking challenge."""

    captcha: bool = False
    signin: bool = False
    otp: bool = False
    robot: bool = False
    title: str = ""

    @classmethod
    def from_raw(cls, raw: Any) -> "ChallengeInfo":
        d = _parse_json_result(raw) or {}
        return cls(
            captcha=bool(d.get("captcha")),
            signin=bool(d.get("signin")),
            otp=bool(d.get("otp")),
            robot=bool(d.get("robot")),
            title=str(d.get("title") or ""),
        )

    def blocking(self, *, include_signin: bool = True) -> bool:
        return self.captcha or self.robot or self.otp or (include_signin and self.signin)

    @property
    def kind(self) -> str:
        if self.signin:
            return "登录验证"
        if self.captcha or self.robot:
            return "验证码"
        if self.otp:
            return "二次验证 (OTP)"
        return "人机验证"


class VerificationHandler:
    """Owns the human-verification concern on a browser-act session.

    Lock-agnostic on purpose: callers that run multi-step sequences hold the
    session lock; the underlying client already serializes individual commands.
    """

    def __init__(self, client: BrowserActClient) -> None:
        self._client = client

    async def detect(self) -> ChallengeInfo:
        try:
            raw = await self._client.eval_js(_JS_DETECT_CHALLENGE)
        except Exception:
            logger.warning("challenge detection failed", exc_info=True)
            return ChallengeInfo()
        return ChallengeInfo.from_raw(raw)

    async def screenshot(self, path: str) -> str:
        """Screenshot the current page; returns the path (or '' on failure)."""
        try:
            await self._client.screenshot(path, full=False)
            return path
        except Exception:
            logger.warning("verification screenshot failed", exc_info=True)
            return ""

    async def raise_if_blocking(
        self,
        *,
        context: str,
        screenshot_dir: Optional[str],
        tag: str,
        include_signin: bool = True,
        subject: str = "",
        message: Optional[str] = None,
    ) -> None:
        """Raise :class:`CaptchaRequiredError` when the page is parked on a
        blocking challenge, after capturing a screenshot for the UI."""
        info = await self.detect()
        if not info.blocking(include_signin=include_signin):
            return
        image_path = ""
        if screenshot_dir:
            os.makedirs(screenshot_dir, exist_ok=True)
            image_path = await self.screenshot(os.path.join(screenshot_dir, f"{tag}.png"))
        raise CaptchaRequiredError(
            message or f"{subject}遇到{info.kind}，请在弹窗中完成验证后继续",
            image_path=image_path,
            context=context,
        )

    async def submit(self, answer: str) -> bool:
        """Type ``answer`` into the parked challenge page and submit.

        Returns True when the page no longer looks like a challenge afterward.
        """
        elements = await self._client.state()
        target = _first_input(elements)
        if target is not None and answer:
            await self._client.input(target, answer)
        submit_idx = _find_submit(elements)
        if submit_idx is not None:
            await self._client.click(submit_idx)
        else:
            await self._client.keys("Enter")
        await self._client.wait_stable()
        cleared = not (await self.detect()).blocking()
        logger.info("verification submit cleared=%s", cleared)
        return cleared


def _normalize_reviews(raw_reviews: list) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in raw_reviews:
        if isinstance(r, dict) and (r.get("body") or r.get("title")):
            out.append(
                {
                    "title": str(r.get("title", "")).strip(),
                    "body": str(r.get("body", "")).strip(),
                    "rating": float(r.get("rating") or 0) if r.get("rating") else 0,
                }
            )
    return out


def _dedupe_reviews(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in reviews:
        key = (r.get("title", "") + "\n" + r.get("body", "")).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(r)
    return out


# --- Review scraping ---


class ReviewScraper:
    """Scrapes logged-in Amazon reviews via browser-act. SRP: review extraction."""

    def __init__(
        self,
        *,
        browser_name: str = "eco_listing",
        session_name: str = "eco_listing",
        proxy_region: str = "",
        headed: bool = False,
    ) -> None:
        self.client = BrowserActClient(
            browser_name=browser_name,
            session_name=session_name,
            dynamic_proxy=proxy_region,
            headed=headed,
        )
        self._verifier = VerificationHandler(self.client)
        # A single session is one window; serialize multi-command operations.
        self._lock = asyncio.Lock()

    @staticmethod
    def available() -> bool:
        return browser_act_available()

    async def get_reviews(
        self,
        asin: str,
        site: str,
        max_pages: int = 3,
        *,
        target_count: int = 20,
        screenshot_dir: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Scrape reviews for ``asin``, aiming for at least ``target_count``.

        Amazon caps the public dp page at ~8 "top reviews" and frequently ignores
        the ``pageNumber`` parameter on /product-reviews/, so simple pagination
        yields very few. To gather more we sweep several *views* — different
        star-rating filters and sort orders — and accumulate de-duplicated
        reviews until we hit ``target_count`` or run out of views. Each view
        surfaces a largely distinct slice, so the union easily exceeds 20.

        Raises :class:`CaptchaRequiredError` on a verification challenge (session
        left parked on the page) and :class:`LoginRequiredError` if browser-act
        is unavailable.
        """
        if not self.available():
            raise LoginRequiredError("browser-act 未安装，无法使用登录态抓取")

        reviews: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add(items: list[dict[str, Any]]) -> int:
            added = 0
            for r in _normalize_reviews(items):
                key = (r["title"] + "\n" + r["body"]).strip()
                if key and key not in seen:
                    seen.add(key)
                    reviews.append(r)
                    added += 1
            return added

        async with self._lock:
            # 1) Public "Top reviews" on the product (dp) page need no login.
            res = await self.client.open(f"https://{site}/dp/{asin}")
            if not res.ok:
                logger.warning("browser-act open failed: %s", res.stderr or res.stdout)
            await self.client.wait_stable()
            # A captcha / robot-check still blocks; a sign-in form won't appear on
            # the public dp page, so don't treat one as blocking here.
            await self._verifier.raise_if_blocking(
                context="scrape",
                screenshot_dir=screenshot_dir,
                tag=f"verify_{asin}_dp",
                subject=f"抓取 {asin} 评论时",
                include_signin=False,
            )
            try:
                await self.client.eval_js(_JS_SCROLL_REVIEWS)
                await self.client.wait_stable()
            except Exception:
                logger.debug("scroll-to-reviews failed", exc_info=True)
            _add(_parse_json_result(await self.client.eval_js(_JS_EXTRACT_REVIEWS)) or [])

            # 2) The dedicated /product-reviews/ page is login-walled; only sweep
            #    it when authenticated to avoid bouncing into the sign-in wall.
            logged_in = bool(
                (_parse_json_result(await self.client.eval_js(_JS_IS_LOGGED_IN)) or {}).get(
                    "loggedIn"
                )
            )
            if logged_in and len(reviews) < target_count:
                base_url = f"https://{site}/product-reviews/{asin}"
                for star, sort in _REVIEW_VIEWS:
                    if len(reviews) >= target_count:
                        break
                    for page_num in range(1, max_pages + 1):
                        if len(reviews) >= target_count:
                            break
                        url = (
                            f"{base_url}?reviewerType=all_reviews"
                            f"&filterByStar={star}&sortBy={sort}&pageNumber={page_num}"
                        )
                        if not await self._goto(url):
                            # net error / proxy drop — skip the rest of this view.
                            break
                        await self._verifier.raise_if_blocking(
                            context="scrape",
                            screenshot_dir=screenshot_dir,
                            tag=f"verify_{asin}_{star}_{sort}_p{page_num}",
                            subject=f"抓取 {asin} 评论时",
                        )
                        page_reviews = _parse_json_result(
                            await self.client.eval_js(_JS_EXTRACT_REVIEWS)
                        )
                        if not isinstance(page_reviews, list) or not page_reviews:
                            break
                        # Amazon often re-serves page 1 for higher pageNumbers; once
                        # a page adds nothing new, further pages of this view won't.
                        if _add(page_reviews) == 0:
                            break

        reviews = _dedupe_reviews(reviews)
        logger.info(
            "browser-act scraped %d reviews for %s/%s (target %d)",
            len(reviews), site, asin, target_count,
        )
        return reviews

    async def _goto(self, url: str, *, retries: int = 2) -> bool:
        """Navigate and confirm the page actually loaded (not a chrome-error).

        A dropped dynamic proxy or transient block lands the tab on
        ``chrome-error://`` while still reporting ``ok``; detect that and retry a
        couple of times before giving up on the view.
        """
        for attempt in range(retries + 1):
            res = await self.client.navigate(url)
            if not res.ok:
                logger.warning("browser-act navigate failed: %s", res.stderr or res.stdout)
            await self.client.wait_stable()
            try:
                href = await self.client.eval_js("location.href")
            except Exception:
                href = ""
            href = href if isinstance(href, str) else ""
            if "chrome-error" not in href:
                return True
            logger.warning("navigation landed on error page (attempt %d): %s", attempt + 1, url)
            await asyncio.sleep(2.5)
        return False

    async def get_alex(
        self,
        asin: str,
        site: str,
        *,
        screenshot_dir: Optional[str] = None,
    ) -> dict[str, Any]:
        """Scrape the inline Rufus ("Looking for specific info?") suggested
        questions from the product page.

        "Alex" is this project's name for Amazon's Rufus AI shopping assistant.
        Returns ``{"questions": [str, ...]}`` — the AI-suggested shopper
        questions the listing-optimization pipeline consumes. Raises
        :class:`CaptchaRequiredError` on a verification challenge (session parked)
        and :class:`LoginRequiredError` when browser-act is unavailable.
        """
        if not self.available():
            raise LoginRequiredError("browser-act 未安装，无法使用登录态抓取")

        url = f"https://{site}/dp/{asin}"
        async with self._lock:
            res = await self.client.open(url)
            if not res.ok:
                logger.warning("browser-act open failed: %s", res.stderr or res.stdout)
            await self.client.wait_stable()
            # The Rufus widget is lazy-loaded below the fold; scroll to trigger it.
            try:
                await self.client.eval_js(
                    "(() => { const e = document.querySelector('#dpx-rex-nice-widget-container');"
                    " (e || document.body).scrollIntoView({block:'center'});"
                    " window.scrollTo(0, document.body.scrollHeight*0.7); })()"
                )
                await self.client.wait_stable()
            except Exception:
                logger.debug("scroll-to-rufus failed", exc_info=True)

            await self._verifier.raise_if_blocking(
                context="scrape",
                screenshot_dir=screenshot_dir,
                tag=f"verify_alex_{asin}",
                subject=f"抓取 {asin} 的 Rufus 问题时",
            )

            raw = await self.client.eval_js(_JS_EXTRACT_ALEX)

        data = _parse_json_result(raw)
        qs = data.get("questions") if isinstance(data, dict) else None
        questions = [q for q in qs if isinstance(q, str)] if isinstance(qs, list) else []
        logger.info(
            "browser-act scraped %d Rufus questions for %s/%s", len(questions), site, asin
        )
        return {"questions": questions}

    async def submit_verification(self, answer: str) -> bool:
        async with self._lock:
            return await self._verifier.submit(answer)

    async def close(self) -> None:
        try:
            await self.client.close_session()
        except Exception:
            logger.debug("browser-act close_session failed", exc_info=True)


# --- Login / authentication ---


class LoginManager:
    """Establishes / probes the authenticated session. SRP: authentication."""

    def __init__(
        self,
        *,
        browser_name: str = "eco_listing",
        session_name: str = "eco_listing_login",
        proxy_region: str = "",
        headed: bool = False,
    ) -> None:
        self.client = BrowserActClient(
            browser_name=browser_name,
            session_name=session_name,
            dynamic_proxy=proxy_region,
            headed=headed,
        )
        self._verifier = VerificationHandler(self.client)
        self._lock = asyncio.Lock()

    @staticmethod
    def available() -> bool:
        return browser_act_available()

    async def is_logged_in(self, site: str = "amazon.com") -> bool:
        if not self.available():
            return False
        async with self._lock:
            try:
                await self.client.open(f"https://{site}/")
                await self.client.wait_stable()
                raw = await self.client.eval_js(_JS_IS_LOGGED_IN)
            except Exception:
                logger.warning("is_logged_in probe failed", exc_info=True)
                return False
        return bool((_parse_json_result(raw) or {}).get("loggedIn"))

    async def login(
        self,
        site: str,
        email: str,
        password: str,
        *,
        screenshot_dir: Optional[str] = None,
    ) -> bool:
        """Best-effort interactive login.

        Fills the Amazon sign-in form. If a captcha/OTP appears, screenshots it,
        leaves the session parked, and raises :class:`CaptchaRequiredError` with
        ``context="login"``. Returns True once the account nav shows a logged-in
        state.
        """
        if not self.available():
            raise LoginRequiredError("browser-act 未安装，无法登录")
        if not email or not password:
            raise LoginRequiredError("请先在配置中填写账号邮箱与密码")

        async with self._lock:
            # Land on the homepage first; short-circuit if already authenticated.
            await self.client.open(f"https://{site}/")
            await self.client.wait_stable()
            if bool((_parse_json_result(await self.client.eval_js(_JS_IS_LOGGED_IN)) or {}).get("loggedIn")):
                return True

            # Enter the real sign-in page via the account nav link's href.
            href = await self.client.eval_js(_JS_SIGNIN_HREF)
            if isinstance(href, str) and href.startswith("http"):
                await self.client.navigate(href)
                await self.client.wait_stable()

            # Step 1: email -> Continue.
            elements = await self.client.state()
            email_idx = _find_input(elements, "ap_email", "type=email", "mobile number or email")
            if email_idx is not None:
                await self.client.input(email_idx, email)
                # Native click (real mouse event) reliably submits; a JS
                # ``.click()`` is a silent no-op on Amazon's a-button, so it's
                # only a last resort when no element index was found.
                await self._submit(_find_clickable(elements, "id=continue"), _JS_CLICK_CONTINUE)
                await self.client.wait_stable()

            # Step 2: password -> Sign-In.
            elements = await self.client.state()
            pwd_idx = _find_input(elements, "ap_password", "type=password")
            if pwd_idx is not None:
                await self.client.input(pwd_idx, password)
                await self._submit(
                    _find_clickable(elements, "signinsubmit", "type=submit"), _JS_CLICK_SIGNIN
                )
                await self.client.wait_stable()

            # A sign-in form lingering here just means credentials weren't
            # accepted yet, so exclude it from the blocking check.
            await self._verifier.raise_if_blocking(
                context="login",
                screenshot_dir=screenshot_dir,
                tag="login_verify",
                include_signin=False,
                message="登录需要完成人机验证 / 二次验证，请在弹窗中输入",
            )

            raw = await self.client.eval_js(_JS_IS_LOGGED_IN)

        return bool((_parse_json_result(raw) or {}).get("loggedIn"))

    async def _submit(self, index: Optional[int], fallback_js: str) -> None:
        """Submit a sign-in step: prefer a native click on ``index`` (real mouse
        event), falling back to a JS ``.click()`` only when no index was found."""
        if index is not None:
            await self.client.click(index)
            return
        try:
            await self.client.eval_js(fallback_js)
        except Exception:
            logger.debug("fallback eval-click failed", exc_info=True)

    async def submit_verification(self, answer: str) -> bool:
        async with self._lock:
            return await self._verifier.submit(answer)

    async def capture_screenshot(self, path: str) -> str:
        async with self._lock:
            return await self._verifier.screenshot(path)

    async def close(self) -> None:
        try:
            await self.client.close_session()
        except Exception:
            logger.debug("browser-act close_session failed", exc_info=True)


# --- element matching helpers (against browser-act's parsed `state` output) ---
#
# Each element is ``{index, tag, text, attrs}`` where ``attrs`` is the raw
# attribute string (e.g. ``type=email id=ap_email_login name=email ...``), so we
# match on the attributes + visible label rather than label alone.

_INPUT_TAGS = {"input", "textarea", "textbox", "searchbox", "combobox"}


def _haystack(el: dict) -> str:
    return (str(el.get("attrs", "")) + " " + str(el.get("text", ""))).lower()


def _first_input(elements: list[dict]) -> Optional[int]:
    for el in elements:
        if el.get("tag", "").lower() in _INPUT_TAGS:
            return el.get("index")
    return None


def _find_input(elements: list[dict], *needles: str) -> Optional[int]:
    """Index of the first input-like element whose attrs/label match a needle."""
    for el in elements:
        if el.get("tag", "").lower() not in _INPUT_TAGS:
            continue
        hay = _haystack(el)
        if any(n in hay for n in needles):
            return el.get("index")
    return None


def _find_clickable(elements: list[dict], *needles: str) -> Optional[int]:
    """Index of the first element whose attrs/label match a needle."""
    for el in elements:
        if any(n in _haystack(el) for n in needles):
            return el.get("index")
    return None


def _find_submit(elements: list[dict]) -> Optional[int]:
    return _find_clickable(
        elements,
        "id=continue",
        "signinsubmit",
        "type=submit",
        "sign in",
        "verify",
        "登录",
        "继续",
        "确定",
        "提交",
    )
