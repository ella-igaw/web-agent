# modules/auto_analyzer.py
import re
import json
from .llm_services import get_llm_response, USE_LLM

def analyze_layout_and_get_selectors(html_content: str, user_hint: str = "main product list") -> dict:
    """
    LLM을 사용하여 HTML 구조를 분석하고, 반복되는 데이터 목록을 추출하기 위한
    동적 CSS 선택자를 생성합니다.
    """
    if not USE_LLM:
        return {"error": "LLM is required for auto analysis."}

    # HTML의 불필요한 부분을 제거하여 LLM에 더 깨끗한 데이터를 제공합니다.
    cleaned_html = re.sub(r'<(script|style|svg).*?>.*?</\1>', '', html_content, flags=re.DOTALL)
    cleaned_html = re.sub(r'\s{2,}', ' ', cleaned_html) #
    
    prompt = f"""
역할: 당신은 웹페이지의 HTML 구조를 분석하여, 반복되는 데이터 목록을 찾아내는 전문 웹 스크레이핑 AI입니다. 당신의 임무는 사람이 직접 CSS 선택자를 찾는 과정을 자동화하는 것입니다.

[분석 목표]
사용자는 이 페이지에서 '{user_hint}'에 해당하는 데이터 목록을 찾고 싶어합니다.

[작업 지시]
아래 제공된 HTML 코드에서, 사용자의 분석 목표에 가장 부합하는 **핵심적인 반복 데이터 목록**(예: 상품 목록, 게시글 목록)을 하나만 찾아내세요.
그리고 그 목록에서 **각 아이템**과, 각 아이템 내부의 **핵심 정보(예: 이름, 가격, 브랜드, 링크)**를 추출할 수 있는, 가장 안정적이고 의미있는 **CSS 선택자**를 JSON 형식으로 알려주세요.
'css-...' 와 같이 컴퓨터가 생성한 불안정한 클래스 이름 대신, 'product_item' 처럼 의미있는 클래스 이름을 우선적으로 사용해야 합니다.

[입력 HTML (일부)]
{cleaned_html[:8000]} 

[출력 JSON 형식]
{{
  "list_item_selector": "각 아이템 하나하나를 감싸는 가장 가까운 부모 요소의 CSS 선택자. (예: li.product_item)",
  "fields": {{
    "title": "아이템 내에서 '제목'에 해당하는 가장 적절한 CSS 선택자",
    "price": "아이템 내에서 '가격'에 해당하는 가장 적절한 CSS 선택자",
    "brand": "아이템 내에서 '브랜드'에 해당하는 가장 적절한 CSS 선택자 (없으면 null)",
    "url": "아이템 내에서 '상세 페이지 링크'에 해당하는 a 태그의 CSS 선택자",
    "image_url": "아이템 내에서 '대표 이미지'에 해당하는 img 태그의 CSS 선택자 (없으면 null)"
  }}
}}
"""
    return get_llm_response(prompt)