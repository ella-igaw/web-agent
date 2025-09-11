# ssg_hybrid_scraper.py - SSG Hybrid Scraper (Direct + OCR Fallback)
import asyncio
import re
import random
import urllib.parse
from typing import List, Dict, Any, Optional
from playwright.async_api import async_playwright
import json
from datetime import datetime

# OCR imports with fallbacks
try:
    import easyocr
    HAS_EASYOCR = True
except ImportError:
    HAS_EASYOCR = False

try:
    from PIL import Image
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

async def get_ssg_products_hybrid(query: str, max_products: int = 30, debug: bool = True) -> List[Dict[str, Any]]:
    """
    SSG.COM에서 제품 정보를 수집합니다.
    1차: 직접 HTML 스크래핑 시도
    2차: 실패 시 OCR 스크린샷 방식으로 자동 전환
    
    Args:
        query: 검색어
        max_products: 최대 제품 수
        debug: 디버그 모드
    
    Returns:
        제품 데이터 리스트
    """
    
    print(f"🔄 SSG Hybrid Scraper - Query: '{query}'")
    print("=" * 50)
    
    # Phase 1: Try direct HTML scraping
    print("1️⃣ Attempting direct HTML scraping...")
    direct_results = await try_direct_scraping(query, max_products, debug)
    
    # Check if direct scraping was successful
    successful_products = [p for p in direct_results if "error" not in p and p.get("product_name")]
    
    if len(successful_products) >= 5:  # Good enough results
        print(f"✅ Direct scraping successful: {len(successful_products)} products")
        return direct_results
    
    # Phase 2: Fallback to OCR screenshot
    print(f"⚠️  Direct scraping found only {len(successful_products)} products")
    print("2️⃣ Switching to OCR screenshot method...")
    
    if not HAS_EASYOCR and not HAS_TESSERACT:
        print("❌ No OCR libraries available!")
        print()
        print("🛠️  To fix this, run:")
        print("   python install_ocr.py")
        print()
        print("Or manually install:")
        print("   pip install easyocr Pillow opencv-python")
        print()
        return direct_results + [{"error": "OCR libraries not available", "solution": "Run: python install_ocr.py"}]
    
    ocr_results = await try_ocr_scraping(query, max_products, debug)
    
    # Combine results
    combined_results = []
    
    # Add successful direct results first
    for product in direct_results:
        if "error" not in product and product.get("product_name"):
            product["source"] = "direct_html"
            combined_results.append(product)
    
    # Add OCR results
    for product in ocr_results:
        if "error" not in product and product.get("product_name"):
            product["source"] = "ocr_screenshot"
            combined_results.append(product)
    
    # Re-rank combined results
    for i, product in enumerate(combined_results[:max_products]):
        product["rank"] = i + 1
    
    print(f"🎯 Final results: {len(combined_results)} products")
    print(f"   📊 Direct HTML: {len([p for p in combined_results if p.get('source') == 'direct_html'])}")
    print(f"   📸 OCR Screenshot: {len([p for p in combined_results if p.get('source') == 'ocr_screenshot'])}")
    
    return combined_results[:max_products]


async def try_direct_scraping(query: str, max_products: int, debug: bool) -> List[Dict[str, Any]]:
    """직접 HTML 스크래핑 시도"""
    
    products = []
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.ssg.com/search.ssg?target=all&query={encoded_query}&page=1&sort=sale"
    
    async with async_playwright() as p:
        browser = None
        try:
            if debug:
                print(f"🌐 Connecting to: {url}")
            
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale='ko-KR',
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            
            # Navigate to page
            await page.goto(url, wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(3000)
            
            # Scroll to load more products
            for i in range(2):
                await page.evaluate("window.scrollTo(0, window.scrollY + 1000)")
                await page.wait_for_timeout(1000)
            
            if debug:
                print("🔍 Searching for product elements...")
            
            # Enhanced selectors for SSG.COM
            selectors_to_try = [
                # 2024 layouts
                ".cunit_t232",
                ".cunit_t239", 
                ".cunit_md",
                ".cunit_t258",
                
                # Generic patterns
                "li[class*='cunit']",
                ".search_result .cunit",
                ".item_thmb",
                ".product_item",
                ".goods_item",
                
                # Fallback patterns
                "li[data-info]",
                "div[class*='item']",
                "article[class*='product']",
                "*[data-shp-contents-id]"
            ]
            
            items = []
            used_selector = None
            
            for selector in selectors_to_try:
                try:
                    if debug:
                        print(f"   Trying: {selector}")
                    
                    await page.wait_for_selector(selector, timeout=3000)
                    found_items = await page.query_selector_all(selector)
                    
                    if debug:
                        print(f"   Found: {len(found_items)} elements")
                    
                    if len(found_items) >= 5:  # Reasonable threshold
                        items = found_items
                        used_selector = selector
                        if debug:
                            print(f"✅ Using selector: {selector} ({len(items)} items)")
                        break
                    
                except Exception as e:
                    if debug:
                        print(f"   Failed: {str(e)[:30]}...")
                    continue
            
            if not items:
                if debug:
                    # Take screenshot for debugging
                    await page.screenshot(path=f"debug_ssg_direct_{query}.png")
                    print("📸 Debug screenshot saved")
                
                return [{"error": "No products found with direct scraping", "url": url, "debug_screenshot": f"debug_ssg_direct_{query}.png"}]
            
            # Extract product data
            if debug:
                print(f"📦 Extracting data from {len(items)} products...")
            
            for i, item in enumerate(items[:max_products]):
                try:
                    product_data = await extract_product_data_direct(item, i + 1)
                    
                    if product_data and product_data.get("product_name"):
                        products.append(product_data)
                        
                        if debug and i < 3:  # Show first 3
                            print(f"   {i+1}. {product_data.get('brand', 'N/A')[:12]} | {product_data.get('product_name', 'N/A')[:35]} | {product_data.get('price', 0):,}원")
                
                except Exception as e:
                    if debug:
                        print(f"   Error item {i+1}: {str(e)[:40]}...")
                    continue
            
        except Exception as e:
            if debug:
                print(f"❌ Direct scraping error: {e}")
            return [{"error": f"Direct scraping failed: {e}"}]
        
        finally:
            if browser:
                await browser.close()
    
    if debug:
        print(f"📊 Direct scraping result: {len(products)} products")
    
    return products


async def extract_product_data_direct(item, rank: int) -> Optional[Dict[str, Any]]:
    """직접 스크래핑에서 제품 데이터 추출"""
    
    product_data = {
        "rank": rank,
        "brand": "",
        "product_name": "",
        "price": 0,
        "review_count": 0,
        "rating": 0.0
    }
    
    try:
        # Extract title
        title_selectors = [
            ".cunit_info .tx_ko",
            ".tx_ko",
            ".cunit_tit",
            ".prod_tit",
            "a[title]",
            ".title"
        ]
        
        for t_sel in title_selectors:
            title_element = await item.query_selector(t_sel)
            if title_element:
                full_title = await title_element.text_content()
                if full_title and len(full_title.strip()) > 5:
                    brand, product_name = parse_brand_and_name(full_title.strip())
                    product_data["brand"] = brand
                    product_data["product_name"] = product_name
                    product_data["full_title"] = full_title.strip()
                    break
        
        # Extract price
        price_selectors = [
            ".cunit_price .ssg_price",
            ".ssg_price",
            ".price",
            ".sell_price",
            ".tx_num"
        ]
        
        for p_sel in price_selectors:
            price_element = await item.query_selector(p_sel)
            if price_element:
                price_text = await price_element.text_content()
                if price_text:
                    price_match = re.search(r'[\d,]+', price_text.replace(' ', '').replace('원', ''))
                    if price_match:
                        try:
                            product_data["price"] = int(price_match.group().replace(',', ''))
                            break
                        except:
                            continue
        
        # Extract review count
        review_selectors = [
            ".cunit_info .tx_num",
            ".review_count",
            "[class*='review']"
        ]
        
        for r_sel in review_selectors:
            review_element = await item.query_selector(r_sel)
            if review_element:
                review_text = await review_element.text_content()
                if review_text:
                    review_match = re.search(r'(\d+)', review_text)
                    if review_match:
                        product_data["review_count"] = int(review_match.group(1))
                        break
        
        return product_data if product_data["product_name"] else None
        
    except:
        return None


async def try_ocr_scraping(query: str, max_products: int, debug: bool) -> List[Dict[str, Any]]:
    """OCR 스크린샷 방식으로 스크래핑"""
    
    products = []
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.ssg.com/search.ssg?target=all&query={encoded_query}&page=1&sort=sale"
    
    async with async_playwright() as p:
        browser = None
        try:
            if debug:
                print("📸 Taking screenshot for OCR...")
            
            # Launch browser with more human-like settings
            browser = await p.chromium.launch(
                headless=False,  # Show browser briefly
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale='ko-KR',
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            
            # Remove automation indicators
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
            """)
            
            await page.goto(url, wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(5000)  # Wait for full load
            
            # Scroll to load more products
            for i in range(3):
                await page.evaluate("window.scrollTo(0, window.scrollY + 800)")
                await page.wait_for_timeout(1500)
            
            # Take full page screenshot
            screenshot_path = f"ssg_ocr_{query}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            
            if debug:
                print(f"📸 Screenshot saved: {screenshot_path}")
            
            await browser.close()
            
            # Process screenshot with OCR
            if debug:
                print("🔍 Processing screenshot with OCR...")
            
            products = process_ssg_screenshot_with_ocr(screenshot_path, max_products, debug)
            
        except Exception as e:
            if debug:
                print(f"❌ OCR scraping error: {e}")
            if browser:
                await browser.close()
            return [{"error": f"OCR scraping failed: {e}"}]
    
    return products


def process_ssg_screenshot_with_ocr(screenshot_path: str, max_products: int, debug: bool) -> List[Dict[str, Any]]:
    """스크린샷을 OCR로 처리하여 제품 데이터 추출"""
    
    products = []
    
    try:
        if HAS_EASYOCR:
            products = extract_with_easyocr_ssg(screenshot_path, max_products, debug)
        elif HAS_TESSERACT:
            products = extract_with_tesseract_ssg(screenshot_path, max_products, debug)
        else:
            return [{"error": "No OCR library available"}]
            
    except Exception as e:
        if debug:
            print(f"❌ OCR processing error: {e}")
        return [{"error": f"OCR processing failed: {e}"}]
    
    return products


def extract_with_easyocr_ssg(screenshot_path: str, max_products: int, debug: bool) -> List[Dict[str, Any]]:
    """EasyOCR로 SSG 스크린샷 처리"""
    
    products = []
    
    try:
        reader = easyocr.Reader(['ko', 'en'], gpu=False)
        result = reader.readtext(screenshot_path)
        
        if debug:
            print(f"🔍 OCR extracted {len(result)} text elements")
        
        # Group OCR results by vertical position (product rows)
        grouped_texts = group_ocr_results_by_position(result)
        
        if debug:
            print(f"📊 Grouped into {len(grouped_texts)} potential product rows")
        
        for i, group in enumerate(grouped_texts[:max_products]):
            try:
                # Combine text from this group
                combined_text = ' '.join([item[1] for item in group if item[2] > 0.5])  # Confidence > 0.5
                
                if len(combined_text) > 10:  # Reasonable text length
                    product_data = parse_ocr_text_to_product_ssg(combined_text, i + 1)
                    
                    if product_data:
                        products.append(product_data)
                        
                        if debug and i < 5:
                            print(f"   {i+1}. {product_data.get('brand', 'N/A')[:12]} | {product_data.get('product_name', 'N/A')[:35]} | {product_data.get('price', 0):,}원")
            
            except Exception as e:
                if debug:
                    print(f"   Error processing group {i+1}: {e}")
                continue
        
    except Exception as e:
        if debug:
            print(f"❌ EasyOCR error: {e}")
        return [{"error": f"EasyOCR failed: {e}"}]
    
    return products


def extract_with_tesseract_ssg(screenshot_path: str, max_products: int, debug: bool) -> List[Dict[str, Any]]:
    """Tesseract로 SSG 스크린샷 처리"""
    
    products = []
    
    try:
        from PIL import Image
        import pytesseract
        
        image = Image.open(screenshot_path)
        text = pytesseract.image_to_string(image, lang='kor+eng')
        
        # Split into lines and try to find products
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        current_product_lines = []
        
        for line in lines:
            if '원' in line and current_product_lines:  # Found a price, end of product
                combined_text = ' '.join(current_product_lines + [line])
                product_data = parse_ocr_text_to_product_ssg(combined_text, len(products) + 1)
                
                if product_data:
                    products.append(product_data)
                    
                    if debug and len(products) <= 3:
                        print(f"   {len(products)}. {product_data.get('brand', 'N/A')[:12]} | {product_data.get('product_name', 'N/A')[:35]} | {product_data.get('price', 0):,}원")
                
                current_product_lines = []
                
                if len(products) >= max_products:
                    break
            else:
                current_product_lines.append(line)
                
                # Limit lines per product to avoid combining unrelated text
                if len(current_product_lines) > 5:
                    current_product_lines = current_product_lines[-3:]  # Keep last 3 lines
        
    except Exception as e:
        if debug:
            print(f"❌ Tesseract error: {e}")
        return [{"error": f"Tesseract failed: {e}"}]
    
    return products


def group_ocr_results_by_position(ocr_result: List, tolerance: int = 80) -> List[List]:
    """OCR 결과를 세로 위치별로 그룹화 (제품 행별)"""
    
    if not ocr_result:
        return []
    
    # Sort by vertical position
    sorted_results = sorted(ocr_result, key=lambda x: x[0][0][1])
    
    groups = []
    current_group = [sorted_results[0]]
    current_y = sorted_results[0][0][0][1]
    
    for item in sorted_results[1:]:
        item_y = item[0][0][1]
        
        if abs(item_y - current_y) <= tolerance:
            current_group.append(item)
        else:
            if len(current_group) >= 2:  # Only keep groups with multiple elements
                groups.append(current_group)
            current_group = [item]
            current_y = item_y
    
    if current_group and len(current_group) >= 2:
        groups.append(current_group)
    
    return groups


def parse_ocr_text_to_product_ssg(text: str, rank: int) -> Optional[Dict[str, Any]]:
    """OCR 텍스트에서 SSG 제품 정보 파싱"""
    
    if not text or len(text.strip()) < 10:
        return None
    
    product_data = {
        "rank": rank,
        "brand": "",
        "product_name": "",
        "price": 0,
        "full_ocr_text": text
    }
    
    # Extract price
    price_match = re.search(r'(\d{1,3}(?:[,\d]*)?)\s*원', text)
    if price_match:
        try:
            product_data["price"] = int(price_match.group(1).replace(',', ''))
        except:
            pass
    
    # Remove price from text to get product name
    product_text = text
    if price_match:
        product_text = text.replace(price_match.group(0), '').strip()
    
    # Clean up text
    product_text = re.sub(r'\s+', ' ', product_text)
    product_text = re.sub(r'[^\w\s가-힣]', ' ', product_text).strip()
    
    # Extract brand and product name
    brand, product_name = parse_brand_and_name(product_text)
    product_data["brand"] = brand
    product_data["product_name"] = product_name
    
    # Only return if we have meaningful data
    return product_data if (product_name and len(product_name) > 3) or product_data["price"] > 0 else None


def parse_brand_and_name(full_text: str, known_brands: List) -> tuple[str, str]:
    """텍스트에서 브랜드와 제품명 분리"""
    
    text_lower = full_text.lower()
    found_brand = ""
    
    for brand in known_brands:
        if brand.lower() in text_lower:
            found_brand = brand
            break
    
    if found_brand:
        product_name = full_text
        for variant in [found_brand, found_brand.upper(), found_brand.lower()]:
            product_name = re.sub(rf'\b{re.escape(variant)}\b\s*', '', product_name).strip()
        
        product_name = re.sub(r'\s+', ' ', product_name)
        return found_brand, product_name
    else:
        words = full_text.split()
        if len(words) > 1:
            return words[0], ' '.join(words[1:])
        else:
            return "", full_text


async def main():
    """테스트 실행"""
    
    print("🎯 SSG Hybrid Scraper Test")
    print("=" * 40)
    print("This scraper tries HTML first, then switches to OCR if needed")
    print()
    
    query = "헤어드라이기"
    max_products = 15
    
    print(f"🔍 Testing with query: '{query}'")
    print(f"🎯 Target: {max_products} products")
    print()
    
    products = await get_ssg_products_hybrid(query, max_products, debug=True)
    
    print("\n" + "=" * 50)
    print("📊 FINAL RESULTS:")
    print("-" * 50)
    
    successful_products = [p for p in products if "error" not in p and p.get("product_name")]
    
    if successful_products:
        print(f"✅ Success: {len(successful_products)} products found")
        print()
        
        for product in successful_products[:10]:  # Show top 10
            source_emoji = "📊" if product.get("source") == "direct_html" else "📸"
            print(f"{source_emoji} {product['rank']:2d}. {product.get('brand', 'N/A')[:15]:15} | {product.get('product_name', 'N/A')[:40]:40} | {product.get('price', 0):8,}원")
        
        # Show source breakdown
        direct_count = len([p for p in successful_products if p.get("source") == "direct_html"])
        ocr_count = len([p for p in successful_products if p.get("source") == "ocr_screenshot"])
        
        print(f"\n📈 Source Breakdown:")
        print(f"   📊 Direct HTML: {direct_count}")
        print(f"   📸 OCR Screenshot: {ocr_count}")
        
        print(f"\n🎯 Perfect for mobile ads intelligence!")
        
    else:
        print("❌ No products found")
        for product in products:
            if "error" in product:
                print(f"   Error: {product['error']}")
        
        print("\n💡 Troubleshooting:")
        print("   1. Check internet connection")
        print("   2. Install OCR: pip install easyocr")
        print("   3. Try different query")


if __name__ == "__main__":
    asyncio.run(main())