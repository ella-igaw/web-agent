# modules/shopping_scraper.py
import re
import random # random 라이브러리를 직접 import
from typing import List, Dict
from playwright.async_api import async_playwright
from config import USER_AGENTS # config에서 User-Agent 리스트만 가져옴


def improve_search_query(query: str) -> str:
    """
    개선된 검색어로 변환하여 더 나은 결과를 얻습니다.
    """
    # Remove generic terms that yield poor results
    generic_terms = ["프리미엄", "뷰티", "스타일링", "제품"]
    improved = query
    
    # Brand-specific improvements
    brand_mappings = {
        "프리미엄 뷰티 스타일링 제품": "헤어드라이어 고데기",
        "헤어케어": "헤어드라이어",
        "스타일링": "고데기",
        "뷰티 기기": "헤어드라이어"
    }
    
    for original, replacement in brand_mappings.items():
        if original in query:
            return replacement
    
    # Remove too generic terms
    for term in generic_terms:
        if term in improved and len(improved.split()) > 2:
            improved = improved.replace(term, "").strip()
    
    return improved if improved else query


async def scrape_ssg_playwright(query: str, top_n: int = 10, sort_by: str = "sale") -> List[Dict[str, any]]:
    """
    Playwright를 사용하여 SSG.COM 검색 결과를 스크레이핑합니다.
    sort_by options: sale(판매순), pop(인기순), rev(리뷰순), pa(낮은가격순), pd(높은가격순)
    """
    products = []
    
    # Improve search query for better results
    improved_query = improve_search_query(query)
    encoded_query = re.sub(r'\s+', '+', improved_query)
    
    # Sort options mapping
    sort_options = {
        'sale': 'sale',      # 판매순 (best for purchase data)
        'popular': 'pop',    # 인기순
        'review': 'rev',     # 리뷰순  
        'price_low': 'pa',   # 낮은가격순
        'price_high': 'pd',  # 높은가격순
        'recent': 'rd'       # 최신순
    }
    
    sort_param = sort_options.get(sort_by, 'sale')
    url = f"https://www.ssg.com/search.ssg?target=all&query={encoded_query}&sort={sort_param}"

    async with async_playwright() as p:
        browser = None
        page = None
        try:
            random_user_agent = random.choice(USER_AGENTS)
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random_user_agent, 
                locale='ko-KR',
                viewport={'width': 1280, 'height': 720}
            )
            page = await context.new_page()
            
            # Set additional headers to look more like a real browser
            await page.set_extra_http_headers({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            })
            
            await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait a bit for dynamic content to load
            await page.wait_for_timeout(2000)
            
            # Multiple possible selectors for SSG.COM product listings
            possible_selectors = [
                "li.cunit_t232",  # Original selector
                "li[class*='cunit']",  # More flexible selector
                ".cunit_prod",  # Alternative selector
                ".search_result .cunit",  # Search result specific
                "li.cunit_md",  # Medium layout
                "li.cunit_t239",  # Alternative layout
                ".item_thmb"  # Thumbnail item
            ]
            
            items = []
            list_selector = None
            
            # Try different selectors until one works
            for selector in possible_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    items = await page.query_selector_all(selector)
                    if items:
                        list_selector = selector
                        break
                except:
                    continue
            
            if not items:
                # Last resort: try to find any product-like elements
                items = await page.query_selector_all("[data-info*='prod'] li, .prod_item, .item")
                if not items:
                    return [{"error": "No product items found on page", "url": url}]
            
            print(f"Found {len(items)} items using selector: {list_selector}")
            
            for i, item in enumerate(items[:top_n]):
                try:
                    # Multiple possible title selectors
                    title_selectors = [
                        ".cunit_info .tx_ko",  # Original
                        ".tx_ko",
                        ".cunit_tit",
                        ".prod_tit",
                        ".item_tit",
                        "a[title]",
                        ".title",
                        "h3", "h4"
                    ]
                    
                    title = "N/A"
                    for t_sel in title_selectors:
                        title_element = await item.query_selector(t_sel)
                        if title_element:
                            title_text = await title_element.text_content()
                            if title_text and title_text.strip():
                                title = title_text.strip()
                                break
                    
                    # Multiple possible price selectors
                    price_selectors = [
                        ".cunit_price .ssg_price",  # Original
                        ".ssg_price",
                        ".price",
                        ".sell_price",
                        ".tx_num",
                        "[class*='price']",
                        ".cunit_price span"
                    ]
                    
                    price = 0
                    for p_sel in price_selectors:
                        price_element = await item.query_selector(p_sel)
                        if price_element:
                            price_text = await price_element.text_content()
                            if price_text:
                                # Extract numbers from price text
                                price_match = re.search(r'[\d,]+', price_text.replace(' ', ''))
                                if price_match:
                                    price = int(price_match.group().replace(',', ''))
                                    break
                    
                    # Get product URL if available
                    link_element = await item.query_selector("a[href]")
                    product_url = ""
                    if link_element:
                        href = await link_element.get_attribute("href")
                        if href:
                            product_url = href if href.startswith('http') else f"https://www.ssg.com{href}"
                    
                    # Extract purchase indicators
                    purchase_indicators = {}
                    
                    # Look for review count (indicates purchase volume)
                    review_selectors = [".cunit_info .tx_num", ".review_count", "[class*='review']", ".star + .tx_num"]
                    for r_sel in review_selectors:
                        review_element = await item.query_selector(r_sel)
                        if review_element:
                            review_text = await review_element.text_content()
                            if review_text:
                                review_match = re.search(r'(\d+)', review_text)
                                if review_match:
                                    purchase_indicators["review_count"] = int(review_match.group(1))
                                    break
                    
                    # Look for badges indicating popularity/sales
                    badge_selectors = [".badge", ".cunit_badge", "[class*='best']", "[class*='hot']"]
                    badges = []
                    for b_sel in badge_selectors:
                        badge_elements = await item.query_selector_all(b_sel)
                        for badge in badge_elements:
                            badge_text = await badge.text_content()
                            if badge_text and badge_text.strip():
                                badges.append(badge_text.strip())
                    
                    # Look for rating
                    rating = 0
                    rating_selectors = [".star", ".rating", "[class*='star']"]
                    for rating_sel in rating_selectors:
                        rating_element = await item.query_selector(rating_sel)
                        if rating_element:
                            rating_text = await rating_element.get_attribute("title") or await rating_element.text_content()
                            if rating_text:
                                rating_match = re.search(r'(\d+\.?\d*)', rating_text)
                                if rating_match:
                                    rating = float(rating_match.group(1))
                                    break
                    
                    # Calculate purchase score (for ranking by purchase likelihood)
                    purchase_score = 0
                    if purchase_indicators.get("review_count", 0) > 0:
                        purchase_score += min(purchase_indicators["review_count"], 1000)  # Cap at 1000
                    if rating > 0:
                        purchase_score += rating * 10  # Rating contributes to score
                    if any("베스트" in badge or "인기" in badge or "BEST" in badge.upper() for badge in badges):
                        purchase_score += 100  # Boost for bestseller badges
                    
                    products.append({
                        "rank": i + 1,
                        "title": title,
                        "price": price,
                        "url": product_url,
                        "review_count": purchase_indicators.get("review_count", 0),
                        "rating": rating,
                        "badges": badges,
                        "purchase_score": purchase_score,
                        "sort_method": sort_by
                    })
                
                except Exception as e:
                    print(f"Error processing item {i+1}: {e}")
                    continue
        
        except Exception as e:
            print(f"Playwright scraping failed for SSG.COM query '{query}': {e}")
            # Save screenshot for debugging
            if page:
                try:
                    await page.screenshot(path=f"debug_ssg_error_{query[:10]}.png")
                except:
                    pass
            return [{"error": str(e), "query": query, "url": url}]
        
        finally:
            if browser and browser.is_connected(): 
                await browser.close()

    return products if products else [{"error": "No products found", "query": query, "url": url}]