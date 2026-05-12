from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.agents.prompts import PromptRegistry
from app.tools.browser_tool import BrowserTool
from app.tools.compliance_tool import ComplianceTool
from app.tools.file_store import FileStoreTool
from app.tools.keyword_tool import KeywordTool
from app.tools.llm_tool import LLMTool


@dataclass
class ToolBox:
    llm: LLMTool
    keyword: KeywordTool
    compliance: ComplianceTool
    file_store: FileStoreTool
    prompts: PromptRegistry
    browser: Optional[BrowserTool] = None
