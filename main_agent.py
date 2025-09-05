# main_agent.py
import os, json, re, pathlib, asyncio
from urllib.parse import urlparse
from modules.crawler import crawl_site
from modules.providers import provider_collect
from modules.utils import fetch, extract_text, _clean
from modules.llm_services import (
    brand_profile_from_pages,
    summarize_and_extract_insights,
    generate_comparison_table,
    ontology_for,
    verify_official_site
)
from modules.shopping_scraper import scrape_ssg_playwright

def fetch_evidence(meta: dict) -> dict:
    try:
        r = fetch(meta.get("url", "")); html = r.text; text = extract_text(html)
        if not text or len(text) < 150: return {**meta, "content": "", "error": "short"}
        return {**meta, "content": _clean(text)}
    except Exception as e:
        return {**meta, "content": "", "error": str(e)}

def analyze_price_range(pages: list) -> str:
    all_prices = [p for page in pages for p in page.get("prices", [])]
    if not all_prices: return "정보 없음"
    meaningful_prices = [p for p in all_prices if 10000 < p < 10000000]
    if not meaningful_prices: return "정보 없음"
    return f"약 {min(meaningful_prices):,}원 ~ {max(meaningful_prices):,}원"

def discover_seed_url(brand_name: str, industry: str, per_query_cap: int, preferred_provider: str, progress) -> str | None:
    progress("discover:start", {"brand_name": brand_name})

    queries = [f'{brand_name} 공식 홈페이지 {industry}', f'{brand_name} 공식 사이트', f'{brand_name} 브랜드']
    metas = provider_collect(preferred_provider, qs=queries, per_query_cap=10, min_keep_threshold=5, progress=progress)
    if not metas: return None

    # --- 1단계: 강화되고 유연해진 점수 계산 ---
    scored_metas = []
    for meta in metas:
        score = 0.0; url = meta.get("url", "").lower(); title = meta.get("title", "").lower()
        domain = urlparse(url).netloc.replace("www.", "")

        # (페널티) 뉴스/블로그/커뮤니티/정부/SNS 사이트
        if any(kw in domain for kw in ['news', 'recruit', 'blog', 'community', 'wiki', 'gov', 'go.kr', 'instagram', 'facebook', 'youtube']):
            score -= 5.0
        
        # 도메인에 브랜드 이름의 일부라도 포함된 경우
        # 예: "웅진씽크빅" -> "웅진", "씽크빅"으로 나눠서 "wjthinkbig"과 비교
        brand_tokens = re.findall(r'[a-zA-Z가-힣0-9]+', brand_name)
        if any(token.lower() in domain.lower() for token in brand_tokens):
            score += 5.0

        # (보너스) '공식' 키워드
        if "공식" in title or "official" in title:
            score += 2.0
        # (보너스) 짧은 URL 경로
        path_depth = len([s for s in urlparse(url).path.split('/') if s])
        if path_depth <= 1: # 루트 페이지나 바로 하위 페이지
            score += 1.0
        else:
            score -= path_depth * 0.5
        print(url, score)
        scored_metas.append({**meta, "score": score})
    
    sorted_metas = sorted(scored_metas, key=lambda x: x.get("score", 0), reverse=True)

    # --- 2단계: LLM 최종 검증 (더 똑똑해진 프롬프트 사용) ---
    for candidate in sorted_metas[:3]:
        # 점수가 0 이하인 후보는 검증할 가치도 없음
        if candidate.get("score", 0) < 0: continue
            
        url = candidate.get("url")
        progress("discover:verify", {"candidate_url": url, "score": candidate.get("score")})
        try:
            content = fetch_evidence({"url": url}).get("content", "")
            if content and verify_official_site(content, brand_name):
                progress("discover:done", {"brand_name": brand_name, "found_url": url, "source": "Verified Discovery"})
                return url
        except Exception:
            continue
    
    progress("discover:fail", {"reason": "No candidate passed verification."})
    # LLM 검증 실패 시, 가장 점수가 높았던 후보라도 반환 시도 (최후의 수단)
    if sorted_metas and sorted_metas[0].get("score", 0) > 0:
        fallback_url = sorted_metas[0].get("url")
        progress("discover:fallback", {"fallback_url": fallback_url})
        return fallback_url

    return None

def get_market_awareness(brand_name: str, industry: str, audience: str, per_query_cap: int, preferred_provider: str, min_keep_threshold: int, progress) -> dict:
    progress("news_agent:start", {"brand": brand_name})
    queries = [f'"{brand_name}" 시장 점유율 최신 뉴스', f'"{brand_name}" {industry} 산업 동향 네이버 뉴스', f'"{brand_name}" {audience} 타겟 분석 기사']
    metas = provider_collect(preferred_provider, qs=queries, per_query_cap=per_query_cap, min_keep_threshold=min_keep_threshold, timelimit='y', progress=progress)
    if not metas: return {"error": "No relevant news found.", "insights":[]}
    docs = [fetch_evidence(m) for m in metas]
    return summarize_and_extract_insights(docs, f"{brand_name}의 시장 인지도", industry, audience)

def get_consumer_image(brand_name: str, industry: str, audience: str, per_query_cap: int, progress) -> str:
    progress("sns_agent:start", {"brand": brand_name})
    queries = [f'site:instagram.com {brand_name} 후기', f'site:x.com {brand_name} 반응', f'{brand_name} 소비자 인식']
    metas = provider_collect("ddg", qs=queries, per_query_cap=per_query_cap, min_keep_threshold=3, progress=progress)
    if not metas: return "대중적 이미지를 파악하기 어려움"
    docs = [fetch_evidence(m) for m in metas]
    analysis = summarize_and_extract_insights(docs, f"{brand_name}에 대한 소비자 이미지", industry, audience)
    return (analysis.get("insights") or [{"insight": ""}])[0].get("insight") or (analysis.get("summary_bullets") or [""])[0]

# get_shopping_data 함수를 아래 코드로 교체
def get_shopping_data(brand_profile: dict, progress) -> dict:
    products_to_search = brand_profile.get("products_services", [])
    if not products_to_search: return {}
    
    main_product = products_to_search[0]
    progress("shopping_agent:start", {"target": "SSG.COM", "product": main_product})
    
    # 네이버 스크레이퍼 대신 SSG 스크레이퍼 호출
    shopping_results = asyncio.run(scrape_ssg_playwright(query=main_product, top_n=10))
    #shopping_results = await scrape_ssg_playwright(query=main_product, top_n=10)
    
    progress("shopping_agent:done", {"product": main_product, "results_count": len(shopping_results)})
    
    return {
        "main_product_analysis": {
            "product_name": main_product,
            "top_10_results": shopping_results
        }
    }
def create_competitor_profile(name: str, industry: str, audience: str, per_query_cap: int, preferred_provider: str, min_keep_threshold: int, progress) -> dict:
    progress("competitor:start", {"name": name})
    
    # Initialize with defaults to ensure we always return a valid profile
    profile_data = {
        "brand": name,
        "brand_position": "정보 없음",
        "price_range": "정보 없음", 
        "key_products": ["-"],
        "key_features": "정보 없음",
        "market_awareness": "정보 없음",
        "consumer_image": "정보 없음",
        "data_quality": "minimal"  # Track data quality
    }
    
    # Try to get website data
    site_profile = {}
    try:
        seed_url = discover_seed_url(name, industry, per_query_cap, preferred_provider, progress)
        if seed_url:
            progress("competitor:url_found", {"name": name, "url": seed_url})
            try:
                pages = crawl_site(seed_url, industry, max_pages=10, progress=progress)
                if pages and len(pages) > 0:
                    site_profile = brand_profile_from_pages(name, pages, industry, audience)
                    if site_profile and not site_profile.get("error"):
                        site_profile['estimated_price_range'] = analyze_price_range(pages)
                        profile_data["data_quality"] = "good"
                        progress("competitor:site_analyzed", {"name": name, "pages": len(pages)})
                    else:
                        progress("competitor:site_analysis_failed", {"name": name, "reason": "llm_analysis_failed"})
                else:
                    progress("competitor:no_pages", {"name": name, "reason": "crawling_failed"})
            except Exception as crawl_e:
                progress("competitor:crawl_error", {"name": name, "error": str(crawl_e)})
        else:
            progress("competitor:no_url", {"name": name, "reason": "url_discovery_failed"})
    except Exception as url_e:
        progress("competitor:url_error", {"name": name, "error": str(url_e)})
    
    # Update profile data with site information if available
    if site_profile and not site_profile.get("error"):
        profile_data.update({
            "brand": site_profile.get("brand", name),
            "brand_position": (site_profile.get("key_messages") or [profile_data["brand_position"]])[0],
            "price_range": site_profile.get("estimated_price_range", profile_data["price_range"]),
            "key_products": site_profile.get("products_services", profile_data["key_products"]),
            "key_features": (site_profile.get("key_messages") or [profile_data["key_features"]])[-1],
        })
    
    # Try to get market awareness (less critical, can fail gracefully)
    try:
        awareness_analysis = get_market_awareness(name, industry, audience, per_query_cap, preferred_provider, min_keep_threshold, progress)
        if awareness_analysis and not awareness_analysis.get("error"):
            insights = awareness_analysis.get("insights", [])
            if insights and len(insights) > 0:
                profile_data["market_awareness"] = insights[0].get("insight", "정보 없음")
                if profile_data["data_quality"] == "minimal":
                    profile_data["data_quality"] = "partial"
    except Exception as awareness_e:
        progress("competitor:awareness_error", {"name": name, "error": str(awareness_e)})
    
    # Try to get consumer image (less critical, can fail gracefully)  
    try:
        consumer_image = get_consumer_image(name, industry, audience, per_query_cap, progress)
        if consumer_image and consumer_image != "대중적 이미지를 파악하기 어려움":
            profile_data["consumer_image"] = consumer_image
            if profile_data["data_quality"] == "minimal":
                profile_data["data_quality"] = "partial"
    except Exception as image_e:
        progress("competitor:consumer_image_error", {"name": name, "error": str(image_e)})
    
    progress("competitor:done", {"name": name, "data_quality": profile_data["data_quality"]})
    return profile_data


def run_research_v3(seed_url: str, industry: str, audience: str, keywords: list, competitor_list: list, per_query_cap: int, preferred_provider: str, min_keep_threshold: int, progress):
    report = {"brand_profile": {}, "ontology": {}, "news_analysis": {}, "raw_news_docs": [], "shopping_data": {}, "competitor_profiles": [], "competitor_comparison_table": "분석 중 오류 발생", "run_meta": {}}
    try:
        progress("stage:start", {"seed_url": seed_url, "industry": industry, "audience": audience})
        if not seed_url:
            if not keywords: raise ValueError("Seed URL 또는 키워드를 입력해야 합니다.")
            brand_hint_from_kw = keywords[0]
            found_seed_url = discover_seed_url(brand_hint_from_kw, industry, per_query_cap, preferred_provider, progress)
            if found_seed_url: seed_url = found_seed_url
            else: raise ValueError(f"키워드 '{' '.join(keywords)}'로부터 유효한 웹사이트를 찾을 수 없습니다.")
        brand_hint = re.sub(r"^www\.", "", urlparse(seed_url).netloc.split(":")[0]).split(".")[0]
        report["run_meta"] = {"brand_hint": brand_hint, "outdir": f"out/{brand_hint}"}
        
        try:
            pages = crawl_site(seed_url, industry, max_pages=30, progress=progress)
            profile = brand_profile_from_pages(brand_hint, pages, industry, audience)
            profile['estimated_price_range'] = analyze_price_range(pages)
            report["brand_profile"] = profile
            product_industry = (profile.get("products_services") or ["-"])[0]
            report["ontology"] = ontology_for(industry, audience, product_industry)
            progress("profile:done", {"brand": profile.get('brand')})
        except Exception as e:
            progress("profile:error", {"error": str(e)}); report["brand_profile"] = {"error": f"프로필 생성 실패: {e}"}

        brand_name = report["brand_profile"].get("brand", brand_hint)
        try:
            news_analysis = get_market_awareness(brand_name, industry, audience, per_query_cap, preferred_provider, min_keep_threshold, progress)
            report["news_analysis"] = news_analysis
            # report["raw_news_docs"]는 news_analysis 내부에서 처리되지 않으므로 별도 수집 필요
        except Exception as e:
            progress("news:error", {"error": str(e)}); report["news_analysis"] = {"error": f"뉴스 분석 실패: {e}"}
        try:
            if report["brand_profile"].get("products_services"):
                report["shopping_data"] = get_shopping_data(report["brand_profile"], progress)
        except Exception as e:
            progress("shopping:error", {"error": str(e)}); report["shopping_data"] = {"error": f"쇼핑 데이터 분석 실패: {e}"}
        # Competitor analysis with graceful degradation
        try:
            names = competitor_list if len(competitor_list ) > 3 else  report.get("ontology", {}).get("competitor_corporate_and_brand_name") 
            if not names:
                progress("competitor:skip", {"reason": "No competitor names available"})
                report["competitor_profiles"] = []
                report["competitor_comparison_table"] = "경쟁사 정보가 없어 비교표를 생성할 수 없습니다."
            else:
                progress("competitor:start_batch", {"count": len(names), "names": names})
                competitor_profiles = []
                
                # Process each competitor individually with error handling
                for i, name in enumerate(names):
                    try:
                        profile = create_competitor_profile(name, industry, audience, per_query_cap, preferred_provider, min_keep_threshold, progress)
                        # Check if profile has meaningful data
                        if profile and profile.get("brand") and profile.get("brand") != name:
                            competitor_profiles.append(profile)
                            progress("competitor:success", {"name": name, "completed": i+1, "total": len(names)})
                        else:
                            progress("competitor:empty", {"name": name, "reason": "insufficient_data"})
                    except Exception as comp_e:
                        progress("competitor:individual_error", {"name": name, "error": str(comp_e)})
                        # Continue with other competitors even if one fails
                        continue
                
    
                
                # Generate comparison table only if we have competitor data
                if competitor_profiles:
                    try:
                        main_brand_profile_for_table = { "brand": brand_name, **report["brand_profile"] }
                        main_brand_profile_for_table['market_awareness'] = report["news_analysis"].get("insights",[{}])[0].get("insight","")
                        main_brand_profile_for_table['consumer_image'] = get_consumer_image(brand_name, industry, audience, per_query_cap, progress)
                        report["competitor_comparison_table"] = generate_comparison_table(main_brand_profile_for_table, competitor_profiles, industry, audience)
                        progress("competitor:comparison_done", {"competitor_count": len(competitor_profiles)})
                    except Exception as table_e:
                        progress("competitor:comparison_error", {"error": str(table_e)})
                        report["competitor_comparison_table"] = f"비교표 생성 중 오류 발생: {str(table_e)}"
                else:
                    report["competitor_comparison_table"] = "경쟁사 데이터 수집에 실패하여 비교표를 생성할 수 없습니다."
                    progress("competitor:no_data", {"attempted": len(names), "successful": 0})
                    
        except Exception as e:
            progress("competitor:fatal_error", {"error": str(e)})
            report["competitor_profiles"] = []
            report["competitor_comparison_table"] = f"경쟁사 분석 중 오류 발생: {str(e)}"
    except Exception as e:
        progress("pipeline:fatal_error", {"error": str(e)})
    finally:
        outdir = pathlib.Path(report.get("run_meta", {}).get("outdir", f"out/{brand_hint or 'default'}"))
        outdir.mkdir(parents=True, exist_ok=True)
        with open(outdir / "report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        progress("stage:done", {"outdir": str(outdir)})
        return report