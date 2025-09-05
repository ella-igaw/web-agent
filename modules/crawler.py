# modules/crawler.py
import time
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from modules.utils import fetch, _score_url_for_crawl, extract_socials_from_html, _clean, extract_text

def crawl_site(seed_url: str, industry: str, max_pages=30, progress=lambda e,p:None) -> list:
    seed_url = seed_url.rstrip("/")
    parsed = urlparse(seed_url); base = f"{parsed.scheme}://{parsed.netloc}"
    
    queue = [seed_url]
    seen=set(); pages=[]
    
    while queue and len(pages) < max_pages:
        u = queue.pop(0)
        if u in seen: continue
        seen.add(u)
        if not u.startswith(base): continue
        
        try:
            r = fetch(u); html = r.text; text = extract_text(html)
            pages.append({"url": u, "text": _clean(text), "html": html})
            progress("crawl:page", {"url": u, "pages_found": len(pages)})

            soup = BeautifulSoup(html, "lxml")
            nexts=[]
            for a in soup.select("a[href]"):
                nxt_url = urljoin(u, a["href"]).split("#")[0]
                if nxt_url.startswith(base) and nxt_url not in seen:
                    nexts.append(nxt_url)
            
            nexts = sorted(set(nexts), key=lambda uu: _score_url_for_crawl(uu, industry), reverse=True)
            queue.extend(nexts[:10])
            time.sleep(0.05)
        except Exception as e:
            progress("crawl:error", {"url": u, "error": str(e)})

    progress("crawl:done", {"count": len(pages)})
    return pages
