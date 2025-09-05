# modules/utils.py
import re, json, hashlib, requests, random
from urllib.parse import urlparse, urljoin
from typing import Dict
from bs4 import BeautifulSoup
import trafilatura
from trafilatura.settings import use_config
from config import BASE_HEADERS, USER_AGENTS, SNS_DOMAINS, INDUSTRY_ALLOW, COMMON_ALLOW, COMMON_BLOCK, SOCIAL_PATTERNS


def get_random_headers() -> dict:
    headers= BASE_HEADERS.copy()
    headers["User-Agent"] = random.choice(USER_AGENTS)
    return headers

def fetch(url: str, timeout=25) -> requests.Response:
    r = requests.get(url, headers=get_random_headers(), timeout=timeout, allow_redirects=True)
    r.raise_for_status()

  #  r.encoding = 'utf-8'

    if r.encoding == "ISO-8859-1":
        detected_encoding = r.apparent_encoding 
        
        if detected_encoding:
            
            r.encoding = detected_encoding 
        else:
            r.encoding = 'utf-8'
            
    
    return r

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

_TRF = use_config()
_TRF.set("DEFAULT", "USER_AGENT", get_random_headers()["User-Agent"])
_TRF.set("DEFAULT", "MIN_EXTRACTED_SIZE", "120")

def extract_text(html: str) -> str:
    try:
        txt = trafilatura.extract(html, config=_TRF, favor_recall=True, target_language="ko")
        if txt and len(txt) > 150:
            return txt.strip()
    except Exception:
        pass
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)

def _score_url_for_crawl(u: str, industry: str) -> float:
    p = urlparse(u); path = (p.path or "/").lower()
    sc = 0.0
    if any(d in p.netloc.lower() for d in SNS_DOMAINS): return 3.0
    if any(b in path for b in COMMON_BLOCK): sc -= 1.0
    allow = COMMON_ALLOW + INDUSTRY_ALLOW.get(industry.split("/")[0].strip(), [])
    if any(a in path for a in allow): sc += 1.2
    return sc

def extract_socials_from_html(html: str) -> Dict[str, Dict[str,str]]:
    soup = BeautifulSoup(html, "lxml")
    prof={}
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        for plat, rx in SOCIAL_PATTERNS.items():
            m=re.search(rx, href, re.I)
            if m:
                prof.setdefault(plat, {"url": href, "handle": m.group(1)})
    return prof
