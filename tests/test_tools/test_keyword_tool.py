import io

import openpyxl

from app.tools.keyword_tool import KeywordTool, parse_xlsx_keywords


def _xlsx_bytes(rows: list[list]) -> bytes:
    """Build an in-memory .xlsx (first row = header) and return its bytes."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestParseXlsxKeywords:
    def test_xiyou_weekly_avg_volume_variant(self):
        """Regression: 西柚 export naming the column '周平均搜索量' (not '周搜索量')
        must still parse real search volumes, not 0."""
        data = _xlsx_bytes([
            ["关键词 (数据来源于西柚洞察)", "翻译", "周平均搜索量", "CPC建议竞价($)", "点击转化率(均值)"],
            ["kitchenaid mixer attachments", "KitchenAid搅拌机配件", 8087, 1.23, 0.104999],
            ["flour funnel", "面粉漏斗", 1450, 0.59, 0.139767],
        ])
        parsed = parse_xlsx_keywords(data)
        assert [p["search_volume"] for p in parsed] == [8087, 1450]
        assert parsed[0]["translation"] == "KitchenAid搅拌机配件"
        assert parsed[0]["bid_price"] == 1.23

    def test_oulu_format_still_parses(self):
        data = _xlsx_bytes([
            ["流量关键词", "月搜索量", "机会指数"],
            ["dog toy", 5000, 0.6],
            ["puppy ball", 1200, 0.1],
        ])
        parsed = parse_xlsx_keywords(data)
        assert [p["search_volume"] for p in parsed] == [5000, 1200]
        assert parsed[0]["competition"] == "低"   # opp 0.6 -> 低
        assert parsed[1]["competition"] == "高"   # opp 0.1 -> 高

    def test_repairs_all_zero_when_volume_header_unrecognized(self):
        """Validation+repair: an unfamiliar volume header ('周热度') yields all-0,
        so the parser backfills from the most search-volume-like numeric column."""
        data = _xlsx_bytes([
            ["关键词 (西柚)", "翻译", "周热度", "CPC建议竞价($)", "点击转化率"],
            ["dog ball toy", "狗球玩具", 3200, 1.10, 0.08],
            ["led dog toy", "LED狗玩具", 900, 0.75, 0.05],
        ])
        parsed = parse_xlsx_keywords(data)
        assert [p["search_volume"] for p in parsed] == [3200, 900]

    def test_clean_from_bytes_sorts_and_dedupes(self):
        data = _xlsx_bytes([
            ["关键词 (数据来源于西柚洞察)", "翻译", "周平均搜索量"],
            ["Dog Toy", "狗玩具", 100],
            ["dog toy", "狗玩具", 999],   # dup (case) -> first wins in clean
            ["ball", "球", 500],
        ])
        cleaned = KeywordTool().clean(data)
        assert [c["keyword"] for c in cleaned] == ["ball", "dog toy"]
        assert cleaned[0]["search_volume"] == 500


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
                {"keyword": "spacious", "search_volume": 50},
            ]
        }
        # ST is now a bag of unique single words: words already indexed in the
        # listing (waterproof) are dropped; novel words (spacious) are kept.
        result = tool.optimize_st(listing, ["waterproof"], classified)
        assert "waterproof" not in result["final_st"]
        assert "spacious" in result["final_st"]

    def test_dedupes_words_across_phrases(self):
        tool = KeywordTool()
        listing = {"title": "Belt Hanger", "bullet_points": [], "description": ""}
        st_v3 = [
            "closet organizers and storage",
            "closet organizer",
            "hat organizer",
            "closet organization",
        ]
        result = tool.optimize_st(listing, st_v3, {})
        st = result["final_st"]
        # No word repeats across the ST bag.
        assert len(st) == len(set(st))
        # Shared words appear exactly once.
        assert st.count("closet") == 1
        assert st.count("organizer") == 1
