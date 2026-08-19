# mcp_tools.py — Knowledge ingestion: URL fetching, text extraction, chunking
import ipaddress
import re
import logging
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("wildtails.mcp_tools")

# Safety limits
FETCH_TIMEOUT = 15  # seconds
MAX_CONTENT_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_TEXT_CHARS = 50_000  # truncate extracted text beyond this


# --- SSRF-safe URL validation ---

# Private / reserved IP ranges that must never be fetched
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def validate_url(url: str) -> str | None:
    """Validate a URL for safe external fetching.

    Returns the cleaned URL or None if the URL is invalid/blocked.
    Rules:
    - Only http/https schemes allowed
    - Hostname must not resolve to a private/local IP (SSRF prevention)
    - No empty or overly long URLs
    """
    if not url or len(url) > 4096:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    # Only allow http/https
    if parsed.scheme not in ("http", "https"):
        return None

    hostname = parsed.hostname
    if not hostname:
        return None

    # Resolve hostname and check against blocked networks
    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            for net in _BLOCKED_NETWORKS:
                if ip in net:
                    logger.warning("URL %s resolves to blocked IP %s", url, ip)
                    return None
    except socket.gaierror:
        # Can't resolve hostname — allow it (will fail at fetch time)
        pass

    return url


def _is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube video."""
    parsed = urlparse(url)
    return parsed.hostname in (
        "www.youtube.com", "youtube.com", "youtu.be", "m.youtube.com",
    )


def _extract_youtube_video_id(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    parsed = urlparse(url)
    if parsed.hostname == "youtu.be":
        return parsed.path.lstrip("/")
    if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        return qs.get("v", [None])[0]
    return None


def _fetch_youtube_transcript(url: str) -> dict | None:
    """Attempt to fetch YouTube transcript via youtube-transcript-api."""
    video_id = _extract_youtube_video_id(url)
    if not video_id:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # Prefer Vietnamese, then English, then any available
        transcript = None
        for lang in ["vi", "en"]:
            try:
                transcript = transcript_list.find_transcript([lang])
                break
            except Exception:
                continue
        if transcript is None:
            transcript = transcript_list.find_generated_transcript(["en", "vi"])
        entries = transcript.fetch()
        full_text = " ".join(e.text for e in entries)
        return {
            "title": f"YouTube Transcript [{video_id}]",
            "text": full_text[:MAX_TEXT_CHARS],
            "source_type": "youtube_transcript",
        }
    except ImportError:
        logger.info("youtube-transcript-api not installed, falling back to page scrape")
        return None
    except Exception as e:
        logger.warning("YouTube transcript fetch failed: %s", e)
        return None


def _fetch_article(url: str) -> dict | None:
    """Fetch and extract readable text from a web article via BeautifulSoup."""
    try:
        headers = {
            "User-Agent": "WildTails-KnowledgeBot/1.0",
            "Accept": "text/html,application/xhtml+xml",
        }
        resp = requests.get(url, timeout=FETCH_TIMEOUT, headers=headers, stream=True)
        resp.raise_for_status()

        # Enforce size limit by reading in chunks
        content_parts = []
        total = 0
        for chunk in resp.iter_content(chunk_size=8192, decode_unicode=False):
            total += len(chunk)
            if total > MAX_CONTENT_BYTES:
                logger.warning("Content exceeds %d bytes, truncating", MAX_CONTENT_BYTES)
                break
            content_parts.append(chunk)
        raw_html = b"".join(content_parts)

        soup = BeautifulSoup(raw_html, "html.parser")

        # Extract title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else url

        # Remove non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
            tag.decompose()

        # Try <article> first, then <main>, then <body>
        content_el = soup.find("article") or soup.find("main") or soup.find("body")
        if content_el is None:
            return None

        # Extract text, collapse whitespace
        text = content_el.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text[:MAX_TEXT_CHARS]

        return {
            "title": title,
            "text": text,
            "source_type": "article",
        }
    except requests.RequestException as e:
        logger.warning("Article fetch failed for %s: %s", url, e)
        return None
    except Exception as e:
        logger.warning("Article parsing failed for %s: %s", url, e)
        return None


def fetch_and_extract(url: str) -> dict | None:
    """Main entry point: fetch URL content and return extracted text.

    Returns dict with keys: title, text, source_type
    or None on failure.
    Applies SSRF-safe URL validation before any network request.
    """
    safe_url = validate_url(url)
    if safe_url is None:
        logger.warning("URL validation failed for: %s", url)
        return None

    if _is_youtube_url(safe_url):
        result = _fetch_youtube_transcript(safe_url)
        if result is not None:
            return result
        # Fall through to article scrape for YouTube pages without transcript

    return _fetch_article(safe_url)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks by word boundaries.

    Args:
        text: The full text to chunk.
        chunk_size: Target number of words per chunk.
        overlap: Number of overlapping words between consecutive chunks.
    """
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap

    return chunks
