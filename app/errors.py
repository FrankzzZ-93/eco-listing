class EcoListingError(Exception):
    pass


class AgentError(EcoListingError):
    def __init__(self, agent: str, action: str, message: str):
        self.agent = agent
        self.action = action
        super().__init__(f"[{agent}.{action}] {message}")


class LLMError(EcoListingError):
    pass


class ComplianceError(EcoListingError):
    pass


class CaptchaRequiredError(EcoListingError):
    """Raised when scraping hits an interactive human-verification challenge.

    Carries the path to a screenshot of the challenge so the UI can render it in
    a captcha modal, plus a context label distinguishing a run-scrape captcha
    from an account-login captcha. The scraper that raises this keeps its
    browser-act session alive (the page is parked on the challenge) so the
    submitted answer can be typed back into the same live page.
    """

    def __init__(self, message: str, image_path: str = "", context: str = "scrape"):
        self.image_path = image_path
        self.context = context
        super().__init__(message)


class LoginRequiredError(EcoListingError):
    """Raised when an operation needs an authenticated session but none exists."""

    def __init__(self, message: str = "需要先登录账号"):
        super().__init__(message)
