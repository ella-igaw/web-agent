# modules/llm_services.py
import os, re, json
import google.generativeai as genai
import dotenv
dotenv_file = dotenv.find_dotenv()
dotenv.load_dotenv(dotenv_file)

USE_LLM = bool(os.environ["GEMINI_API_KEY"])
GEM_MODEL = "gemini-2.0-flash-lite"



def get_llm_response(prompt: str, is_json=True, max_retries=3, retry_delay=1):
    import time
    
    if not USE_LLM:
        return {"error": "LLM API Key not configured."} if is_json else "LLM not configured."
    
    last_error = None
    for attempt in range(max_retries):
        try:
            genai.configure(api_key=os.environ["GEMINI_API_KEY"])
            model = genai.GenerativeModel(GEM_MODEL)
            
            # Generate content with safety settings to avoid blocks
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=2048,
                ),
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ]
            )
            
            text = (response.text or "").strip()
            if not text:
                raise ValueError("Empty response from Gemini API")
                
            if is_json:
                # Try to extract JSON from response
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(0))
                    except json.JSONDecodeError as je:
                        # If JSON parsing fails, try to fix common issues
                        json_str = match.group(0)
                        # Fix common JSON issues
                        json_str = re.sub(r',\s*}', '}', json_str)  # Remove trailing commas
                        json_str = re.sub(r',\s*]', ']', json_str)   # Remove trailing commas in arrays
                        try:
                            return json.loads(json_str)
                        except json.JSONDecodeError:
                            if attempt == max_retries - 1:  # Last attempt
                                return {"error": f"JSON parsing failed: {je}", "raw_response": text}
                            else:
                                raise je
                else:
                    if attempt == max_retries - 1:  # Last attempt
                        return {"error": "No JSON found in response", "raw_response": text}
                    else:
                        raise ValueError("No JSON found in response")
            
            return text
            
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()
            
            # Determine if this is a retryable error
            retryable_errors = [
                "rate limit", "quota", "timeout", "connection", 
                "service unavailable", "internal error", "500", "502", "503", "504"
            ]
            
            is_retryable = any(err in error_msg for err in retryable_errors)
            
            if attempt < max_retries - 1 and is_retryable:
                # Calculate exponential backoff delay
                delay = retry_delay * (2 ** attempt)
                print(f"LLM API attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
                continue
            else:
                # Non-retryable error or final attempt
                break
    
    # All retries exhausted
    error_response = f"LLM API failed after {max_retries} attempts: {last_error}"
    return {"error": error_response} if is_json else error_response

def brand_profile_from_pages(brand_hint: str, pages: list, industry: str, audience: str) -> dict:
    context = "\n".join([f"URL: {p.get('url','')}\nTEXT: {(p.get('text') or '')[:1000]}" for p in pages[:10]])
    prompt = f"""
역할: 당신은 주어진 웹사이트 콘텐츠를 분석하여 브랜드의 정체성을 파악하는 전문 브랜드 분석가입니다.

[분석 정보]
- 분석 대상 브랜드 힌트: '{brand_hint}'
- 산업: '{industry}'
- 타겟 고객: '{audience}'

[작업 지시]
아래 '입력 콘텐츠'를 바탕으로 브랜드의 핵심 정체성을 추출하여, 지정된 JSON 형식으로만 답변해주세요.

[입력 콘텐츠]
{context}

[출력 JSON 형식]
{{
  "brand": "분석을 통해 감지된 최종 브랜드 이름",
  "products_services": ["주요 제품 및 서비스 목록 (리스트)"],
  "key_messages": ["핵심 마케팅 메시지 또는 슬로건 목록 (리스트)"],
  "audience_clues": ["타겟 고객에 대한 단서 목록 (리스트)"]
}}
"""
    return get_llm_response(prompt)

def verify_official_site(content: str, brand_name: str) -> bool:
    """
    주어진 콘텐츠가 특정 브랜드의 공식 사이트인지 LLM을 통해 확인하고,
    판단의 근거까지 추론하도록 하여 정확도를 높입니다.
    """
    if not USE_LLM: return True

    prompt = f"""
[CONTEXT]
{content[:2500]}

[TASK]
Analyze the CONTEXT provided above. Does it seem to be from the official homepage for the brand '{brand_name}'?
Consider elements like copyright notices, official product listings, company information, etc.
Respond in JSON format with two keys: "is_official" (boolean) and "reason" (a brief explanation in Korean).

Example Response:
{{
  "is_official": true,
  "reason": "콘텐츠 하단에 '웅진씽크빅' 저작권 정보가 명시되어 있으며, '스마트올' 등 주요 제품을 소개하고 있습니다."
}}
"""
    response = get_llm_response(prompt, is_json=True)
    
    # 응답이 유효하고, is_official이 True일 때만 검증 성공으로 간주
    if response and not response.get("error") and response.get("is_official") is True:
        return True
    
    return False

def summarize_and_extract_insights(docs: list, topic: str, industry: str, audience: str) -> dict:
    # Data quality check first
    MIN_TEXT_LENGTH = 2000 # minimum total text length for analysis
    
    total_content = "".join([d.get("content", "") for d in docs])
    
    if len(total_content) < MIN_TEXT_LENGTH:
        return {
            "error": "InsufficientData",
            "message": f"분석에 필요한 최소한의 데이터({MIN_TEXT_LENGTH}자)를 수집하지 못했습니다. (현재 {len(total_content)}자)",
            "insights": [
                {
                    "insight": "데이터 부족으로 분석 불가",
                    "quote": "수집된 문서의 양이 너무 적어 유의미한 인사이트를 도출할 수 없습니다.",
                    "source_url": ""
                }
            ],
            "collected_sources": [doc.get("url") for doc in docs]
        }

    if not USE_LLM or not docs:
        return {"summary_bullets": [], "insights": []}

    context_str = ""
    for i, d in enumerate(docs[:20]):
        context_str += f"[문서 {i+1}] (URL: {d.get('url', '')})\n- 제목: {d.get('title', '')}\n- 내용: {(d.get('content', '') or '')[:500]}\n\n"

    prompt = f"""
역할: 당신은 사실 기반(Fact-based) 분석가입니다. 주어진 여러 문서에서 주장을 뒷받침하는 '정확한 인용구'를 찾아내는 것이 당신의 핵심 임무입니다.

[분석 정보]
- 조사 주제: {topic}
- 산업: {industry}
- 타겟 고객: {audience}

[입력 자료]
{context_str}

[작업 지시]
입력 자료를 바탕으로, {topic}에 대한 중요한 인사이트를 2~3개 추출하세요.
**각 인사이트는 반드시 입력 자료에 나온 '정확한 문장(인용구)'과 해당 문장이 출처인 'URL'을 근거로 제시해야 합니다.**

[출력 JSON 형식]
{{
  "insights": [
    {{
      "insight": "도출된 인사이트 또는 주장 요약",
      "quote": "주장을 뒷받침하는 원본 문서의 핵심 문장 (복사-붙여넣기)",
      "source_url": "해당 문장이 포함된 문서의 URL"
    }}
  ]
}}
"""
    return get_llm_response(prompt)

def generate_comparison_table(main_profile: dict, competitor_profiles: list, industry: str, audience: str) -> str:
    # LLM에게 전달할 데이터를 더 명확하게 구조화
    all_profiles = [main_profile] + competitor_profiles
    profiles_summary = json.dumps(all_profiles, ensure_ascii=False, indent=2)
    
    prompt = f"""
역할: 당신은 전문 시장 분석가입니다. 주어진 여러 브랜드의 구조화된 프로필 데이터를 바탕으로 최종 비교 분석표를 Markdown 형식으로 작성합니다.

[분석 대상 프로필 데이터 (JSON)]
{profiles_summary}

[작업 지시]
위 JSON 데이터를 바탕으로, 아래 각 항목에 대한 Markdown 비교표를 생성하세요.
- **브랜드 포지션**: 'brand_position' 값을 사용하세요.
- **가격대**: 'price_range' 값을 사용하세요.
- **주요 제품군**: 'key_products' 리스트를 보기 좋게 요약하세요.
- **주요 기능/USP**: 'key_features' 값을 사용하세요.
- **시장 인지도**: 'market_awareness' 값을 간결하게 요약하세요.
- **소비자 이미지**: 'consumer_image' 값을 간결하게 요약하세요.

- 표의 첫 번째 열은 반드시 '구분'이어야 합니다.
- 각 브랜드는 표의 열(column)을 차지해야 합니다.
- 각 칸의 내용은 핵심만 간결하게 표현해주세요.
"""
    return get_llm_response(prompt, is_json=False)

def ontology_for(industry: str, audience: str, product_industry: str, on_k: int = 20) -> dict:
    keys = ["vocab", "synonyms", "entities", "questions", "competitor_corporate_and_brand_name"]
    prompt = f'역할: 당신은 \'{industry}\' 산업의 전문 온톨로지 설계자입니다.\n타겟 고객: \'{audience}\'\n핵심 제품군: \'{product_industry}\'\n[작업 지시]\n위 정보를 바탕으로, 아래 각 항목에 대해 연관성이 높은 한국어 단어를 추출해주세요.\n- \'competitor_corporate_and_brand_name\' 항목에는 \'{product_industry}\' 제품군 내의 주요 경쟁사 브랜드 이름을 5~7개 추출해주세요.\n- 나머지 항목은 {on_k}개씩 추출해주세요.\n[출력 JSON 형식]\n{{\n  "vocab": ["업계 전문 용어..."],\n  "synonyms": ["제품/서비스 관련 동의어..."],\n  "entities": ["주요 인물, 회사, 이벤트 등..."],\n  "questions": ["타겟 고객이 가질만한 질문..."],\n  "competitor_corporate_and_brand_name": ["경쟁사 브랜드명..."]\n}}'
    response = get_llm_response(prompt)
    if "error" in response: return {key: [] for key in keys}
    for key in keys: response.setdefault(key, [])
    return response

def synthesize_brand_analysis(brand_name: str, site_profile: dict, market_awareness: dict, consumer_image: str) -> dict:
    """
    수집된 모든 데이터를 종합하여, 예시 리포트 수준의 최종 브랜드 분석을 생성합니다.
    """
    # market_awareness 딕셔너리에서 인사이트 텍스트만 추출
    awareness_insights = "\n".join([f"- {item.get('insight', '')}" for item in market_awareness.get("insights", [])])

    prompt = f"""
역할: 당신은 대한민국 소비재 시장의 수석 애널리스트입니다. 수집된 모든 원본 데이터를 바탕으로, '{brand_name}' 브랜드에 대한 최종 분석 프로필을 작성해주세요. 각 항목은 전문가의 시각에서 분석된, 깊이 있고 정제된 내용이어야 합니다.

[입력 데이터]
1. 웹사이트 프로필: {site_profile}
2. 시장 인지도 (뉴스 기반 요약): {awareness_insights}
3. 소비자 이미지 (SNS 기반 요약): {consumer_image}

[작업 지시]
위 입력 데이터를 종합적으로 분석하여, 아래 JSON 형식에 맞춰 각 항목의 내용을 작성해주세요.

[출력 JSON 형식]
{{
  "consumer_perspective": "웹사이트 프로필의 제품 정보와 소비자 이미지를 종합하여, 소비자들이 브랜드를 어떻게 인식하는지 상세히 분석. (장점, 단점, 핵심 구매 요인 등 포함)",
  "market_perception": "시장 인지도(뉴스)와 웹사이트 프로필을 바탕으로, 시장 전체에서 이 브랜드가 어떤 위치를 차지하고 있는지 분석. (전문가용, 대중용, 혁신적, 가성비 등)",
  "ad_key_messages": "웹사이트 프로필의 핵심 메시지와 소비자 이미지 등을 바탕으로, 현재 사용하고 있는 주요 광고/키 메시지를 2~3개 추출하여 요약."
}}
"""
    return get_llm_response(prompt)