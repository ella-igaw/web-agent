import time, os
from urllib.parse import urlparse
from ddgs import DDGS
from tavily import TavilyClient

def _sanitize_query(q: str) -> str:
    return " ".join((q or "").replace("\n"," ").split())

def ddg_collect(qs: list, per_query_cap: int, timelimit: str | None = None, progress=lambda e,p:None) -> list:
    items, seen = [], set()
    with DDGS() as ddgs:
        for q in qs:
            q = _sanitize_query(q)
            if not q: continue
            try:
                progress("ddg:query", {"query": q})
                results = list(ddgs.text(q, region="kr-kr", max_results=per_query_cap, timelimit=timelimit))
                for r in results:
                    href = r.get("href")
                    if href and href not in seen:
                        seen.add(href); items.append({"title": r.get("title",""), "url": href, "source": urlparse(href).netloc})
            except Exception as e:
                progress("ddg:error", {"query": q, "error": str(e)})
            time.sleep(0.1)
    return items

def tavily_collect(qs: list, per_query_cap: int, topic: str = "general", progress=lambda e,p:None) -> list:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        progress("tavily:error", {"reason": "API key not found"}); return []
    try:
        client = TavilyClient(api_key=api_key)
        all_results, seen_urls = [], set()
        for q in qs:
            q = _sanitize_query(q)
            if not q: continue
            progress("tavily:query", {"query": q, "topic": topic})
            response = client.search(query=q, search_depth="advanced", topic=topic, max_results=per_query_cap)
            for res in response.get("results", []):
                href = res.get("url")
                if href and href not in seen_urls:
                    seen_urls.add(href)
                    all_results.append({
                        "title": res.get("title",""), "url": href, 
                        "source": urlparse(href).netloc, "content": res.get("content", "")
                    })
        return all_results
    except Exception as e:
        progress("tavily:error", {"query": q, "error": str(e)}); return []

def provider_collect(preferred_provider: str, qs: list, per_query_cap: int, min_keep_threshold: int, timelimit: str | None = None, topic: str = "general", progress=lambda e,p:None) -> list:
    def _merge(primary, secondary):
        seen_urls = {item['url'] for item in primary}
        for item in secondary:
            if item['url'] not in seen_urls: primary.append(item)
        return primary

    primary_results = []
    if preferred_provider == "tavily" and os.environ.get("Tavily_API_KEY"):
        primary_results = tavily_collect(qs, per_query_cap, topic, progress)
        if len(primary_results) < min_keep_threshold:
            progress("provider:fallback", {"from": "tavily", "to": "ddg"})
            secondary_results = ddg_collect(qs, per_query_cap, timelimit, progress)
            return _merge(primary_results, secondary_results)
    else:
        primary_results = ddg_collect(qs, per_query_cap, timelimit, progress)
    return primary_results