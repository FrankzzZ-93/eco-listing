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


class TestItemHighlightsAndBrand:
    def setup_method(self):
        self.tool = ComplianceTool()

    def _listing(self, **overrides):
        base = {
            "title": "Acme Widget for Home Use",
            "item_highlights": "Compact widget that fits small desks",
            "bullet_points": [],
            "description": "",
        }
        return {**base, **overrides}

    def test_default_title_limit_is_75(self):
        violations = self.tool.validate(self._listing(title="Acme " + "A" * 71))
        assert any("标题超长: 76 > 75" in v for v in violations)

    def test_item_highlights_too_long(self):
        violations = self.tool.validate(self._listing(item_highlights="H" * 126))
        assert any("Item Highlights 超长: 126 > 125" in v for v in violations)

    def test_item_highlights_limit_from_settings(self):
        limits = {"item_highlights_max_chars": 10}
        violations = self.tool.validate(self._listing(), limits)
        assert any("Item Highlights 超长" in v for v in violations)

    def test_item_highlights_empty(self):
        violations = self.tool.validate(self._listing(item_highlights="  "))
        assert any("Item Highlights 为空" in v for v in violations)

    def test_item_highlights_duplicates_title(self):
        violations = self.tool.validate(
            self._listing(item_highlights="acme widget for home use")
        )
        assert any("与标题完全重复" in v for v in violations)

    def test_listing_without_item_highlights_key_is_not_flagged(self):
        listing = self._listing()
        del listing["item_highlights"]
        assert not any("Item Highlights" in v for v in self.tool.validate(listing))

    def test_forbidden_word_in_item_highlights(self):
        violations = self.tool.validate(self._listing(item_highlights="The best widget"))
        assert any('"best"' in v for v in violations)

    def test_brand_first_word_ok(self):
        violations = self.tool.validate(self._listing(), brand="Acme")
        assert not any("品牌" in v for v in violations)

    def test_brand_missing_from_title(self):
        violations = self.tool.validate(self._listing(title="Widget by Acme"), brand="Acme")
        assert any('标题首词必须是品牌 "Acme"' in v for v in violations)

    def test_brand_case_must_match(self):
        violations = self.tool.validate(self._listing(title="ACME Widget"), brand="Acme")
        assert any("品牌" in v for v in violations)

    def test_brand_glued_to_next_word(self):
        violations = self.tool.validate(self._listing(title="AcmePro Widget"), brand="Acme")
        assert any("品牌" in v for v in violations)

    def test_no_brand_skips_check(self):
        violations = self.tool.validate(self._listing(title="Widget for Home"), brand="")
        assert not any("品牌" in v for v in violations)


class TestInternalTerms:
    def setup_method(self):
        self.tool = ComplianceTool()

    def _listing(self, bullet):
        return {
            "title": "Acme Belt Hanger",
            "item_highlights": "Holds belts and ties",
            "bullet_points": [bullet],
            "description": "",
        }

    def test_confirmed_header_flagged(self):
        violations = self.tool.validate(
            self._listing("FOR CONFIRMED SPACES: Use it in bedrooms and dorms")
        )
        assert any('内部流程用语 "confirmed"' in v for v in violations)

    def test_attribute_table_flagged(self):
        violations = self.tool.validate(
            self._listing("SIZE: Dimensions per the attributes are 10 inches")
        )
        assert any('"per the attributes"' in v for v in violations)

    def test_chinese_term_flagged(self):
        violations = self.tool.validate(self._listing("SIZE: 尺寸为已确认的10英寸"))
        assert any('"已确认"' in v for v in violations)

    def test_normal_copy_not_flagged(self):
        violations = self.tool.validate(
            self._listing("FITS STANDARD CLOSET RODS: Hangs in bedrooms and dorm closets")
        )
        assert not any("内部流程用语" in v for v in violations)
