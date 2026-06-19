"""Ad-hoc capability test for a single ASIN (login + reviews + Alex Q&A).

Usage:
    python3 scripts/test_asin.py login
    python3 scripts/test_asin.py captcha <code>
    python3 scripts/test_asin.py reviews
    python3 scripts/test_asin.py alex
    python3 scripts/test_asin.py status

browser-act browsers persist on disk, so login state and a captcha-parked page
survive across separate invocations of this script.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.errors import CaptchaRequiredError, LoginRequiredError
from app.tools.browser_act_scraper import LoginManager, ReviewScraper

EMAIL = "jsli_2016@163.com"
PWD = "wcg12345!"
SITE = "amazon.com"
ASIN = "B099DW9MYJ"
SHOT_DIR = "artifacts/_test_asin"
HEADED = False


async def status() -> None:
    m = LoginManager(headed=HEADED)
    print("available:", m.available())
    print("logged_in:", await m.is_logged_in(SITE))


async def login() -> None:
    m = LoginManager(headed=HEADED)
    print("available:", m.available())
    if await m.is_logged_in(SITE):
        print("RESULT=ALREADY_LOGGED_IN")
        return
    try:
        ok = await m.login(SITE, EMAIL, PWD, screenshot_dir=SHOT_DIR)
        print("RESULT=LOGIN_OK" if ok else "RESULT=LOGIN_FAILED")
    except CaptchaRequiredError as e:
        print(f"RESULT=CAPTCHA_REQUIRED context={e.context} image={e.image_path}")
        print("MSG=", str(e))
    except LoginRequiredError as e:
        print("RESULT=LOGIN_REQUIRED", e)


async def captcha(code: str) -> None:
    m = LoginManager(headed=HEADED)
    cleared = await m.submit_verification(code)
    print("RESULT=CLEARED" if cleared else "RESULT=NOT_CLEARED")
    print("logged_in:", await m.is_logged_in(SITE))


async def reviews() -> None:
    rs = ReviewScraper(headed=HEADED)
    try:
        items = await rs.get_reviews(
            ASIN, SITE, max_pages=2, target_count=20, screenshot_dir=SHOT_DIR
        )
        print(f"RESULT=REVIEWS count={len(items)}")
        print(json.dumps(items, ensure_ascii=False, indent=2))
    except CaptchaRequiredError as e:
        print(f"RESULT=CAPTCHA_REQUIRED context={e.context} image={e.image_path}")
    finally:
        await rs.close()


async def alex() -> None:
    from app.tools.browser_tool import BrowserTool

    bt = BrowserTool()
    try:
        res = await bt.scrape_alex(ASIN, SITE)
        questions = res.get("questions", [])
        print(f"RESULT=ALEX questions={len(questions)} error={res.get('error', '')}")
        print(json.dumps(res, ensure_ascii=False, indent=2)[:4000])
    finally:
        await bt.close()


_CMDS = {
    "status": status,
    "login": login,
    "reviews": reviews,
    "alex": alex,
}


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: test_asin.py {status|login|captcha <code>|reviews|alex}")
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "captcha":
        if len(sys.argv) < 3:
            print("usage: test_asin.py captcha <code>")
            sys.exit(2)
        asyncio.run(captcha(sys.argv[2]))
    elif cmd in _CMDS:
        asyncio.run(_CMDS[cmd]())
    else:
        print(f"unknown command: {cmd}")
        sys.exit(2)


if __name__ == "__main__":
    main()
