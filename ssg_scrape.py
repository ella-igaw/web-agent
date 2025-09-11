# ssg_scrape.py
#!/usr/bin/env python3
import asyncio
import json
import argparse
import contextlib
from typing import List, Dict, Any
from playwright.async_api import async_playwright

# --- 핵심 JS: SSG 검색 카드에서 title / price / brand / rating / review / url / image 추출 ---
JS = r"""
(() => {
  const MAX = %MAX%;

  const q  = (el, sel) => el.querySelector(sel);
  const qq = (el, sel) => Array.from(el.querySelectorAll(sel));
  const txt = el => el ? el.textContent.trim() : "";

  const num = s => {
    if (!s) return null;
    const m = s.replace(/\s/g,"").match(/\d[\d,\.]+/);
    if (!m) return null;
    const v = parseFloat(m[0].replace(/,/g,""));
    return Number.isFinite(v) ? v : null;
  };


const canon = (u) => {
  try {
    if (!u) return "";
    const x = new URL(u, location.href);
    x.hash = "";

    if (x.hostname.endsWith("ssg.com")) {
      // 추적성 파라미터만 제거하고, 나머지는 유지 (특히 itemId 유지)
      const drop = ["NaPm","ckwhere","src_area","srcid","_gd","tr","gd_type"];
      drop.forEach(k => x.searchParams.delete(k));

      // 안전장치: itemId가 없으면 파라미터를 아예 건드리지 않음
      if (!x.searchParams.has("itemId")) {
        return x.href; // 그대로
      }
    }

    return x.href;
  } catch (_) {
    return u || "";
  }
};

  // 카드 후보 래퍼 & 타이틀/브랜드 셀렉터
  const CARD_WRAPS = [
    "li.srchItem","li.cunit_prod","li","article",
    ".cunit","[class*='cunit_']",
    ".chakra-card",".chakra-stack",".chakra-link",
    "div[class*='grid']","div[class*='stack']","div[class*='card']",
    "[data-product]","[data-item]"
  ];
  const TITLE_SELS = [
    "a[title]","img[alt]",
    ".cm_item_tit",".cunit_info_tit",".cunit_tit",
    "p[class*='chakra-text'] span, p[class*='chakra-text']",
    "h1,h2,h3,h4,h5,h6",
    "[class*='title']","[class*='tit']","[class*='name']"
  ];
  const BRAND_SELS = [
    ".cm_mall_text",".mallname",".brand",".cunit_info .mall",".cunit_info .brand",
    ".cm_mall",".mall"
  ];
  const RATING_SELS = [
    "[aria-label*='평점']","[class*='rating']","[class*='rate']","[class*='star']","[class*='score']"
  ];
  const REVIEW_SELS = [
    // 사용자 제보 경로: chakra-stack 내 p:nth-child(4) > span 등
    ".chakra-stack p span",
    "[class*='review']","[class*='rcount']","[class*='cnt']"
  ];

  // ★ 라벨 기반 가격 추출기
const pickPrice = (root) => {
  const LABELS = ["판매가격","즉시할인가","쿠폰","혜택가","최저가","가격"];
  const PRICE_SELS = [
    "em[class*='price']","span[class*='price']","strong[class*='price']",
    ".ssg_price",".org_price",".opt_price",".final_price",".sale_price",
    "[data-price]","em.css-1oiygnj",".css-idkz9h",".css-ffjhre"
  ];
  const cleanNum = (s) => {
    if (!s) return null;
    const m = s.replace(/\s/g,"").match(/\d[\d,\.]+/);
    if (!m) return null;
    const v = parseFloat(m[0].replace(/,/g,""));
    return Number.isFinite(v) && v > 500 ? v : null;
  };

  // (0) "판매가격" 라벨을 포함하는 컨테이너에서, 라벨 텍스트 제거 후 남은 숫자
  const labelNodes = Array.from(root.querySelectorAll("em,span,div,strong,b"))
    .filter(n => LABELS.some(k => (n.textContent||"").includes(k)));
  for (const lab of labelNodes) {
    const cont = lab.closest("em,span,div,strong,b") || lab.parentElement;
    if (cont) {
      const contText = (cont.textContent||"").replace(/\s/g,"");
      const labelText = (lab.textContent||"").replace(/\s/g,"");
      const after = contText.replace(labelText, "");
      const v0 = cleanNum(after);
      if (v0 !== null) return v0;
    }
  }

  // (1) 라벨 다음 **텍스트노드/형제 요소들**을 걸어가며 숫자 찾기
  for (const lab of labelNodes) {
    let node = lab.nextSibling;
    let hops = 0;
    while (node && hops < 8) {
      if (node.nodeType === Node.TEXT_NODE) {
        const v1 = cleanNum(node.textContent || "");
        if (v1 !== null) return v1;
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        const v2 = cleanNum(node.textContent || "");
        if (v2 !== null) return v2;
        for (const el of node.querySelectorAll("span,em,strong,b,[class*='price']")) {
          const v3 = cleanNum(el.textContent || "");
          if (v3 !== null) return v3;
        }
      }
      node = node.nextSibling;
      hops++;
    }
  }

  // (2) 클래스 기반 백업
  for (const s of PRICE_SELS) {
    for (const el of root.querySelectorAll(s)) {
      const v = cleanNum(el.textContent || "");
      if (v !== null) return v;
    }
  }

  // (3) 최종 백업: 카드 전체 텍스트에서 '원' 앞의 가장 큰 숫자
  const all = root.textContent || "";
  const nums = Array.from(all.matchAll(/\d[\d,\.]+(?=\s*원?)/g))
    .map(m => parseFloat(m[0].replace(/,/g,"")))
    .filter(v => Number.isFinite(v) && v > 500)
    .sort((a,b)=>b-a);
  return nums[0] || null;
};

  const getRoot = (a) => {
    let el = a;
    for (let i=0; i<7 && el; i++) {
      for (const sel of CARD_WRAPS) {
        const wrap = el.closest(sel);
        if (wrap && (wrap.querySelector("a[href]") || wrap.querySelector("img[src]"))) return wrap;
      }
      el = el.parentElement;
    }
    return a;
  };

  // 앵커 수집
  let anchors = Array.from(document.querySelectorAll("a[href*='itemView.ssg']"));
  if (!anchors.length) anchors = Array.from(document.querySelectorAll("a.chakra-link[href*='/item/']"));

  const out = [];
  const seen = new Set();

  for (const a of anchors) {
    if (out.length >= MAX) break;
    const root = getRoot(a);

    // title
    let title = a.getAttribute("title") || a.getAttribute("aria-label") || "";
    if (!title) {
      const imgAlt = (root.querySelector("img[alt]")||a.querySelector("img[alt]"));
      title = (imgAlt && imgAlt.getAttribute("alt")) || "";
    }
    if (!title) {
      for (const s of TITLE_SELS) { const t = txt(q(root, s)); if (t) { title = t; break; } }
      if (!title) title = txt(a);
    }

    const url   = canon(a.href);
    const image = (root.querySelector("img[currentSrc], img[src], img[data-src], img[data-original]")?.currentSrc)
               || (root.querySelector("img[src]")?.src)
               || root.querySelector("img[data-src]")?.getAttribute("data-src")
               || root.querySelector("img[data-original]")?.getAttribute("data-original")
               || null;

    const price = pickPrice(root);

    let brand = "";
    for (const s of BRAND_SELS) { const t = txt(q(root, s)); if (t) { brand = t; break; } }
    if (!brand && title) {
      const paren = title.match(/\(([^)]+)\)/);
      brand = paren ? paren[1].trim() : (title.split(/\s|,|-/)[0] || "").trim();
    }
    if (!brand) brand = null;

    const rating_text = (() => {
      for (const s of RATING_SELS) { const t = txt(q(root, s)); if (t) return t; }
      return null;
    })();
    const review_text = (() => {
      // 카드 내부 여러 span 중 “리뷰/건/평” 같은 힌트 포함 텍스트를 우선
      const spans = qq(root, REVIEW_SELS.join(","));
      const cand = spans.map(el => txt(el)).find(t => /리뷰|건|평/.test(t));
      return cand || (spans.length ? txt(spans[0]) : null);
    })();

    const row = {
      title: title || null,
      url,
      image: image || null,
      price: price,
      brand: brand || null,
      rating_text: rating_text || null,
      review_text: review_text || null
    };

    if (row.review_count == null) {
      const m = (root.textContent||"").match(/(\d[\d,\.]*)\s*건/);
      if (m) row.review_count = parseInt(m[1].replace(/,/g,''), 10);
    }

    const rnum = num(row.rating_text); if (rnum !== null) row.rating = rnum;
    const cnum = num(row.review_text); if (cnum !== null) row.review_count = cnum;

    // dedup
    let key = "";
    if (row.url && row.url.includes("itemId=")) key = "id:" + row.url.split("itemId=")[1].split("&")[0];
    else if (row.url) key = "u:" + row.url;
    else key = "t:" + (row.title||"") + "|i:" + (row.image||"");
    if (!seen.has(key)) { seen.add(key); out.push(row); }
  }

  return out.slice(0, MAX);
})();

"""

async def scrape(url: str, max_items: int = 60, headless: bool = True) -> List[Dict[str, Any]]:
  async with async_playwright() as pw:
    browser = await pw.chromium.launch(
      headless=headless,
      args=["--disable-blink-features=AutomationControlled"]
    )
    ctx = await browser.new_context(
      user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"),
      locale="ko-KR",
      timezone_id="Asia/Seoul",
      viewport={"width": 1366, "height": 900}
    )
    # anti-bot 1단계
    await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")

    page = await ctx.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    # lazy-load 유도 + anchor 등장 대기
    for _ in range(10):
      await page.evaluate("window.scrollBy(0, document.body.scrollHeight*0.6);")
      await asyncio.sleep(2)
    with contextlib.suppress(Exception):
      await page.wait_for_selector("a[href*='itemView.ssg'], a.chakra-link[href*='/item/']", timeout=8000)

    items = await page.evaluate(JS.replace("%MAX%", str(max_items)))

    # 디버그 아티팩트
    with contextlib.suppress(Exception):
      await page.screenshot(path="ssg_debug.png", full_page=True)
    with contextlib.suppress(Exception):
      html = await page.content()
      with open("ssg_debug.html", "w", encoding="utf-8") as f:
        f.write(html)

    await browser.close()
    return items
      
import pandas as pd
from collections import defaultdict

def analyze_by_brand(items):
    df = pd.DataFrame(items)

    brand_map = defaultdict(list)
    for _, row in df.iterrows():
        brand = row.get("brand") or "Unknown"
        title = row.get("title") or "No Title"
        brand_map[brand].append(title)

    # 등장 횟수 + 상품명 리스트 출력용
    analysis = {brand: {"count": len(titles), "titles": titles}
                for brand, titles in brand_map.items()}

    return analysis

if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("url", help="SSG 검색 URL (예: https://www.ssg.com/search.ssg?query=헤어드라이어&sort=sale)")
  ap.add_argument("--max", type=int, default=60, help="최대 아이템 수")
  ap.add_argument("--headful", action="store_true", help="브라우저 창 띄워서 확인")
  ap.add_argument("--csv", default="", help="CSV 파일명 (예: out.csv)")
  args = ap.parse_args()

  items = asyncio.run(scrape(args.url, max_items=args.max, headless=not args.headful))
  brand_analysis = analyze_by_brand(items)

  print("items:", len(items))
  for i, r in enumerate(items[:10], 1):
    print(i, r.get("title"), r.get("brand"), r.get("price"), r.get("rating"), r.get("review_count"), r.get("url"))
  # import pandas as pd
  # pd.DataFrame(items).to_csv('out.csv')


  for brand, info in brand_analysis.items():
    print(f"브랜드: {brand} (총 {info['count']}개)")
  for t in info["titles"]:
    print("  -", t)
    
    if args.csv:
        import pandas as pd
        df = pd.DataFrame(items, columns=["title","brand","price","rating","review_count","url","image"])
        df.to_csv(args.csv, index=False, encoding="utf-8-sig")
        print("CSV 저장:", args.csv)
        # import csv
        # fields = ["title","brand","price","rating","review_count","url","image"]
        # with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
        #     w = csv.DictWriter(f, fieldnames=fields)
        #     w.writeheader()
        #     for row in items:
        #         safe_row = {k: row.get(k, "") for k in fields}
        #         w.writerow(safe_row)
        # print("CSV 저장:", args.csv)
