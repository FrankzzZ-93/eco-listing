"""Ad-hoc capability test for a single ASIN (login + reviews + Alex Q&A) on the
real-Chrome engine.

Usage:
    python3 scripts/test_asin.py status      # is the persistent profile logged in?
    python3 scripts/test_asin.py login       # open a headed Chrome to log in manually
    python3 scripts/test_asin.py reviews [ASIN]
    python3 scripts/test_asin.py alex [ASIN]

Login is manual (Amazon blocks scripted form-fills): ``login`` opens the real
Chrome window and you sign in yourself; the session persists in the Chrome
profile (``settings.chrome_profile_dir``) across invocations. No credentials are
stored here.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.errors import CaptchaRequiredError
from app.tools.chrome_session import LoginManager, ReviewScraper

SITE = "amazon.com"
DEFAULT_ASIN = "B099DW9MYJ"
SHOT_DIR = "artifacts/_test_asin"


def _asin() -> str:
    return sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ASIN


async def status() -> None:
    m = LoginManager()
    print("available:", m.available())
    print("logged_in:", await m.is_logged_in(SITE))


async def login() -> None:
    m = LoginManager()
    print("available:", m.available())
    if await m.is_logged_in(SITE):
        print("RESULT=ALREADY_LOGGED_IN")
        return
    await m.open_for_login(SITE)
    print("RESULT=WINDOW_OPENED — 请在打开的 Chrome 窗口中手动登录，然后跑 `status` 确认")


async def reviews() -> None:
    rs = ReviewScraper()
    try:
        items = await rs.get_reviews(
            _asin(), SITE, max_pages=2, target_count=20, screenshot_dir=SHOT_DIR
        )
        print(f"RESULT=REVIEWS count={len(items)}")
        print(json.dumps(items, ensure_ascii=False, indent=2))
    except CaptchaRequiredError as e:
        print(f"RESULT=CAPTCHA_REQUIRED image={e.image_path} — 请在窗口里处理后重试")
    finally:
        await rs.close()


async def alex() -> None:
    from app.tools.browser_tool import BrowserTool

    bt = BrowserTool()
    try:
        res = await bt.scrape_alex(_asin(), SITE)
        questions = res.get("questions", [])
        print(f"RESULT=ALEX questions={len(questions)} error={res.get('error', '')}")
        print(json.dumps(res, ensure_ascii=False, indent=2)[:4000])
    finally:
        await bt.close()


_CMDS = {"status": status, "login": login, "reviews": reviews, "alex": alex}


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in _CMDS:
        asyncio.run(_CMDS[cmd]())
    else:
        print("usage: test_asin.py {status|login|reviews [ASIN]|alex [ASIN]}")
        sys.exit(2)


if __name__ == "__main__":
    main()
