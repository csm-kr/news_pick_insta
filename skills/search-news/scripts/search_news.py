#!/usr/bin/env python3
"""Discover RSS candidates and validate a selected news story."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REGISTRY = Path(__file__).resolve().parent.parent / "references" / "source-registry.json"
BLOCKED_HOSTS = {"news.google.com", "search.naver.com", "news.naver.com"}


def parse_time(value: str) -> datetime:
    value = (value or "").strip()
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        result = parsedate_to_datetime(value)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def clean_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"유효하지 않은 URL: {value}")
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ""))


def text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in list(node):
        local = child.tag.rsplit("}", 1)[-1].lower()
        if local in names and (child.text or "").strip():
            return (child.text or "").strip()
        if local == "link" and "link" in names and child.attrib.get("href"):
            return child.attrib["href"].strip()
    return ""


def parse_feed(data: bytes, source: dict[str, Any]) -> list[dict[str, Any]]:
    root = ET.fromstring(data)
    entries = [n for n in root.iter() if n.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    results = []
    for item in entries:
        title = text(item, ("title",))
        link = text(item, ("link",))
        published = text(item, ("pubdate", "published", "updated", "date"))
        if not title or not link or not published:
            continue
        try:
            when = parse_time(published)
            url = clean_url(link)
        except (ValueError, TypeError):
            continue
        results.append({
            "source_id": source["id"],
            "publisher": source["publisher"],
            "title": title,
            "canonical_url": url,
            "published_at": when.isoformat().replace("+00:00", "Z"),
            "source_type": "press_article",
            "status": "candidate",
        })
    return results


def fetch_source(source: dict[str, Any], timeout: float = 10) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    request = urllib.request.Request(source["url"], headers={"User-Agent": "newspick-search-news/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(5_000_000)
        items = parse_feed(data, source)
        if not items:
            raise ValueError("feed item을 파싱하지 못했다.")
        return items, {"source_id": source["id"], "ok": True, "items": len(items)}
    except Exception as exc:  # source별 실패를 다른 source와 격리
        return [], {"source_id": source["id"], "ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}


def discover(since: datetime, until: datetime, registry_path: Path = REGISTRY) -> dict[str, Any]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    sources = [s for s in registry["sources"] if s.get("enabled") and s.get("type") == "rss"]
    candidates: list[dict[str, Any]] = []
    health = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(sources))) as pool:
        for items, record in pool.map(fetch_source, sources):
            health.append(record)
            candidates.extend(items)
    unique = {}
    for item in candidates:
        when = parse_time(item["published_at"])
        if since <= when <= until:
            unique[item["canonical_url"]] = item
    return {
        "schema_version": "1.0",
        "window": {"since": since.isoformat(), "until": until.isoformat()},
        "candidates": sorted(unique.values(), key=lambda x: x["published_at"], reverse=True),
        "source_health": sorted(health, key=lambda x: x["source_id"]),
    }


def validate_story(story: dict[str, Any]) -> None:
    required = {"schema_version", "story_id", "edition_at", "topic", "verified_headline", "why_it_matters", "claims", "sources", "verification_status"}
    missing = sorted(required - set(story))
    if missing:
        raise ValueError(f"필수 필드 누락: {missing}")
    if story["verification_status"] != "verified":
        raise ValueError("verification_status는 verified여야 한다.")
    if story["topic"] not in {"politics", "real_estate", "economy", "society"}:
        raise ValueError("지원하지 않는 topic이다.")
    source_ids = set()
    press_publishers = set()
    official = 0
    for source in story["sources"]:
        for field in ("id", "publisher", "source_type", "canonical_url", "published_at", "observed_at", "locator"):
            if not source.get(field):
                raise ValueError(f"source 필드 누락: {field}")
        host = (urlsplit(clean_url(source["canonical_url"])).hostname or "").lower()
        if host in BLOCKED_HOSTS:
            raise ValueError(f"중계/검색 URL은 근거가 아니다: {host}")
        if source["id"] in source_ids:
            raise ValueError(f"중복 source id: {source['id']}")
        source_ids.add(source["id"])
        if source["source_type"] == "press_article":
            press_publishers.add(source["publisher"])
        if source["source_type"] == "official_release":
            official += 1
    if len(press_publishers) < 2:
        raise ValueError("독립 언론사 원문 두 곳 이상이 필요하다.")
    if story.get("official_required") and official < 1:
        raise ValueError("이 사건에는 공식 원문이 필요하다.")
    if not story["claims"]:
        raise ValueError("claim이 없다.")
    for claim in story["claims"]:
        if claim.get("status") != "verified" or not claim.get("text"):
            raise ValueError("모든 claim은 verified text여야 한다.")
        evidence = set(claim.get("evidence_ids", []))
        if len(evidence & source_ids) < 2:
            raise ValueError(f"claim {claim.get('id')}의 근거가 두 곳 미만이다.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    disc = commands.add_parser("discover")
    disc.add_argument("--since", required=True)
    disc.add_argument("--until", required=True)
    disc.add_argument("--registry", type=Path, default=REGISTRY)
    disc.add_argument("--output", type=Path, required=True)
    val = commands.add_parser("validate")
    val.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "discover":
            payload = discover(parse_time(args.since), parse_time(args.until), args.registry)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = {"output": str(args.output.resolve()), "candidates": len(payload["candidates"]), "sources_ok": sum(x["ok"] for x in payload["source_health"])}
        else:
            validate_story(json.loads(args.input.read_text(encoding="utf-8")))
            result = {"valid": True, "input": str(args.input.resolve())}
    except (OSError, ValueError, KeyError, ET.ParseError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

