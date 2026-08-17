from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).with_name("search_news.py")
SPEC = importlib.util.spec_from_file_location("search_news", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


class SearchNewsTests(unittest.TestCase):
    def test_parse_rss(self):
        xml = b"<rss><channel><item><title>A</title><link>https://example.com/a</link><pubDate>Mon, 17 Aug 2026 08:00:00 GMT</pubDate></item></channel></rss>"
        items = MOD.parse_feed(xml, {"id": "x", "publisher": "X"})
        self.assertEqual(items[0]["title"], "A")

    def test_validate_story(self):
        sources = [
            {"id": "p1", "publisher": "A", "source_type": "press_article", "canonical_url": "https://a.example/x", "published_at": "2026-08-17T08:00:00Z", "observed_at": "2026-08-17T08:01:00Z", "locator": "p1"},
            {"id": "p2", "publisher": "B", "source_type": "press_article", "canonical_url": "https://b.example/x", "published_at": "2026-08-17T08:00:00Z", "observed_at": "2026-08-17T08:01:00Z", "locator": "p2"},
            {"id": "o1", "publisher": "기관", "source_type": "official_release", "canonical_url": "https://gov.example/x", "published_at": "2026-08-17T08:00:00Z", "observed_at": "2026-08-17T08:01:00Z", "locator": "p3"},
        ]
        story = {"schema_version": "1.0", "story_id": "x", "edition_at": "2026-08-17T17:00:00+09:00", "topic": "politics", "verified_headline": "x", "why_it_matters": "x", "official_required": True, "claims": [{"id": "c1", "text": "x", "status": "verified", "evidence_ids": ["p1", "p2", "o1"]}], "sources": sources, "verification_status": "verified"}
        MOD.validate_story(story)

    def test_rejects_portal_url(self):
        story = {"schema_version": "1.0", "story_id": "x", "edition_at": "x", "topic": "society", "verified_headline": "x", "why_it_matters": "x", "claims": [{"id": "c", "text": "x", "status": "verified", "evidence_ids": ["a", "b"]}], "sources": [
            {"id": "a", "publisher": "A", "source_type": "press_article", "canonical_url": "https://news.google.com/x", "published_at": "x", "observed_at": "x", "locator": "x"},
            {"id": "b", "publisher": "B", "source_type": "press_article", "canonical_url": "https://b.example/x", "published_at": "x", "observed_at": "x", "locator": "x"}], "verification_status": "verified"}
        with self.assertRaises(ValueError):
            MOD.validate_story(story)


if __name__ == "__main__":
    unittest.main()

