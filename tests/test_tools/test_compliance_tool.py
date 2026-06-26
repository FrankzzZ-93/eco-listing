from app.tools.compliance_tool import ComplianceTool


class TestComplianceValidate:
    def setup_method(self):
        self.tool = ComplianceTool()

    def test_valid_listing(self):
        # Within hard limits, no forbidden words / ASIN strings -> no hard
        # violations. Soft minimums (content-fullness encouragement, e.g.
        # "标题过短") are disabled here so this test targets the hard-validation
        # path in isolation.
        listing = {
            "title": "Premium Widget for Home Use",
            # 5 complete, non-empty bullets (the pipeline always ships 5).
            "bullet_points": [
                "DURABLE BUILD made to last.",
                "EASY SETUP in minutes.",
                "VERSATILE for home and office.",
                "COMPACT design saves space.",
                "RELIABLE everyday performance.",
            ],
            "description": "A great product for daily use.",
        }
        no_soft_minimums = {
            "title_min_chars": 0,
            "bullets_total_min_bytes": 0,
            "description_min_chars": 0,
        }
        assert self.tool.validate(listing, no_soft_minimums) == []

    def test_title_too_long(self):
        listing = {
            "title": "A" * 201,
            "bullet_points": [],
            "description": "",
        }
        violations = self.tool.validate(listing)
        assert any("标题超长" in v for v in violations)

    def test_bullet_too_long(self):
        listing = {
            "title": "OK Title",
            "bullet_points": ["B" * 501],
            "description": "",
        }
        violations = self.tool.validate(listing)
        assert any("Bullet #1 超长" in v for v in violations)

    def test_forbidden_word_best(self):
        listing = {
            "title": "The best product ever",
            "bullet_points": [],
            "description": "",
        }
        violations = self.tool.validate(listing)
        assert any('"best"' in v for v in violations)

    def test_forbidden_word_free(self):
        listing = {
            "title": "Get it free today",
            "bullet_points": [],
            "description": "",
        }
        violations = self.tool.validate(listing)
        assert any('"free"' in v for v in violations)

    def test_multiple_violations(self):
        listing = {
            "title": "A" * 250 + " best product guaranteed",
            "bullet_points": [],
            "description": "",
        }
        violations = self.tool.validate(listing)
        assert len(violations) >= 3  # title length + best + guaranteed
