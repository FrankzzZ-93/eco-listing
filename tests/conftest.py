import json
import os
from unittest.mock import AsyncMock

import pytest

from app.agents.base import ToolBox
from app.agents.prompts import PromptRegistry
from app.tools.compliance_tool import ComplianceTool
from app.tools.file_store import FileStoreTool
from app.tools.keyword_tool import KeywordTool
from app.tools.llm_tool import LLMTool

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def tmp_artifacts(tmp_path):
    return str(tmp_path)


@pytest.fixture
def mock_llm():
    llm = LLMTool()
    llm._invoke = AsyncMock(
        return_value={
            "title": "Test Product - Premium Quality Widget for Home & Office",
            "bullet_points": [
                "DURABLE DESIGN - Built to last with premium materials",
                "EASY TO USE - Simple setup in minutes",
                "VERSATILE - Perfect for home and office use",
                "COMPACT SIZE - Fits any workspace",
                "SATISFACTION - Designed for your comfort",
            ],
            "description": "Discover the perfect widget for your needs.",
            "search_terms": ["widget", "premium", "home office"],
            "target_users": ["home users", "office workers"],
            "use_cases": ["daily work", "home improvement"],
            "pain_points": ["poor durability", "complex setup"],
            "core_features": ["durable", "easy setup"],
            "selling_points": ["premium materials", "compact design"],
            "language_patterns": ["love this", "works great"],
            "confidence": 0.85,
            "notes": "Good overall quality",
            "questions": ["Is it waterproof?", "What are the dimensions?"],
            "functional": [
                {"keyword": "waterproof", "search_volume": 12000},
            ],
            "scenario": [
                {"keyword": "camping", "search_volume": 8000},
            ],
            "audience": [
                {"keyword": "for kids", "search_volume": 5000},
            ],
            "selling_point": [
                {"keyword": "lightweight", "search_volume": 9000},
            ],
            "emotional": [
                {"keyword": "premium", "search_volume": 7000},
            ],
        }
    )
    return llm


@pytest.fixture
def mock_toolbox(tmp_artifacts, mock_llm):
    _setup_test_prompts()
    return ToolBox(
        llm=mock_llm,
        keyword=KeywordTool(),
        compliance=ComplianceTool(rules_dir=os.path.join(FIXTURES_DIR, "compliance_rules")),
        file_store=FileStoreTool(tmp_artifacts),
        prompts=PromptRegistry(os.path.join(FIXTURES_DIR, "prompts")),
    )


def _setup_test_prompts():
    """Create minimal prompt fixtures if they don't exist."""
    prompts_dir = os.path.join(FIXTURES_DIR, "prompts")
    rules_dir = os.path.join(FIXTURES_DIR, "compliance_rules")
    os.makedirs(rules_dir, exist_ok=True)

    rules_file = os.path.join(rules_dir, "general.md")
    if not os.path.exists(rules_file):
        with open(rules_file, "w") as f:
            f.write("# Test Rules\nNo forbidden words: best, cheapest\n")

    agents = {
        "research": {
            "templates": {"rufus_extract": {"active": "v1", "model": "gemini-pro"}},
            "files": {"rufus_extract_v1.md": "Extract questions from {{ screenshot_count }} screenshots.\nReturn JSON with questions list."},
        },
        "product_analyst": {
            "templates": {
                "info_fusion": {"active": "v1", "model": "gemini-pro"},
                "self_eval": {"active": "v1", "model": "claude-sonnet"},
            },
            "files": {
                "info_fusion_v1.md": "Analyze:\n{{ competitor_listings }}\n{{ review_summary }}\n{{ rufus_questions }}\nReturn product attributes JSON.",
                "self_eval_v1.md": "Evaluate:\n{{ draft }}\nReturn {confidence, notes}.",
            },
        },
        "keyword_strategist": {
            "templates": {"classify": {"active": "v1", "model": "claude-sonnet"}},
            "files": {
                "classify_v1.md": "Classify keywords:\n{{ product_attributes }}\n{{ keywords }}\nReturn categorized JSON.",
            },
        },
        "copywriter": {
            "templates": {
                "round_1_draft": {"active": "v1", "model": "gemini-pro"},
                "round_2_rufus": {"active": "v1", "model": "claude-sonnet"},
                "round_3_compliance": {"active": "v1", "model": "claude-sonnet"},
            },
            "files": {
                "round_1_draft_v1.md": "Write listing from:\n{{ approved_product_attributes }}\n{{ classified_keywords }}",
                "round_2_rufus_v1.md": "Optimize with Rufus:\n{{ draft_v1 }}\n{{ product_attributes }}\n{{ rufus_questions }}",
                "round_3_compliance_v1.md": "Fix compliance:\n{{ draft_v2 }}\n{{ product_attributes }}\n{{ compliance_rules }}\n{{ previous_violations }}",
            },
        },
    }

    for agent_name, spec in agents.items():
        agent_dir = os.path.join(prompts_dir, agent_name)
        os.makedirs(agent_dir, exist_ok=True)

        meta_path = os.path.join(agent_dir, "meta.json")
        if not os.path.exists(meta_path):
            with open(meta_path, "w") as f:
                json.dump({"templates": spec["templates"]}, f)

        for fname, content in spec["files"].items():
            fpath = os.path.join(agent_dir, fname)
            if not os.path.exists(fpath):
                with open(fpath, "w") as f:
                    f.write(content)
