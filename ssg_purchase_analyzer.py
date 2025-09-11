# ssg_purchase_analyzer.py - SSG.COM Purchase Behavior Analysis
import asyncio
import re
import random
import urllib.parse
from typing import List, Dict, Any
import json
from datetime import datetime

# Playwright import with error handling
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("❌ Playwright not available. Install with: pip install playwright")

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

async def analyze_ssg_purchase_behavior(query: str, max_products: int = 50, include_reviews: bool = True) -> Dict[str, Any]:
    """
    SSG.COM에서 구매 행동 패턴을 분석합니다.
    
    Args:
        query: 검색어 (예: "헤어드라이기")
        max_products: 분석할 최대 제품 수
        include_reviews: 리뷰 데이터 포함 여부
    
    Returns:
        구매 행동 분석 결과
    """
    
    print(f"🛒 SSG.COM Purchase Behavior Analysis")
    print(f"🔍 Query: '{query}' | Target: {max_products} products")
    print("=" * 60)
    
    # Collect purchase data
    purchase_data = await crawl_ssg_purchase_data(query, max_products, include_reviews)
    
    if not purchase_data or all("error" in item for item in purchase_data):
        return {"error": "Failed to collect purchase data", "query": query}
    
    # Analyze purchase patterns
    analysis = analyze_purchase_patterns(purchase_data, query)
    
    # Save detailed results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"ssg_purchase_analysis_{query}_{timestamp}.json"
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "query": query,
            "analysis_time": datetime.now().isoformat(),
            "total_products": len(purchase_data),
            "purchase_analysis": analysis,
            "raw_data": purchase_data
        }, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Analysis saved: {output_file}")
    
    return analysis


async def crawl_ssg_purchase_data(query: str, max_products: int, include_reviews: bool) -> List[Dict[str, Any]]:
    """SSG.COM에서 구매 관련 데이터를 수집합니다."""
    
    products = []
    encoded_query = urllib.parse.quote(query)
    
    # SSG.COM 판매순 정렬 URL
    url = f"https://www.ssg.com/search.ssg?target=all&query={encoded_query}&page=1&sort=sale"
    
    async with async_playwright() as p:
        browser = None
        try:
            print("🌐 Connecting to SSG.COM...")
            
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale='ko-KR',
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            
            await page.goto(url, wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(3000)
            
            print("📦 Extracting product data...")
            
            # Load more products by scrolling if needed
            for i in range(3):
                await page.evaluate("window.scrollTo(0, window.scrollY + 1000)")
                await page.wait_for_timeout(1000)
            
            # Enhanced product selectors for SSG
            product_selectors = [
                ".cunit_t232",
                ".cunit_t239", 
                ".cunit_md",
                "li[class*='cunit']",
                ".search_result .cunit",
                ".item_thmb"
            ]
            
            items = []
            for selector in product_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    items = await page.query_selector_all(selector)
                    if len(items) >= 10:
                        print(f"✅ Found {len(items)} products using: {selector}")
                        break
                except:
                    continue
            
            if not items:
                print("❌ No products found")
                return [{"error": "No products found", "url": url}]
            
            # Extract detailed purchase data
            for i, item in enumerate(items[:max_products]):
                try:
                    product_data = await extract_detailed_product_data(item, i + 1, page, include_reviews)
                    
                    if product_data and product_data.get("product_name"):
                        products.append(product_data)
                        
                        # Progress indicator
                        if i % 10 == 0:
                            print(f"📊 Processed {i+1}/{min(len(items), max_products)} products...")
                
                except Exception as e:
                    print(f"⚠️  Error processing product {i+1}: {str(e)[:50]}...")
                    continue
            
        except Exception as e:
            print(f"❌ SSG crawling error: {e}")
            return [{"error": str(e)}]
        
        finally:
            if browser:
                await browser.close()
    
    print(f"✅ Collected {len(products)} products with purchase data")
    return products


async def extract_detailed_product_data(item, rank: int, page, include_reviews: bool) -> Dict[str, Any]:
    """개별 제품의 상세 구매 데이터를 추출합니다."""
    
    product_data = {
        "rank": rank,
        "brand": "",
        "product_name": "",
        "price": 0,
        "original_price": 0,
        "discount_rate": 0,
        "review_count": 0,
        "rating": 0.0,
        "badges": [],
        "delivery_info": "",
        "seller_type": "",
        "purchase_indicators": {}
    }
    
    try:
        # Extract title and brand
        title_selectors = [
            ".cunit_info .tx_ko",
            ".tx_ko",
            ".cunit_tit",
            ".prod_tit",
            "a[title]"
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
        
        # Extract pricing information
        await extract_pricing_data(item, product_data)
        
        # Extract purchase indicators
        await extract_purchase_indicators(item, product_data)
        
        # Extract seller and delivery info
        await extract_seller_delivery_info(item, product_data)
        
        # Get product URL for detailed analysis
        link_element = await item.query_selector("a[href]")
        if link_element:
            href = await link_element.get_attribute("href")
            if href:
                product_data["url"] = href if href.startswith('http') else f"https://www.ssg.com{href}"
                
                # Get additional details from product page if needed
                if include_reviews and rank <= 10:  # Only for top 10 products
                    await get_product_page_details(page, product_data["url"], product_data)
    
    except Exception as e:
        product_data["extraction_error"] = str(e)
    
    return product_data


async def extract_pricing_data(item, product_data: Dict[str, Any]):
    """가격 정보 추출"""
    
    # Current price
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
    
    # Original price and discount
    discount_selectors = [
        ".cunit_price .blind",
        ".original_price",
        ".tx_ko.tx_gray"
    ]
    
    for d_sel in discount_selectors:
        discount_element = await item.query_selector(d_sel)
        if discount_element:
            discount_text = await discount_element.text_content()
            if discount_text and '원' in discount_text:
                original_match = re.search(r'[\d,]+', discount_text.replace(' ', '').replace('원', ''))
                if original_match:
                    try:
                        original_price = int(original_match.group().replace(',', ''))
                        product_data["original_price"] = original_price
                        
                        # Calculate discount rate
                        if product_data["price"] > 0:
                            discount_rate = round(((original_price - product_data["price"]) / original_price) * 100, 1)
                            product_data["discount_rate"] = discount_rate
                        break
                    except:
                        continue


async def extract_purchase_indicators(item, product_data: Dict[str, Any]):
    """구매 지표 추출 (리뷰, 평점, 배지 등)"""
    
    # Review count
    review_selectors = [
        ".cunit_info .tx_num",
        ".review_count", 
        "[class*='review']",
        ".star + .tx_num"
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
    
    # Rating
    rating_selectors = [
        ".star",
        ".rating", 
        "[class*='star']"
    ]
    
    for rating_sel in rating_selectors:
        rating_element = await item.query_selector(rating_sel)
        if rating_element:
            rating_text = await rating_element.get_attribute("title") or await rating_element.text_content()
            if rating_text:
                rating_match = re.search(r'(\d+\.?\d*)', rating_text)
                if rating_match:
                    try:
                        product_data["rating"] = float(rating_match.group(1))
                        break
                    except:
                        continue
    
    # Badges and indicators
    badge_selectors = [
        ".badge",
        ".cunit_badge", 
        "[class*='best']",
        "[class*='hot']",
        "[class*='new']"
    ]
    
    badges = []
    for b_sel in badge_selectors:
        badge_elements = await item.query_selector_all(b_sel)
        for badge in badge_elements:
            badge_text = await badge.text_content()
            if badge_text and badge_text.strip():
                badges.append(badge_text.strip())
    
    product_data["badges"] = badges


async def extract_seller_delivery_info(item, product_data: Dict[str, Any]):
    """판매자 및 배송 정보 추출"""
    
    # Delivery information
    delivery_selectors = [
        ".delivery_info",
        ".cunit_delivery",
        "[class*='delivery']"
    ]
    
    for d_sel in delivery_selectors:
        delivery_element = await item.query_selector(d_sel)
        if delivery_element:
            delivery_text = await delivery_element.text_content()
            if delivery_text:
                product_data["delivery_info"] = delivery_text.strip()
                break
    
    # Seller type (SSG direct, marketplace, etc.)
    seller_selectors = [
        ".seller_info",
        ".cunit_seller",
        "[class*='seller']"
    ]
    
    for s_sel in seller_selectors:
        seller_element = await item.query_selector(s_sel)
        if seller_element:
            seller_text = await seller_element.text_content()
            if seller_text:
                product_data["seller_type"] = seller_text.strip()
                break


async def get_product_page_details(page, product_url: str, product_data: Dict[str, Any]):
    """제품 상세 페이지에서 추가 정보 수집 (선택사항)"""
    # Store parameters for potential future use
    _ = (page, product_url, product_data)
    
    # This function is intentionally left empty to avoid too many requests
    # In a future version, this could navigate to individual product pages
    # for more detailed information like detailed specifications, reviews, etc.
    return None


def parse_brand_and_name(full_title: str) -> tuple[str, str]:
    """제품명에서 브랜드와 제품명 분리"""
    known_brands = [
        "다이슨", "Dyson", "필립스", "Philips", "파나소닉", "Panasonic",
        "샤오미", "Xiaomi", "LG", "삼성", "Samsung", "테팔", "브라운", "Braun",
        "글램팜", "보다나", "유닉스", "살롱드프로", "모즈", "아이디어",
        "레틴", "바이레텍", "코멘", "클레오"
    ]
    
    title_lower = full_title.lower()
    found_brand = ""
    
    for brand in known_brands:
        if brand.lower() in title_lower:
            found_brand = brand
            break
    
    if found_brand:
        product_name = full_title
        for variant in [found_brand, found_brand.upper(), found_brand.lower()]:
            product_name = re.sub(rf'\b{re.escape(variant)}\b\s*', '', product_name).strip()
        
        product_name = re.sub(r'\s+', ' ', product_name)
        return found_brand, product_name
    else:
        words = full_title.split()
        if len(words) > 1:
            return words[0], ' '.join(words[1:])
        else:
            return "", full_title


def analyze_purchase_patterns(products: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    """구매 패턴 분석"""
    
    print("📊 Analyzing purchase patterns...")
    
    valid_products = [p for p in products if "error" not in p and p.get("product_name")]
    
    if not valid_products:
        return {"error": "No valid products to analyze"}
    
    analysis = {
        "query": query,
        "total_products_analyzed": len(valid_products),
        "price_analysis": analyze_price_patterns(valid_products),
        "brand_analysis": analyze_brand_patterns(valid_products), 
        "purchase_signals": analyze_purchase_signals(valid_products),
        "market_insights": generate_market_insights(valid_products, query),
        "mobile_ads_recommendations": generate_mobile_ads_insights(valid_products, query)
    }
    
    return analysis


def analyze_price_patterns(products: List[Dict[str, Any]]) -> Dict[str, Any]:
    """가격 패턴 분석"""
    prices = [p["price"] for p in products if p["price"] > 0]
    
    if not prices:
        return {"error": "No price data available"}
    
    return {
        "price_range": {
            "min": min(prices),
            "max": max(prices),
            "average": round(sum(prices) / len(prices), 0),
            "median": sorted(prices)[len(prices)//2]
        },
        "price_tiers": {
            "budget": len([p for p in prices if p < 50000]),
            "mid_range": len([p for p in prices if 50000 <= p <= 200000]),
            "premium": len([p for p in prices if p > 200000])
        },
        "discount_analysis": {
            "products_with_discount": len([p for p in products if p.get("discount_rate", 0) > 0]),
            "average_discount": round(sum([p.get("discount_rate", 0) for p in products]) / len(products), 1)
        }
    }


def analyze_brand_patterns(products: List[Dict[str, Any]]) -> Dict[str, Any]:
    """브랜드 패턴 분석"""
    brand_counts = {}
    brand_avg_prices = {}
    brand_reviews = {}
    
    for product in products:
        brand = product.get("brand", "Unknown")
        if brand:
            brand_counts[brand] = brand_counts.get(brand, 0) + 1
            
            if product["price"] > 0:
                if brand not in brand_avg_prices:
                    brand_avg_prices[brand] = []
                brand_avg_prices[brand].append(product["price"])
            
            if product.get("review_count", 0) > 0:
                if brand not in brand_reviews:
                    brand_reviews[brand] = []
                brand_reviews[brand].append(product["review_count"])
    
    # Calculate averages
    for brand in brand_avg_prices:
        brand_avg_prices[brand] = round(sum(brand_avg_prices[brand]) / len(brand_avg_prices[brand]), 0)
    
    for brand in brand_reviews:
        brand_reviews[brand] = round(sum(brand_reviews[brand]) / len(brand_reviews[brand]), 0)
    
    return {
        "brand_distribution": dict(sorted(brand_counts.items(), key=lambda x: x[1], reverse=True)),
        "brand_avg_prices": brand_avg_prices,
        "brand_avg_reviews": brand_reviews,
        "top_brands": list(sorted(brand_counts.items(), key=lambda x: x[1], reverse=True)[:5])
    }


def analyze_purchase_signals(products: List[Dict[str, Any]]) -> Dict[str, Any]:
    """구매 신호 분석 (리뷰, 평점, 배지 등)"""
    
    review_counts = [p["review_count"] for p in products if p.get("review_count", 0) > 0]
    ratings = [p["rating"] for p in products if p.get("rating", 0) > 0]
    
    # Badge analysis
    all_badges = []
    for product in products:
        all_badges.extend(product.get("badges", []))
    
    badge_counts = {}
    for badge in all_badges:
        badge_counts[badge] = badge_counts.get(badge, 0) + 1
    
    return {
        "review_analysis": {
            "products_with_reviews": len(review_counts),
            "avg_review_count": round(sum(review_counts) / len(review_counts), 0) if review_counts else 0,
            "max_reviews": max(review_counts) if review_counts else 0
        },
        "rating_analysis": {
            "products_with_ratings": len(ratings),
            "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else 0,
            "high_rated_products": len([r for r in ratings if r >= 4.0])
        },
        "badge_distribution": dict(sorted(badge_counts.items(), key=lambda x: x[1], reverse=True))
    }


def generate_market_insights(products: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    """시장 인사이트 생성"""
    
    # Top performing products (high reviews + good rating)
    top_products = []
    _ = query  # Store query for potential future use
    
    for product in products:
        score = 0
        if product.get("review_count", 0) > 100:
            score += product["review_count"] / 100
        if product.get("rating", 0) >= 4.0:
            score += product["rating"] * 10
        if product.get("badges"):
            score += len(product["badges"]) * 5
        
        product["market_score"] = score
        if score > 10:
            top_products.append(product)
    
    top_products.sort(key=lambda x: x["market_score"], reverse=True)
    
    return {
        "market_leaders": top_products[:5],
        "category_saturation": len(set([p.get("brand", "") for p in products])),
        "price_competition": "high" if len(set([p["price"] for p in products if p["price"] > 0])) > 10 else "moderate",
        "consumer_engagement": "high" if sum([p.get("review_count", 0) for p in products]) > 5000 else "moderate"
    }


def generate_mobile_ads_insights(products: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
    """모바일 광고 전략 인사이트"""
    
    prices = [p["price"] for p in products if p["price"] > 0]
    avg_price = sum(prices) / len(prices) if prices else 0
    _ = query  # Store category name for targeting insights
    
    return {
        "target_audience_insights": {
            "price_sensitivity": "high" if avg_price < 100000 else "low",
            "brand_loyalty": "high" if len(set([p.get("brand") for p in products])) < 5 else "moderate",
            "research_driven": "high" if sum([p.get("review_count", 0) for p in products]) > 10000 else "moderate"
        },
        "ad_targeting_recommendations": {
            "budget_segments": {
                "low_budget": f"Under {min(prices):,}원" if prices else "N/A",
                "mid_budget": f"{int(avg_price*0.8):,}원 - {int(avg_price*1.2):,}원" if prices else "N/A", 
                "high_budget": f"Over {max(prices):,}원" if prices else "N/A"
            },
            "key_selling_points": [
                "Price competitiveness" if len([p for p in products if p.get("discount_rate", 0) > 10]) > 5 else None,
                "Brand reputation" if any("브랜드" in str(p.get("badges", [])) for p in products) else None,
                "Customer satisfaction" if sum([p.get("rating", 0) for p in products]) / len(products) > 4.0 else None
            ]
        },
        "campaign_timing": {
            "competition_level": "high" if len(products) > 30 else "moderate",
            "market_opportunity": "good" if avg_price > 50000 and len(products) < 50 else "competitive"
        }
    }


async def main():
    """테스트 실행"""
    query = "헤어드라이기"
    
    print("🎯 SSG Purchase Behavior Analyzer")
    print("=" * 50)
    print("This tool analyzes REAL purchase patterns on SSG.COM")
    print("Perfect for understanding Korean consumer behavior!")
    print()
    
    result = await analyze_ssg_purchase_behavior(query, max_products=20, include_reviews=False)
    
    if "error" not in result:
        print("\n📊 KEY INSIGHTS:")
        print("-" * 30)
        
        # Price insights
        price_info = result.get("price_analysis", {}).get("price_range", {})
        if price_info:
            print(f"💰 Price Range: {price_info.get('min', 0):,}원 - {price_info.get('max', 0):,}원")
            print(f"📈 Average Price: {price_info.get('average', 0):,}원")
        
        # Brand insights  
        top_brands = result.get("brand_analysis", {}).get("top_brands", [])
        if top_brands:
            print(f"🏆 Top Brands: {', '.join([f'{brand}({count})' for brand, count in top_brands[:3]])}")
        
        # Mobile ads insights
        ads_insights = result.get("mobile_ads_recommendations", {})
        if ads_insights:
            target_info = ads_insights.get("target_audience_insights", {})
            print(f"🎯 Price Sensitivity: {target_info.get('price_sensitivity', 'unknown')}")
            print(f"🔍 Research Driven: {target_info.get('research_driven', 'unknown')}")
        
        print(f"\n✅ Full analysis completed!")
        print("📄 Check the saved JSON file for complete details")
    else:
        print(f"❌ Analysis failed: {result.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())