# modules/shopping_scraper.py
import asyncio
import re
import random
from typing import List, Dict, Any
from playwright.async_api import async_playwright
from config import USER_AGENTS

# --- 핵심 JS: 현재 SSG 구조에 맞춰 재설계된, 더 짧고 강력한 데이터 추출기 ---
JS_PAYLOAD = r"""
(() => {
    const MAX_ITEMS = %MAX%;

    // --- 유틸리티 함수 ---
    const getText = (el, selector) => {
        const node = el.querySelector(selector);
        return node ? node.textContent.trim() : "";
    };
    const getNumber = (text) => {
        if (!text) return null;
        const match = text.replace(/,|원/g, "").match(/\d+/);
        return match ? parseInt(match[0], 10) : null;
    };
    const getAttribute = (el, selector, attr) => {
        const node = el.querySelector(selector);
        return node ? node.getAttribute(attr) : "";
    };

    // --- 데이터 수집 ---
    // SSG에서 상품 카드 하나하나를 가리키는 가장 안정적인 선택자입니다.
    const productItems = document.querySelectorAll("li.cunit_prod");
    const results = [];

    for (const item of productItems) {
        if (results.length >= MAX_ITEMS) break;

        const title = getText(item, ".cunit_info .cunit_tit .tx_ko");
        const price = getNumber(getText(item, ".cunit_price .ssg_price"));
        const brand = getText(item, ".cunit_info .cunit_brand");
        const reviewCount = getNumber(getText(item, ".cunit_app .rating_tx .tx_num"));
        let url = getAttribute(item, "a.cunit_prod_link", "href");
        if (url && !url.startsWith('http')) {
            url = new URL(url, location.href).href;
        }
        
        // 유효한 데이터(제목과 가격이 모두 있는)만 결과에 추가
        if (title && price) {
            results.push({
                title: title,
                price: price,
                brand: brand || null,
                review_count: reviewCount || 0,
                url: url || null
            });
        }
    }
    return results;
})();
"""

async def scrape_ssg_playwright(query: str, top_n: int = 20) -> List[Dict[str, any]]:
    """
    Playwright와 업그레이드된 JS 주입을 사용하여 SSG.COM 검색 결과를 스크레이핑합니다.
    """
    products = []
    encoded_query = re.sub(r'\s+', '+', query)
    url = f"https://www.ssg.com/search.ssg?target=all&query={encoded_query}&sort=sale"

    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale='ko-KR'
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            script_with_max = JS_PAYLOAD.replace("%MAX%", str(top_n))
            scraped_data = await page.evaluate(script_with_max)
            
            for i, item in enumerate(scraped_data):
                item["rank"] = i + 1
                products.append(item)
        
        except Exception as e:
            print(f"Playwright scraping failed for SSG.COM query '{query}': {e}")
            if 'page' in locals(): await page.screenshot(path="debug_ssg_error.png")
            return [{"error": str(e)}]
        
        finally:
            if browser and browser.is_connected(): await browser.close()

    return products