"""
Wikipedia client service.

Provides functions to retrieve a page title and cleaned text for either a topic
or a direct Wikipedia URL. Includes retry logic and respects a REQUEST_TIMEOUT
environment variable.

Notes:
- Designed for easy mocking in tests; network calls are isolated in functions.
- Uses wikipedia-api for robust fetching by page title, with a fallback to the
  'wikipedia' package for search/summary when appropriate.
- For direct URLs, uses requests + BeautifulSoup to extract the text content.

Environment variables:
- REQUEST_TIMEOUT: integer seconds for HTTP requests and library calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup
import wikipedia as wikipedia_py
import wikipediaapi

from api.utils.env import get_request_timeout
from api.utils.logging import get_logger
from api.exceptions import FetchError
from api.utils.context import build_log_ctx

logger = get_logger(__name__)


@dataclass
class WikipediaPage:
    """Container for fetched Wikipedia content."""
    title: str
    url: str
    text: str


def _clean_text(text: str) -> str:
    return " ".join((text or "").split())


def _fetch_by_title(title: str, lang: str = "en") -> Optional[WikipediaPage]:
    """
    Fetch a Wikipedia page by exact title using wikipedia-api.
    """
    wiki = wikipediaapi.Wikipedia(language=lang, extract_format=wikipediaapi.ExtractFormat.WIKI)
    page = wiki.page(title)
    if not page.exists():
        return None
    return WikipediaPage(title=page.title, url=page.fullurl, text=_clean_text(page.text))


def _search_and_fetch(topic: str, lang: str = "en") -> Optional[WikipediaPage]:
    """
    Search for a topic using 'wikipedia' package and then fetch using wikipedia-api.
    """
    try:
        wikipedia_py.set_lang(lang)
        results = wikipedia_py.search(topic)
        if not results:
            return None
        # take the first result
        best = results[0]
        page = _fetch_by_title(best, lang=lang)
        if page:
            return page
        # As a last resort, return summary from wikipedia package
        summary = wikipedia_py.summary(best)
        url = wikipedia_py.page(best).url
        return WikipediaPage(title=best, url=url, text=_clean_text(summary))
    except Exception as e:
        logger.warning(
            "Search and fetch failed for topic",
            extra=build_log_ctx(extra={"topic": topic, "error": str(e)}),
        )
        return None


def _fetch_from_url(url: str, timeout: int) -> Optional[WikipediaPage]:
    """
    Fetch Wikipedia page content from a direct URL by scraping.
    This is a fallback for when titles aren't available.
    """
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # Extract title and content paragraphs
        title_tag = soup.find("h1", id="firstHeading")
        title = title_tag.get_text(strip=True) if title_tag else url
        content_div = soup.find("div", id="mw-content-text")
        paragraphs = []
        if content_div:
            for p in content_div.find_all("p"):
                txt = p.get_text(" ", strip=True)
                if txt:
                    paragraphs.append(txt)
        text = _clean_text(" ".join(paragraphs))
        canonical = soup.find("link", rel="canonical")
        page_url = canonical["href"] if canonical and canonical.get("href") else url
        return WikipediaPage(title=title, url=page_url, text=text)
    except Exception as e:
        logger.warning(
            "Fetch from URL failed",
            extra=build_log_ctx(extra={"url": url, "error": str(e)}),
        )
        return None


# PUBLIC_INTERFACE
def fetch_wikipedia(topic_or_url: str, lang: str = "en", retries: int = 2) -> Optional[WikipediaPage]:
    """
    Fetch Wikipedia content for a given topic string or URL.

    Args:
        topic_or_url: Search topic or direct Wikipedia URL.
        lang: Wikipedia language code, default 'en'.
        retries: Number of retries on transient failures.

    Returns:
        WikipediaPage or None if not found/fetchable.
    """
    timeout = get_request_timeout()
    value = (topic_or_url or "").strip()
    if not value:
        return None

    is_url = value.lower().startswith("http://") or value.lower().startswith("https://")
    attempt = 0
    while attempt <= retries:
        try:
            if is_url:
                page = _fetch_from_url(value, timeout=timeout)
                if page and page.text:
                    return page
            else:
                # Try exact title first
                page = _fetch_by_title(value, lang=lang)
                if page and page.text:
                    return page
                # Fallback to search-based fetch
                page = _search_and_fetch(value, lang=lang)
                if page and page.text:
                    return page
            # If reached here, we didn't get text; break and retry
            attempt += 1
            logger.info(
                "Fetch attempt failed; will retry if attempts remain",
                extra=build_log_ctx(extra={"attempt": attempt, "value": value, "retries": retries}),
            )
        except Exception as e:
            logger.info(
                "Fetch attempt raised exception; will retry if attempts remain",
                extra=build_log_ctx(extra={"attempt": attempt, "value": value, "error": str(e), "retries": retries}),
            )
            attempt += 1

    raise FetchError(f"Unable to fetch Wikipedia content for: {value}")
