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
