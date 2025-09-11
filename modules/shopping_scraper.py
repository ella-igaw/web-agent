# modules/shopping_scraper.py
import asyncio
import json
import random
import contextlib
import re
from typing import List, Dict, Any
from playwright.async_api import async_playwright
import pandas as pd
from collections import defaultdict
from config import USER_AGENTS

# ssg_scrape.py의 핵심 JS 로직 (최적화 및 안정화 버전)
JS_PAYLOAD = r"""
(() => {
    const MAX = %MAX%;
    
    coonst getText = (el, selectors) => {
    for (const selector of selectors) {
        const node = el.querySelector(selector);
        if (node && node.textContent) return node.textContenct.trim();
        }
        return "";
    };

    const getNumber = (text) => {
        if (!text) return null;
        const match = text.replace(/,|원|%/g, "").match(/\d+/); // 
        return match ? parseInt(match[0], 10) : null;

    };

    const getAttribute = (el, selectors, attr) => {
        for (const selector of selectors) {
            const node = el.querySelector(selector);
            if (node && node.getAttrigute(attr)) return node.getAttribute(attr);
            }
        return "";
     }

     const CARD_SELECTORS = ["li.cunit_prod", "li.cunit_t232",'.cunit_t239", ".cunit_t232_tx"];
     const TITLE_SELECTORS = [".cunit_info .cunit_tit .tx_ko", ".cunit_info .cunit_tit"];
     const PRICE_SELECTORS = [".cunit_price .ssg_price", ".ssg_price"];
     const 
     
     
    
    const q = (el, sel) => el.querySelector(sel);
    const txt = el => el ? el.textContent.trim() : "";
    const num = s => {
        if (!s) return null;
        const m = s.replace(/,|원/g, "").match(/\d+/);
        return match ? parseInt(match[0], 10) : null;
    };
    
    const out = [];
    const seen = new Set();
    const items = document.querySelectorAll("li.cunit_prod");

    for (const item of items) {
        if (out.length >= MAX) break;
        
        const linkEl = q(item, "a.cunit_prod_link");
        const url = linkEl ? new URL(linkEl.href, location.href).href : null;
        if (!url || seen.has(url)) continue;
        seen.add(url);
        
        const title = txt(q(item, ".cunit_info .cunit_tit .tx_ko"));
        const price = num(txt(q(item, ".cunit_price .ssg_price")));
        const brand = txt(q(item, ".cunit_info .cunit_brand"));
        const reviewCount = num(txt(q(item, ".cunit_app .rating_tx .tx_num")));
        const imageUrl = q(item, ".cunit_prod_thumb img")?.src;

        if (title && price) {
            out.push({ title, price, brand, review_count: reviewCount, url, image_url: imageUrl });
        }
    }
    return out;
})();
"""

async def scrape_ssg(url: str, max_items: int = 60, progress=lambda e,p:None) -> List[Dict[str, Any]]:
    progress("ssg_scraper:start", {"url": url})
    async with async_playwright() as pw:
        browser = None
        try:
            browser = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS), locale="ko-KR")
            await context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)"); await page.wait_for_timeout(1500)

            script = JS_PAYLOAD.replace("%MAX%", str(max_items))
            items = await page.evaluate(script)
            
            progress("ssg_scraper:done", {"found_items": len(items)})
            return items
        except Exception as e:
            progress("ssg_scraper:error", {"error": str(e)})
            if 'page' in locals(): await page.screenshot(path="debug_ssg_error.png")
            return [{"error": str(e)}]
        finally:
            if browser: await browser.close()
 
# --- 핵심 JS: 파트너께서 찾아주신 '족집게' 선택자를 탑재한 최종 버전 ---
JS_PAYLOAD_NAVER = r"""
(() => {
    const MAX_ITEMS = %MAX%;

    // --- 유틸리티 함수 ---
    const getText = (el, selector) => {
        const node = el.querySelector(selector);
        return node ? node.textContent.trim() : "";
    };
    const getNumber = (text) => {
        if (!text) return null;
        // 리뷰 수에 '만+' 같은 문자가 포함될 수 있으므로, 숫자와 점만 추출
        const match = text.replace(/,|원/g, "").match(/[\d\.]+/);
        if (!match) return null;
        let num = parseFloat(match[0]);
        if (text.includes('만')) num *= 10000;
        return Math.round(num);
    };
    const getAttribute = (el, selector, attr) => {
        const node = el.querySelector(selector);
        return node ? node.getAttribute(attr) : "";
    };

    // --- 데이터 수집 ---
    // 네이버 쇼핑에서 상품 카드 하나하나를 가리키는 가장 안정적인 외부 컨테이너
    const productItems = document.querySelectorAll("div[class^='product_item_inner__']");
    const results = [];

    for (const item of productItems) {
        if (results.length >= MAX_ITEMS) break;

        // 파트너께서 찾아주신 '정답' 선택자들을 여기에 그대로 사용합니다.
        // [class*='...'] 와일드카드를 사용하여 뒤에 붙는 무작위 문자열에 대응합니다.
        const url = getAttribute(item, "a[class*='miniProductCard_link__']", "href");
        const imageUrl = getAttribute(item, "img[class*='autoFitImg_auto_fit_img__']", "src");
        const title = getText(item, "[class*='productCardTitle_product_card_title__']");
        const price = getNumber(getText(item, "[class*='priceTag_original_price__']"));
        
        // 리뷰 수는 보통 '리뷰'라는 텍스트와 함께 표시됩니다.
        let reviewCount = 0;
        const reviewElement = item.querySelector("[class*='productCardReview_text__']");
        if (reviewElement) {
            reviewCount = getNumber(reviewElement.textContent);
        }

        if (title && price && url) {
            results.push({
                title: title,
                price: price,
                review_count: reviewCount || 0,
                url: url,
                image_url: imageUrl
            });
        }
    }
    return results;
})();
"""

async def scrape_naver_shopping_with_js(query: str, sort_method: str = "REVIEW", top_n: int = 20, progress=lambda e,p:None) -> List[Dict[str, any]]:
    """
    Playwright와 '정밀 타겟팅' JS를 사용하여 네이버 쇼핑 검색 결과를 스크레이핑합니다.
    """
    products = []
    encoded_query = re.sub(r'\s+', '+', query)
    url = f"https://search.shopping.naver.com/search/all?sort={sort_method}&query={encoded_query}"
    progress("naver_scraper:start", {"url": url})

    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS), locale="ko-KR")
            await context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page = await context.new_page()

            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            script_with_max = JS_PAYLOAD_NAVER.replace("%MAX%", str(top_n))
            scraped_data = await page.evaluate(script_with_max)
            
            for i, item in enumerate(scraped_data):
                item["rank"] = i + 1
                products.append(item)
        
        except Exception as e:
            progress("naver_scraper:error", {"error": str(e)})
            if 'page' in locals(): await page.screenshot(path="debug_naver_error.png")
            return [{"error": str(e)}]
        
        finally:
            if browser: await browser.close()

    progress("naver_scraper:done", {"found_items": len(products)})
    return products


from .auto_analyzer import analyze_layout_and_get_selectors
from .utils import fetch # HTML을 가져오기 위해 fetch 함수 import


async def scrape_any_site_with_ai(url: str, user_hint: str, progress) -> List[Dict[str, Any]]:
    """
    1. Playwright로 사이트에 안전하게 접근하여 HTML을 확보하고,
    2. AI가 사이트 구조를 분석하여 선택자를 생성한 뒤,
    3. 동일한 Playwright 세션에서 즉시 데이터를 스크레이핑하는 범용 스크레이퍼.
    """
    progress("universal_scraper:start", {"url": url})
    
    # ===== 변경점: 작전의 시작부터 끝까지 하나의 Playwright 세션을 사용 =====
    async with async_playwright() as p:
        browser = None
        try:
            # 1. Playwright로 위장하여 목표 사이트에 안전하게 접근
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=random.choice(USER_AGENTS), locale="ko-KR")
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # 2. '살아있는' 페이지의 최종 HTML을 확보
            html_content = await page.content()
            if not html_content:
                raise ValueError("Failed to retrieve HTML content from the page.")

            # 3. AI 두뇌 호출: 확보한 HTML을 분석하여 설계도(선택자) 생성
            progress("universal_scraper:analyzing_layout", {"message": "AI is learning the website structure..."})
            selectors = analyze_layout_and_get_selectors(html_content, user_hint)
            
            if "error" in selectors or not selectors.get("list_item_selector"):
                progress("universal_scraper:error", {"reason": "AI failed to generate selectors", "details": selectors})
                return [{"error": "AI failed to generate selectors", "details": selectors}]
            
            progress("universal_scraper:selectors_generated", {"selectors": selectors})
            
            # 4. AI가 만든 설계도를 사용하여 '이미 열려있는 페이지'에서 즉시 데이터 수집
            list_selector = selectors["list_item_selector"]
            field_selectors = selectors["fields"]
            
            items = await page.query_selector_all(list_selector)
            results = []
            for item in items:
                data = {}
                for field_name, selector in field_selectors.items():
                    if not selector: continue
                    element = await item.query_selector(selector)
                    if element:
                        if field_name in ["url", "image_url"]:
                            attr = "href" if field_name == "url" else "src"
                            value = await element.get_attribute(attr)
                            if value and not value.startswith('http'):
                                value = urlparse(url)._replace(path=value).geturl()
                            data[field_name] = value
                        else:
                            data[field_name] = (await element.text_content()).strip()
                if data: # 비어있지 않은 데이터만 추가
                    results.append(data)
            
            progress("universal_scraper:done", {"found_items": len(results)})
            return results
        except Exception as e:
            progress("universal_scraper:error", {"reason": "Playwright execution failed", "error": str(e)})
            return [{"error": f"Playwright execution failed: {e}"}]
        finally:
            if browser: await browser.close()
    
def analyze_by_brand(items: List[Dict[str, Any]]) -> dict:
    if not items or "error" in items[0]: return {}
    brand_counts = defaultdict(int)
    for item in items:
        # 네이버 쇼핑은 상품명에 브랜드가 포함된 경우가 많으므로, 제목에서 브랜드를 추측합니다.
        brand = item.get("title", "브랜드 없음").split(" ")[0]
        brand_counts[brand] += 1
    sorted_brands = sorted(brand_counts.items(), key=lambda x: x[1], reverse=True)
    return {"brand_counts": dict(sorted_brands)}

def analyze_by_brand(items: List[Dict[str, Any]]) -> dict:
    # 에러가 발생했거나 아이템이 없는 경우
    if not items or "error" in items[0]:
        return {}

    brand_counts = defaultdict(int)
    for item in items:
        brand = item.get("brand") or "브랜드 없음"
        brand_counts[brand] += 1
    
    # 등장 횟수 순으로 정렬
    sorted_brands = sorted(brand_counts.items(), key=lambda x: x[1], reverse=True)
    
    return {"brand_counts": dict(sorted_brands)}