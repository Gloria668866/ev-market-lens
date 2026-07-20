"""Pre-defined tools for oh-my-openagent pipeline agents.

Code agents call these via function calling — they never generate executable code.
Each tool is a pure Python function with a defined JSON schema for LLM consumption.
"""
import json
import logging
import re
import threading
import time
from typing import Any
from urllib.parse import urlparse

import ssl

import httpx

from .config import AGENTS_CONFIG_PATH

_log = logging.getLogger("cheshijing.agent_tools")

# Default timeout and headers for HTTP requests
_DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
_DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

# Use Windows system CA store — handles corporate SSL interception transparently
_SSL_CONTEXT = ssl.create_default_context()

# Per-domain rate limiter (prevents IP ban from aggressive crawling)
_domain_last_call: dict[str, float] = {}
_DOMAIN_MIN_INTERVAL = 3.0


def _rate_limit_domain(domain: str):
    """Enforce per-domain rate limit. Blocks if called too soon."""
    last = _domain_last_call.get(domain, 0)
    elapsed = time.time() - last
    if elapsed < _DOMAIN_MIN_INTERVAL:
        time.sleep(_DOMAIN_MIN_INTERVAL - elapsed)
    _domain_last_call[domain] = time.time()


def _tool_http_get(url: str, **kwargs) -> dict:
    """Fetch a web page. Returns text content and metadata."""
    parsed = urlparse(url)
    if parsed.hostname:
        _rate_limit_domain(parsed.hostname)
    # Validate URL before making request
    if parsed.scheme not in ("http", "https"):
        return {"status": "failed", "error": f"Blocked URL scheme: {parsed.scheme}", "url": url}
    # Block private/internal IPs
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return {"status": "failed", "error": "Blocked: internal host", "url": url}
    if hostname.startswith("169.254.") or hostname.startswith("10.") or hostname.startswith("172.16."):
        return {"status": "failed", "error": "Blocked: private IP range", "url": url}
    if hostname.startswith("192.168."):
        return {"status": "failed", "error": "Blocked: private IP range", "url": url}
    try:
        resp = httpx.get(url, timeout=_DEFAULT_TIMEOUT, headers=_DEFAULT_HEADERS,
                        follow_redirects=True, verify=_SSL_CONTEXT)
        content = resp.text[:50000]  # truncate to 50KB to avoid overwhelming LLM context
        return {
            "status": "success" if 200 <= resp.status_code < 300 else "failed",
            "status_code": resp.status_code,
            "content": content,
            "content_type": resp.headers.get("content-type", "unknown"),
            "url": str(resp.url),  # final URL after redirects
        }
    except httpx.TimeoutException:
        return {"status": "failed", "error": "Request timeout after 15s", "url": url}
    except Exception as e:
        return {"status": "failed", "error": str(e)[:200], "url": url}


def _tool_search_web(query: str, num_results: int = 5, **kwargs) -> dict:
    """Search the web using Baidu (best for Chinese auto data) + Bing as fallback.
    Returns titles, URLs, and snippets."""
    num_results = min(num_results, 10)

    # Strategy 1: Baidu search (best for Chinese content, has AI summaries with data)
    try:
        results = _baidu_search(query, num_results)
        if results:
            return {
                "status": "success",
                "query": query,
                "source": "baidu",
                "results": results,
                "total_found": len(results),
            }
    except Exception as e:
        _log.warning("Baidu search failed: %s", e)

    # Strategy 2: Bing HTML search
    try:
        results = _bing_html_search(query, num_results)
        if results:
            return {
                "status": "success",
                "query": query,
                "source": "bing",
                "results": results,
                "total_found": len(results),
            }
    except Exception as e:
        _log.warning("Bing HTML search failed: %s", e)

    return {"status": "failed", "error": "All search strategies failed", "query": query}


def _baidu_search(query: str, num_results: int = 5) -> list:
    """Parse Baidu search results. Extracts AI summaries and regular results."""
    resp = httpx.get("https://www.baidu.com/s", params={"wd": query},
                     headers=_DEFAULT_HEADERS, timeout=_DEFAULT_TIMEOUT,
                     follow_redirects=True, verify=_SSL_CONTEXT)
    if resp.status_code != 200:
        return []
    html = resp.text
    results = []

    # Extract data-rich text: strip all HTML, find sentences with numbers/keywords
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&nbsp;', ' ').replace('&#183;', '·')
    text = re.sub(r'&#\d+;', '', text)
    text = re.sub(r'\s+', ' ', text)

    # Find data-bearing sentences (contain numbers + auto keywords)
    data_keywords = ['万辆', '万台', '销量', '同比', '环比', '增长', '下滑', '交付', '累计', '%']
    sentences = re.split(r'[。！\n]', text)
    data_snippets = []
    for s in sentences:
        s = s.strip()
        if len(s) < 15 or len(s) > 300:
            continue
        if any(kw in s for kw in data_keywords) and re.search(r'\d', s):
            data_snippets.append(s)

    # If we found data sentences, combine them as a "AI summary" result
    if data_snippets:
        combined = "。".join(data_snippets[:8])
        results.append({
            "title": f"百度AI摘要: {query}",
            "url": f"https://www.baidu.com/s?wd={query}",
            "snippet": combined[:1000],
        })

    # Also extract regular search result blocks
    blocks = re.findall(r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
    for block in blocks[:num_results]:
        title_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
        if not title_match:
            continue
        url = title_match.group(1)
        title = re.sub(r'<[^>]+>', '', title_match.group(2)).strip()
        if not title or len(title) < 3:
            continue
        # Get snippet text from the block
        block_text = re.sub(r'<[^>]+>', ' ', block)
        block_text = re.sub(r'\s+', ' ', block_text).strip()
        snippet = block_text[len(title):].strip()[:500]
        if len(snippet) > 20:
            results.append({"title": title[:100], "url": url, "snippet": snippet})

    return results[:num_results]


def _bing_html_search(query: str, num_results: int = 5) -> list:
    """Parse Bing search results page directly."""
    resp = httpx.get("https://www.bing.com/search", params={"q": query, "count": str(num_results)},
                     headers=_DEFAULT_HEADERS, timeout=_DEFAULT_TIMEOUT,
                     follow_redirects=True, verify=_SSL_CONTEXT)
    if resp.status_code != 200:
        return []
    html = resp.text
    results = []
    # Extract search result blocks: <li class="b_algo">
    blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL)
    for block in blocks[:num_results]:
        # Title and URL
        title_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
        if not title_match:
            continue
        url = title_match.group(1)
        title = re.sub(r'<[^>]+>', '', title_match.group(2))
        # Snippet: try multiple patterns to get as much text as possible
        snippet_parts = []
        for p_match in re.finditer(r'<p[^>]*>(.*?)</p>', block, re.DOTALL):
            text = re.sub(r'<[^>]+>', '', p_match.group(1)).strip()
            if text and len(text) > 10:
                snippet_parts.append(text)
        # Also check <span> tags inside caption area
        for span_match in re.finditer(r'<span[^>]*>(.*?)</span>', block, re.DOTALL):
            text = re.sub(r'<[^>]+>', '', span_match.group(1)).strip()
            if text and len(text) > 30 and text not in " ".join(snippet_parts):
                snippet_parts.append(text)
        snippet = " ".join(snippet_parts) if snippet_parts else ""
        snippet = snippet.replace("&nbsp;", " ").replace("&#183;", "·").replace("&ensp;", " ")
        snippet = re.sub(r'&#\d+;', '', snippet)[:800]
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


_STEALTH_JS = """\
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
window.navigator.chrome={runtime:{}};
Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
Object.defineProperty(navigator,'languages',{get:()=>['zh-CN','zh','en-US','en']});
Object.defineProperty(document,'hidden',{get:()=>false});
Object.defineProperty(document,'visibilityState',{get:()=>'visible'});
"""

_STEALTH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-ipc-flooding-protection",
    "--force-color-profile=srgb",
    "--mute-audio",
    "--disable-features=OptimizationHints,MediaRouter",
    "--disable-component-update",
    "--disable-domain-reliability",
]

_UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def _tool_browser_fetch(url: str, wait_for: str = "", **kwargs) -> dict:
    """Fetch a web page using a stealth browser (Playwright).
    Handles anti-bot sites like 懂车帝, 汽车之家, etc."""
    import asyncio
    import random

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"status": "failed", "error": f"Blocked URL scheme: {parsed.scheme}", "url": url}
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return {"status": "failed", "error": "Blocked: internal host", "url": url}

    # Try crawl4ai first (full anti-bot stack), then fall back to raw playwright
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
        return _browser_fetch_crawl4ai(url, wait_for)
    except ImportError:
        pass

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        _log.warning("Neither crawl4ai nor playwright installed, falling back to httpx")
        return _tool_http_get(url)

    async def _do_fetch():
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                channel="msedge",
                args=_STEALTH_ARGS,
            )
            context = await browser.new_context(
                user_agent=random.choice(_UA_LIST),
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )
            page = await context.new_page()
            await page.add_init_script(_STEALTH_JS)

            try:
                resp = await page.goto(url, wait_until="networkidle", timeout=30000)
                # Wait for dynamic content
                if wait_for:
                    try:
                        await page.wait_for_selector(wait_for, timeout=10000)
                    except Exception:
                        pass
                await page.wait_for_timeout(2500)

                status_code = resp.status if resp else 0
                # Extract visible text (more accurate than regex HTML stripping)
                try:
                    text = await page.inner_text('body')
                    text = re.sub(r'\s+', ' ', text).strip()[:50000]
                except Exception:
                    content = await page.content()
                    text = re.sub(r'<script[^>]*>.*?</script>', ' ', content, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()[:50000]

                return {
                    "status": "success" if 200 <= status_code < 400 else "failed",
                    "status_code": status_code,
                    "content": text,
                    "content_type": "text/plain",
                    "url": page.url,
                    "method": "playwright_stealth",
                }
            finally:
                await browser.close()

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                return pool.submit(lambda: asyncio.run(_do_fetch())).result(timeout=60)
        else:
            return asyncio.run(_do_fetch())
    except Exception as e:
        _log.error("browser_fetch failed: %s", e)
        return {"status": "failed", "error": str(e)[:200], "url": url, "method": "playwright_stealth"}


def _browser_fetch_crawl4ai(url: str, wait_for: str = "") -> dict:
    """Use crawl4ai's full anti-bot stack (preferred when available)."""
    import asyncio
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

    browser_cfg = BrowserConfig(
        headless=True,
        browser_type="chromium",
        user_agent_mode="random",
        text_mode=True,
    )

    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        wait_until="domcontentloaded",
        delay_before_return_html=1.5,
        page_timeout=30000,
        word_count_threshold=10,
    )
    if wait_for:
        run_cfg.wait_for = f"css:{wait_for}"

    async def _do_crawl():
        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            return await crawler.arun(url, config=run_cfg)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            result = pool.submit(lambda: asyncio.run(_do_crawl())).result(timeout=60)
    else:
        result = asyncio.run(_do_crawl())

    if result.success:
        content = (result.markdown or result.cleaned_html or "")[:50000]
        return {
            "status": "success",
            "content": content,
            "content_type": "text/markdown",
            "url": str(result.url) if hasattr(result, 'url') else url,
            "method": "crawl4ai_stealth",
        }
    else:
        return {
            "status": "failed",
            "error": getattr(result, 'error_message', 'Unknown crawl error')[:200],
            "url": url,
            "method": "crawl4ai_stealth",
        }


def _tool_dongchedi_rank(month: str = "", energy_type: str = "", brand_id: str = "",
                          count: int = 20, **kwargs) -> dict:
    """Fetch car sales ranking from dongchedi internal API. No login required.
    month: format YYYY-MM (e.g. '2025-06'). Empty = latest.
    energy_type: '' (all) | '1' (BEV) | '2' (PHEV) | '3' (EREV)
    brand_id: dongchedi brand ID, empty = all brands."""
    _rate_limit_domain("dongchedi.com")
    try:
        params = {
            "aid": "1839",
            "app_name": "auto_web_pc",
            "count": str(min(count, 100)),
            "month": month,
            "new_energy_type": energy_type,
            "rank_data_type": "11",
            "brand_id": brand_id,
            "offset": "0",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://www.dongchedi.com/ranking/pin/month/energy_all",
        }
        resp = httpx.get(
            "https://www.dongchedi.com/motor/pc/car/rank_data",
            params=params, headers=headers, timeout=_DEFAULT_TIMEOUT,
            follow_redirects=True, verify=_SSL_CONTEXT,
        )
        if resp.status_code != 200:
            return {"status": "failed", "error": f"HTTP {resp.status_code}", "source": "dongchedi_api"}

        data = resp.json()
        if data.get("status") != 0:
            return {"status": "failed", "error": data.get("message", "unknown"), "source": "dongchedi_api"}

        items = data.get("data", {}).get("list", [])
        results = []
        for item in items:
            results.append({
                "rank": item.get("rank"),
                "series_name": item.get("series_name"),
                "sales_count": item.get("count"),
                "min_price": item.get("min_price"),
                "max_price": item.get("max_price"),
                "last_rank": item.get("last_rank"),
            })

        return {
            "status": "success",
            "source": "dongchedi_api",
            "month": month or "latest",
            "total_results": len(results),
            "has_more": data.get("data", {}).get("paging", {}).get("has_more", False),
            "results": results,
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)[:200], "source": "dongchedi_api"}


def _tool_parse_html(html: str, **kwargs) -> dict:
    """Extract readable text from HTML. Strips scripts, styles, and boilerplate.
    Uses regex for lightweight extraction — no full DOM parser needed."""
    if not html or not html.strip():
        return {"status": "failed", "error": "empty input", "text": ""}
    try:
        # Remove script and style blocks
        cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        # Decode common entities
        cleaned = cleaned.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        cleaned = cleaned.replace("&quot;", '"').replace("&#39;", "'")
        # Collapse whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Trim to reasonable length
        cleaned = cleaned[:20000]
        return {"status": "success", "text": cleaned, "char_length": len(cleaned)}
    except Exception as e:
        return {"status": "failed", "error": str(e)[:200], "text": ""}


def _tool_write_to_rag(title: str, content: str, source_url: str = "", **kwargs) -> dict:
    """Write collected content into the RAG knowledge base as a public document (user_id=0).
    Uses the existing local_ingest pipeline (chunk → embed → store)."""
    try:
        # Construct a markdown document from the collected data
        md_lines = [f"# {title}", "", f"> 数据来源：{source_url}", "", content]
        md_text = "\n".join(md_lines)

        filename = f"agent_collected_{int(time.time())}.md"
        doc_id, chunk_count = ingest_text_as_document(
            title=title,
            text=md_text,
            filename=filename,
            source_url=source_url,
        )
        return {
            "status": "success",
            "doc_id": doc_id,
            "chunk_count": chunk_count,
            "title": title,
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)[:200], "title": title}


# ── Tool registry ─────────────────────────────────────────────────────────────

ALL_TOOLS: dict[str, callable] = {
    "http_get": _tool_http_get,
    "browser_fetch": _tool_browser_fetch,
    "dongchedi_rank": _tool_dongchedi_rank,
    "search_web": _tool_search_web,
    "parse_html": _tool_parse_html,
    "write_to_rag": _tool_write_to_rag,
}

# OpenAI function-calling JSON schemas
TOOL_SCHEMAS: dict[str, dict] = {
    "http_get": {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": "Fetch content from a web URL. Returns page text and metadata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to fetch (include https://)"},
                },
                "required": ["url"],
            },
        },
    },
    "browser_fetch": {
        "type": "function",
        "function": {
            "name": "browser_fetch",
            "description": "Fetch a web page using stealth browser (defeats anti-bot). Use for sites that block normal HTTP (汽车之家, 乘联会). Slower than http_get but bypasses anti-crawl. NOTE: for 懂车帝 sales data, use dongchedi_rank instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to fetch (include https://)"},
                    "wait_for": {"type": "string", "description": "Optional CSS selector to wait for before extracting content"},
                },
                "required": ["url"],
            },
        },
    },
    "dongchedi_rank": {
        "type": "function",
        "function": {
            "name": "dongchedi_rank",
            "description": "Get car sales ranking data from 懂车帝 (dongchedi). Returns structured JSON with rank, model name, sales count, price range. Fast and reliable — no login needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "string", "description": "Month in YYYY-MM format (e.g. '2025-06'). Empty for latest month."},
                    "energy_type": {"type": "string", "description": "Filter: '' (all cars), '1' (BEV pure electric), '2' (PHEV plug-in hybrid), '3' (EREV range extender)"},
                    "brand_id": {"type": "string", "description": "Dongchedi brand ID to filter. Empty for all brands."},
                    "count": {"type": "integer", "description": "Number of results (default 20, max 100)"},
                },
                "required": [],
            },
        },
    },
    "search_web": {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for information. Returns titles, URLs, and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in Chinese or English"},
                    "num_results": {"type": "integer", "description": "Number of results (default 5, max 10)"},
                },
                "required": ["query"],
            },
        },
    },
    "parse_html": {
        "type": "function",
        "function": {
            "name": "parse_html",
            "description": "Extract readable text from raw HTML. Strips scripts, styles, and tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "html": {"type": "string", "description": "Raw HTML content to parse"},
                },
                "required": ["html"],
            },
        },
    },
    "write_to_rag": {
        "type": "function",
        "function": {
            "name": "write_to_rag",
            "description": "Write collected content into the knowledge base for future queries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Document title"},
                    "content": {"type": "string", "description": "Full text content to store (markdown)"},
                    "source_url": {"type": "string", "description": "Source URL for traceability"},
                },
                "required": ["title", "content"],
            },
        },
    },
}


def get_tool_definitions(agent_name: str) -> list[dict]:
    """Return OpenAI function-calling tool definitions for an agent.
    Reads tool_permissions from agents.yaml to determine which tools this agent can use."""
    schemas = []
    permissions = _get_tool_permissions(agent_name)
    for tool_name in permissions:
        if tool_name in TOOL_SCHEMAS:
            schemas.append(TOOL_SCHEMAS[tool_name])
    return schemas


def execute_tool(tool_name: str, arguments: dict) -> dict:
    """Execute a tool by name. Returns a dict with at least {"status": "..."}."""
    if tool_name not in ALL_TOOLS:
        return {"status": "error", "error": f"unknown tool '{tool_name}'"}
    try:
        return ALL_TOOLS[tool_name](**arguments)
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}


# ── RAG write helper (reuses existing pipeline) ────────────────────────────────

def ingest_text_as_document(title: str, text: str, filename: str = "agent_collected.md",
                            source_url: str = "", public: bool = True) -> tuple[int, int]:
    """Write a text document through the RAG ingest pipeline.

    Uses local_ingest when RAG_BACKEND=local (default), pg ingest when RAG_BACKEND=pg.
    public=True writes as user_id=None (visible to all users).
    public=False writes as user_id=0 (system user, also public in local_store semantics).
    """
    from .config import RAG_BACKEND

    data = text.encode("utf-8")
    file_type = "md"

    if RAG_BACKEND == "pg":
        from .rag import pg, store, embed
        from .rag.chunk import build_chunks
        from .rag.parse import parse_document

        source_uri = store.put_bytes(0, filename, data, "text/markdown")
        doc_id = pg.create_document(0, filename, file_type, source_uri, title=title)
        blocks = parse_document(data, file_type)
        chunks = build_chunks(blocks, count_tokens=embed.count_tokens)
        children = [c for c in chunks if c["is_retrievable"]]
        vecs = embed.embed_passages([c["content_embed"] for c in children])
        emb_by_idx = {c["chunk_index"]: v for c, v in zip(children, vecs)}
        n = pg.insert_chunks(doc_id, 0, chunks, emb_by_idx)
        pg.set_status(doc_id, "ready", chunk_count=n)
        return doc_id, n
    else:
        # RAG_BACKEND=local — write as public document
        try:
            from .rag.local_ingest import ingest_bytes as local_ingest_bytes
            return local_ingest_bytes(0, filename, data, file_type, title=title, public=True)
        except TypeError:
            # Fallback: older local_ingest might not support public param
            from .rag.local_ingest import ingest_bytes as local_ingest_bytes
            return local_ingest_bytes(0, filename, data, file_type, title=title)


# ── Internal helpers ──────────────────────────────────────────────────────────

_yaml_cfg = None
_yaml_lock = threading.Lock()


def _get_tool_permissions(agent_name: str) -> list[str]:
    """Read tool_permissions from agents.yaml (with caching)."""
    global _yaml_cfg
    import yaml
    from pathlib import Path

    with _yaml_lock:
        if _yaml_cfg is None:
            path = Path(AGENTS_CONFIG_PATH)
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    _yaml_cfg = yaml.safe_load(f) or {}
            else:
                _yaml_cfg = {}
    return (_yaml_cfg.get("tool_permissions") or {}).get(agent_name, [])


def reload_config():
    """Force reload tool permissions config from disk."""
    global _yaml_cfg
    with _yaml_lock:
        _yaml_cfg = None
