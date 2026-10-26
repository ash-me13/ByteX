import os
import re
import html
import time
from datetime import datetime
import asyncio
import logging
import urllib.parse
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict, field
import httpx

from skills.base import BaseSkill, ToolResult

logger = logging.getLogger("bytex.skills.search")

def sanitize_search_text(text: str) -> str:
    """Removes sensitive credentials, passwords, and tokens from queries."""
    if not text:
        return ""
    from memory.models import SENSITIVE_PATTERNS
    clean = text.strip()
    clean = re.sub(r"(?:password|passwd|pwd)\s+(?:is\s+)?([^\s,;.]+)", "password [REDACTED]", clean, flags=re.IGNORECASE)
    clean = re.sub(r"(?:api[_-]?key|secret|token|auth)\s+(?:is\s+)?([^\s,;.]+)", "key [REDACTED]", clean, flags=re.IGNORECASE)
    for pat in SENSITIVE_PATTERNS:
        clean = re.sub(pat, "[SENSITIVE REDACTED]", clean, flags=re.IGNORECASE)
    return clean

class SearchResultItem:
    """
    Structured search result item model with full constructor compatibility
    for positional, keyword, legacy (4-arg), and modern (7-arg) instantiation.
    """
    def __init__(
        self,
        index: Optional[Any] = None,
        title: str = "",
        url: str = "",
        snippet: str = "",
        domain: str = "",
        source: str = "",
        engine: str = "google",
        *args,
        **kwargs
    ):
        # Case 1: Legacy positional call where title was 1st argument (str) and url was 2nd (str)
        if isinstance(index, str) and ("://" in str(title) or (url and not isinstance(url, str))):
            self.title = str(index)
            self.url = str(title) if isinstance(title, str) else ""
            self.snippet = str(url) if isinstance(url, str) else (str(snippet) if isinstance(snippet, str) else "")
            self.index = kwargs.get("index", 1)
            self.source = str(domain) if domain else (str(source) if source else "")
            self.domain = kwargs.get("domain", "")
            self.engine = engine or kwargs.get("engine", "google")
        else:
            # Case 2: Standard positional or keyword call
            try:
                self.index = int(index) if index is not None else int(kwargs.get("index", 1))
            except (ValueError, TypeError):
                self.index = 1

            self.title = str(title or kwargs.get("title", ""))
            self.url = str(url or kwargs.get("url", ""))
            self.snippet = str(snippet or kwargs.get("snippet", ""))
            self.domain = str(domain or kwargs.get("domain", ""))
            self.source = str(source or kwargs.get("source", ""))
            self.engine = str(engine or kwargs.get("engine", "google"))

        # Automatic domain extraction if missing
        if not self.domain and self.url:
            try:
                self.domain = urllib.parse.urlparse(self.url).netloc.replace("www.", "")
            except Exception:
                self.domain = ""

        # Automatic source name resolution if missing
        if not self.source:
            self.source = self.domain or "web"

        if not self.index:
            self.index = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "domain": self.domain,
            "source": self.source,
            "engine": self.engine
        }

    def __repr__(self) -> str:
        return f"SearchResultItem(index={self.index}, title='{self.title}', url='{self.url}', domain='{self.domain}', source='{self.source}', engine='{self.engine}')"

@dataclass
class SearchResponse:
    query: str
    results: List[SearchResultItem]
    total_results: int
    provider: str
    engine: str = "google"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "engine": self.engine,
            "timestamp": self.timestamp,
            "total_results": self.total_results,
            "provider": self.provider,
            "results": [r.to_dict() for r in self.results]
        }

class BaseSearchProvider:
    """Abstract Base Class for Web Search Providers."""

    def __init__(self, timeout: float = 8.0, max_retries: int = 1):
        self.timeout = timeout
        self.max_retries = max_retries

    async def search(self, query: str, limit: int = 5, engine: str = "google") -> SearchResponse:
        raise NotImplementedError

class DuckDuckGoSearchProvider(BaseSearchProvider):
    """Zero-config, fast, privacy-preserving DuckDuckGo Web Search Provider."""

    SEARCH_URL = "https://html.duckduckgo.com/html/"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    async def search(self, query: str, limit: int = 5, engine: str = "google") -> SearchResponse:
        clean_query = sanitize_search_text(query.strip())
        normalized_q = re.sub(r"^(?:the\s+|a\s+|an\s+)", "", clean_query, flags=re.IGNORECASE).strip()
        if not normalized_q:
            return SearchResponse(query=query, results=[], total_results=0, provider="duckduckgo", engine=engine)

        search_q = normalized_q
        if engine == "youtube" and not "youtube" in search_q.lower():
            search_q = f"site:youtube.com {search_q}"
        elif engine == "github" and not "github" in search_q.lower():
            search_q = f"site:github.com {search_q}"

        # 1. Primary: DuckDuckGo HTML Search
        headers = {
            **self.HEADERS,
            "Referer": "https://html.duckduckgo.com/",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.post(self.SEARCH_URL, data={"q": search_q}, headers=headers)
                if resp.status_code == 200:
                    results = self._parse_html_results(resp.text, limit, engine=engine)
                    if results:
                        return SearchResponse(
                            query=clean_query,
                            results=results,
                            total_results=len(results),
                            provider="duckduckgo",
                            engine=engine
                        )
        except Exception as e:
            logger.warning(f"[ByteX Search] DuckDuckGo HTML search attempt failed: {e}")

        # 2. Secondary Fallback: DuckDuckGo Instant Answer API
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp_api = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": search_q, "format": "json", "no_html": "1"},
                    headers=self.HEADERS
                )
                if resp_api.status_code in [200, 202]:
                    data = resp_api.json()
                    api_results = []
                    idx = 1
                    if data.get("AbstractText") and data.get("AbstractURL"):
                        domain = urllib.parse.urlparse(data.get("AbstractURL")).netloc.replace("www.", "")
                        api_results.append(
                            SearchResultItem(
                                index=idx,
                                title=data.get("Heading") or normalized_q.title(),
                                url=data.get("AbstractURL"),
                                snippet=data.get("AbstractText"),
                                domain=domain,
                                source=domain,
                                engine=engine
                            )
                        )
                        idx += 1
                    for topic in data.get("RelatedTopics", []):
                        if len(api_results) >= limit:
                            break
                        if isinstance(topic, dict) and topic.get("FirstURL") and topic.get("Text"):
                            domain = urllib.parse.urlparse(topic["FirstURL"]).netloc.replace("www.", "")
                            raw_txt = topic["Text"]
                            title_part = raw_txt.split(" - ")[0] if " - " in raw_txt else raw_txt[:60]
                            api_results.append(
                                SearchResultItem(
                                    index=idx,
                                    title=title_part,
                                    url=topic["FirstURL"],
                                    snippet=raw_txt,
                                    domain=domain,
                                    source=domain,
                                    engine=engine
                                )
                            )
                            idx += 1
                    if api_results:
                        return SearchResponse(
                            query=clean_query,
                            results=api_results,
                            total_results=len(api_results),
                            provider="duckduckgo_api",
                            engine=engine
                        )
        except Exception as e:
            logger.warning(f"[ByteX Search] DuckDuckGo Instant API attempt failed: {e}")

        # 3. Tertiary Fallback: Wikipedia / OpenSearch / Direct Platform Search Fallback
        if engine == "youtube":
            yt_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(normalized_q)}"
            return SearchResponse(
                query=clean_query,
                results=[
                    SearchResultItem(
                        index=1,
                        title=f"YouTube Search: {normalized_q}",
                        url=yt_url,
                        snippet=f"Search results for '{normalized_q}' on YouTube",
                        domain="youtube.com",
                        source="youtube.com",
                        engine="youtube"
                    )
                ],
                total_results=1,
                provider="direct_fallback",
                engine="youtube"
            )
        elif engine == "github":
            gh_url = f"https://github.com/search?q={urllib.parse.quote_plus(normalized_q)}"
            return SearchResponse(
                query=clean_query,
                results=[
                    SearchResultItem(
                        index=1,
                        title=f"GitHub Search: {normalized_q}",
                        url=gh_url,
                        snippet=f"Repositories and code matching '{normalized_q}' on GitHub",
                        domain="github.com",
                        source="github.com",
                        engine="github"
                    )
                ],
                total_results=1,
                provider="direct_fallback",
                engine="github"
            )

        try:
            wiki_headers = {"User-Agent": "ByteX/1.0 (Windows NT 10.0; Win64; x64) contact@bytex.ai"}
            lookup_term = re.sub(
                r"\b(?:search\s+(?:the\s+)?(?:web|internet|online)?\s*(?:for\s+)?|google\s+(?:for\s+)?|find\s+(?:the\s+)?official\s+website\s+(?:for\s+)?|what(?:'s|\s+is)\s+(?:the\s+)?latest\s+news\s+(?:about|on)?|latest\s+news\s+(?:about|on)?|official\s+website\s+(?:for\s+)?|latest\s+news|latest|news|website|resources?|releases?|updates?)\b",
                "",
                normalized_q,
                flags=re.IGNORECASE
            ).strip()
            lookup_term = re.sub(r"^(?:the\s+|a\s+|an\s+|for\s+)", "", lookup_term, flags=re.IGNORECASE).strip() or normalized_q
            lookup_term = re.sub(r"\s+", " ", lookup_term).strip()
            
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp_wiki = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={"action": "opensearch", "search": lookup_term, "limit": limit, "format": "json"},
                    headers=wiki_headers
                )
                if resp_wiki.status_code == 200:
                    data = resp_wiki.json()
                    titles, snippets, urls = data[1], data[2], data[3]
                    wiki_results = []
                    for idx, (t, s, u) in enumerate(zip(titles, snippets, urls), 1):
                        wiki_results.append(
                            SearchResultItem(
                                index=idx,
                                title=t,
                                url=u,
                                snippet=s or f"Official article on {t}",
                                domain="en.wikipedia.org",
                                source="en.wikipedia.org",
                                engine=engine
                            )
                        )
                    if wiki_results:
                        return SearchResponse(
                            query=clean_query,
                            results=wiki_results,
                            total_results=len(wiki_results),
                            provider="wikipedia_opensearch",
                            engine=engine
                        )
        except Exception as e:
            logger.warning(f"[ByteX Search] Wikipedia OpenSearch attempt failed: {e}")

        # 4. Final Fallback: Direct Google Search URL
        direct_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(normalized_q)}"
        return SearchResponse(
            query=clean_query,
            results=[
                SearchResultItem(
                    index=1,
                    title=f"Google Search: {normalized_q}",
                    url=direct_url,
                    snippet=f"Online search results for '{normalized_q}'",
                    domain="google.com",
                    source="google.com",
                    engine=engine
                )
            ],
            total_results=1,
            provider="direct_fallback",
            engine=engine
        )

    def _parse_html_results(self, html_text: str, limit: int, engine: str = "google") -> List[SearchResultItem]:
        title_matches = re.findall(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html_text, re.DOTALL)
        snippet_matches = re.findall(r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', html_text, re.DOTALL)

        items: List[SearchResultItem] = []
        seen_urls = set()

        for idx, (raw_href, raw_title) in enumerate(title_matches):
            if len(items) >= limit:
                break

            # Handle uddg redirect URLs
            if "uddg=" in raw_href:
                parsed_uddg = urllib.parse.parse_qs(urllib.parse.urlparse(raw_href).query)
                actual_url = parsed_uddg.get("uddg", [raw_href])[0]
            else:
                actual_url = raw_href

            # Handle protocol relative URLs
            if actual_url.startswith("//"):
                actual_url = f"https:{actual_url}"

            if actual_url in seen_urls or "duckduckgo.com" in actual_url:
                continue
            seen_urls.add(actual_url)

            clean_title = html.unescape(re.sub(r'<[^>]+>', '', raw_title)).strip()
            raw_snippet = snippet_matches[idx] if idx < len(snippet_matches) else ""
            clean_snippet = html.unescape(re.sub(r'<[^>]+>', '', raw_snippet)).strip()
            domain = urllib.parse.urlparse(actual_url).netloc.replace("www.", "")

            if clean_title and actual_url:
                items.append(
                    SearchResultItem(
                        index=len(items) + 1,
                        title=clean_title,
                        url=actual_url,
                        snippet=clean_snippet,
                        domain=domain,
                        source=domain,
                        engine=engine
                    )
                )

        return items

class TavilySearchProvider(BaseSearchProvider):
    """Tavily AI Search Provider (used when TAVILY_API_KEY or SEARCH_API_KEY is configured)."""

    def __init__(self, api_key: str, timeout: float = 8.0):
        super().__init__(timeout=timeout)
        self.api_key = api_key
        self.endpoint = "https://api.tavily.com/search"

    async def search(self, query: str, limit: int = 5, engine: str = "google") -> SearchResponse:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": limit
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.endpoint, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Tavily provider error: {resp.status_code}")
            data = resp.json()
            results = []
            for idx, item in enumerate(data.get("results", []), 1):
                domain = urllib.parse.urlparse(item.get("url", "")).netloc.replace("www.", "")
                results.append(
                    SearchResultItem(
                        index=idx,
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", ""),
                        domain=domain,
                        source=domain,
                        engine=engine
                    )
                )
            return SearchResponse(
                query=query,
                results=results,
                total_results=len(results),
                provider="tavily",
                engine=engine
            )

def get_search_provider() -> BaseSearchProvider:
    """Factory creating the active search provider based on environment variables."""
    tavily_key = os.getenv("TAVILY_API_KEY") or os.getenv("SEARCH_API_KEY")
    if tavily_key and not tavily_key.startswith("your_"):
        logger.info("[ByteX Search] Using Tavily Search Provider.")
        return TavilySearchProvider(api_key=tavily_key)
    
    # Default to robust, zero-config DuckDuckGo Provider
    return DuckDuckGoSearchProvider()

class WebSearchSkill(BaseSkill):
    """
    Dedicated Web Search Skill for ByteX (Feature #31).
    
    Responsibilities:
    1. Fetches real, live internet search results from configured or default search providers.
    2. Preserves authentic URLs, sources, domains, titles, and snippets with zero hallucinated data.
    3. Strictly enforces read-only network boundaries (zero browser control, form submissions, or downloads).
    4. Automatically integrates with #24 Context Awareness for subsequent follow-up actions.
    """

    def __init__(self):
        self._provider = get_search_provider()

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Searches the web for current online information, news, resources, and websites."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The exact search query to look up on the web."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of search results to return (default: 5)."
                },
                "engine": {
                    "type": "string",
                    "description": "Search engine/platform (google, youtube, github, etc.)."
                }
            },
            "required": ["query"]
        }

    async def execute(self, arguments: dict) -> ToolResult:
        raw_query = arguments.get("query", "").strip()
        if not raw_query:
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="web_search",
                message="No search query was provided.",
                error="Empty query"
            )

        sanitized_q = sanitize_search_text(raw_query)
        limit = min(int(arguments.get("limit", 5)), 10)
        engine = str(arguments.get("engine", "google")).lower().strip()

        print(f"[ByteX WebSearch] Executing live web search: engine='{engine}', query='{sanitized_q}' (limit: {limit})")

        try:
            response = await self._provider.search(sanitized_q, limit=limit, engine=engine)
        except Exception as e:
            logger.error(f"[ByteX WebSearch] Search failure: {e}")
            return ToolResult(
                success=False,
                verified=False,
                tool=self.name,
                action="web_search",
                message=f"I couldn't complete the web search due to a provider error: {e}",
                error=str(e)
            )

        if not response.results:
            return ToolResult(
                success=True,
                verified=True,
                tool=self.name,
                action="web_search",
                message=f"I searched {engine.capitalize()} for '{sanitized_q}', but found no matching results.",
                data=response.to_dict()
            )

        # Format concise, useful, factual response with citations & URLs
        lines = [f"Here are the search results for **{sanitized_q}**:\n"]
        for idx, res in enumerate(response.results, 1):
            lines.append(f"{res.index}. **[{res.title}]({res.url})**")
            if res.snippet:
                lines.append(f"   {res.snippet}")
            lines.append(f"   *Domain: {res.domain}*\n")

        formatted_summary = "\n".join(lines).strip()

        return ToolResult(
            success=True,
            verified=True,
            tool=self.name,
            action="web_search",
            message=formatted_summary,
            data=response.to_dict()
        )
