from app.tools.keyword_tool import KeywordTool


class TestKeywordClean:
    def test_dedup_and_lowercase(self):
        tool = KeywordTool()
        raw = [
            {"keyword": "Waterproof", "search_volume": 100},
            {"keyword": "waterproof", "search_volume": 200},
            {"keyword": "Durable", "search_volume": 50},
        ]
        result = tool.clean(raw)
        assert len(result) == 2
        assert result[0]["keyword"] == "waterproof"
        assert result[0]["search_volume"] == 100

    def test_removes_empty(self):
        tool = KeywordTool()
        raw = [
            {"keyword": "", "search_volume": 100},
            {"keyword": "  ", "search_volume": 200},
            {"keyword": "valid", "search_volume": 50},
        ]
        result = tool.clean(raw)
        assert len(result) == 1
        assert result[0]["keyword"] == "valid"

    def test_sorts_by_search_volume(self):
        tool = KeywordTool()
        raw = [
            {"keyword": "low", "search_volume": 10},
            {"keyword": "high", "search_volume": 1000},
            {"keyword": "mid", "search_volume": 500},
        ]
        result = tool.clean(raw)
        assert [r["keyword"] for r in result] == ["high", "mid", "low"]


class TestSTOptimize:
    def test_byte_limit(self):
        tool = KeywordTool()
        listing = {
            "title": "Great Product",
            "bullet_points": ["Feature one"],
            "description": "A nice product",
        }
        classified = {
            "functional": [
                {"keyword": f"keyword{i}", "search_volume": 1000 - i}
                for i in range(50)
            ]
        }
        result = tool.optimize_st(listing, [], classified)
        total_bytes = len(" ".join(result["final_st"]).encode("utf-8"))
        assert total_bytes <= 249

    def test_removes_listing_duplicates(self):
        tool = KeywordTool()
        listing = {
            "title": "Waterproof Bag",
            "bullet_points": ["Durable material"],
            "description": "",
        }
        classified = {
            "functional": [
                {"keyword": "waterproof", "search_volume": 100},
                {"keyword": "unique_keyword", "search_volume": 50},
            ]
        }
        result = tool.optimize_st(listing, ["waterproof"], classified)
        assert "waterproof" not in result["final_st"]
        assert "unique_keyword" in result["final_st"]
