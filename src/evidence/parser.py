"""
src/evidence/parser.py
Lightweight HTML/text parser. Extracts clean text from search result pages.
No RAG, no embeddings. Plain HTML parsing only.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

@dataclass
class ParsedContent:
    extracted_text: str
    source_title: str
    publication_date: Optional[str]
    parse_success: bool
    error_messages: List[str] = field(default_factory=list)
    truncated: bool = False

MAX_CONTENT_BYTES = 100_000

_CAUSAL_SIGNALS = frozenset([
    "because", "due to", "caused by", "resulted from",
    "as a result of", "in response to", "following",
    "triggered by", "driven by",
])

class SearchResultParser:
    """
    Parses HTML or plain text into clean extractable text.
    Always returns ParsedContent - never raises.
    """

    def parse(self, content: str, url: str = "") -> ParsedContent:
        if not content or not content.strip():
            return ParsedContent(
                extracted_text="", source_title="",
                publication_date=None, parse_success=True,
                error_messages=["Empty content"]
            )

        # Detect anti-scraping
        lower = content.lower()
        if any(p in lower for p in ["captcha", "verify you are human", "robot check", "access denied"]):
            return ParsedContent(
                extracted_text="", source_title="",
                publication_date=None, parse_success=False,
                error_messages=["Anti-scraping pattern detected"]
            )

        # Truncate
        truncated = False
        if len(content.encode("utf-8", errors="replace")) > MAX_CONTENT_BYTES:
            content = content[:MAX_CONTENT_BYTES]
            truncated = True

        # Try BeautifulSoup, fall back to regex
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            for tag in soup(["script","style","nav","header","footer","iframe"]):
                tag.decompose()
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            # Extract publication date from meta
            pub_date = None
            for meta in soup.find_all("meta"):
                prop = meta.get("property","") or meta.get("name","")
                if prop in ("article:published_time","datePublished","pubdate","date"):
                    pub_date = meta.get("content","") or None
                    if pub_date:
                        break
            paragraphs = []
            for tag in soup.find_all(["p","h1","h2","h3","h4","li","td"]):
                t = tag.get_text(separator=" ").strip()
                if len(t) > 30:
                    paragraphs.append(t)
            text = "\n\n".join(paragraphs)
            return ParsedContent(
                extracted_text=text, source_title=title,
                publication_date=pub_date, parse_success=True,
                truncated=truncated
            )
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("BeautifulSoup failed for %s: %s", url, exc)

        # Regex fallback
        try:
            text = re.sub(r"<[^>]+>", " ", content)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            title_m = re.search(r"<title[^>]*>([^<]+)</title>", content, re.I)
            title = title_m.group(1).strip() if title_m else ""
            return ParsedContent(
                extracted_text=text, source_title=title,
                publication_date=None, parse_success=True,
                truncated=truncated
            )
        except Exception as exc:
            return ParsedContent(
                extracted_text="", source_title="",
                publication_date=None, parse_success=False,
                error_messages=[str(exc)]
            )

    def has_causal_signal(self, text: str) -> bool:
        """
        Returns True if text contains causal language.
        NOTE: This is a SIGNAL only, not proof of causality.
        Verification must still assess whether causality is actually established.
        """
        t = text.lower()
        return any(s in t for s in _CAUSAL_SIGNALS)

    def segment_passages(self, text: str, min_len: int = 80, max_len: int = 800) -> List[str]:
        """Split extracted text into candidate passages for evidence extraction."""
        raw = [p.strip() for p in text.split("\n\n") if p.strip()]
        result = []
        for para in raw:
            if len(para) <= max_len:
                if len(para) >= min_len:
                    result.append(para)
            else:
                # split on sentence boundaries
                sentences = re.split(r"(?<=[.!?])\s+", para)
                buf = ""
                for s in sentences:
                    if len(buf) + len(s) + 1 > max_len and len(buf) >= min_len:
                        result.append(buf.strip())
                        buf = s
                    else:
                        buf = (buf + " " + s).strip() if buf else s
                if len(buf) >= min_len:
                    result.append(buf.strip())
        return result[:10]  # max 10 passages per source
