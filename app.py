import streamlit as st
import os
import re
import json
import pandas as pd
from dotenv import load_dotenv
from main_agent import run_research_v3

# .env 파일에서 API 키를 로드합니다.
load_dotenv()

st.set_page_config(page_title="리서치 에이전트", page_icon="🧭", layout="wide")
st.title("🧭 대화형 브랜드 리서치 에이전트")

# --- Session State 초기화 ---
if 'step' not in st.session_state: st.session_state.step = 0
if 'user_inputs' not in st.session_state: st.session_state.user_inputs = {}
if 'result_data' not in st.session_state: st.session_state.result_data = None

# --- 콜백 & 사이드바 ---
def progress_callback(evt, payload):
    log_entry = f"- **{evt}**: {json.dumps(payload, ensure_ascii=False, default=str)}"
    log_container.markdown(log_entry, unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 설정")
    # .env 파일에 저장된 키를 기본값으로 사용합니다.
    g_api_key = st.text_input("GEMINI API 키", type="password", value=os.environ.get("GEMINI_API_KEY", ""))
    t_api_key = st.text_input("TAVILY API 키 (선택)", type="password", value=os.environ.get("TAVILY_API_KEY", ""))
    if g_api_key: os.environ["GEMINI_API_KEY"] = g_api_key
    if t_api_key: os.environ["TAVILY_API_KEY"] = t_api_key
    
    st.divider()
    st.header("🔍 검색 엔진 설정")
    preferred_provider = st.selectbox("선호 검색 엔진", ["ddg", "tavily"], index=1)
    per_cap = st.slider("쿼리당 수집 개수", 3, 10, 5, 1)
    min_keep_threshold = st.slider("최소 유지 개수 (Fallback 기준)", 1, 10, 3, 1)
    
    st.divider()
    st.header("🔬 진행 로그")
    log_container = st.container(height=300)

def reset_session():
    st.session_state.step = 0
    st.session_state.user_inputs = {}
    st.session_state.result_data = None
    st.rerun()

# --- 메인 패널 로직 ---

# 최종 결과가 있으면 결과 화면을 먼저 표시
if st.session_state.get('result_data'):
    res = st.session_state.result_data
    st.success("✅ 리서치 완료!")
    if st.button("🔄 새로운 리서치 시작", use_container_width=True):
        reset_session()

    # --- 결과 표시 섹션 ---
    st.header("📊 경쟁사 비교 분석")
    st.markdown(res.get("competitor_comparison_table", "생성된 비교표가 없습니다."))

    st.header("🛒 SSG.COM 판매 순위 분석 (주요 제품)")
    shopping_data_wrapper = res.get("shopping_data", {})
    if "error" in shopping_data_wrapper:
        st.info("쇼핑 데이터 분석 중 오류가 발생했습니다.")
        with st.expander("오류 상세 내용 보기"):
            st.error(shopping_data_wrapper.get("error"))
    else:
        shopping_analysis = shopping_data_wrapper.get("main_product_analysis", {})
        results = shopping_analysis.get("top_10_results", [])
        if results and isinstance(results, list) and (len(results) == 0 or "error" not in results[0]):
            st.subheader(f"'{shopping_analysis.get('product_name')}' 판매순 TOP 10")
            df = pd.DataFrame(results)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("SSG.COM에서 유의미한 상품 순위 데이터를 수집하지 못했습니다.")
            if results and isinstance(results, list) and len(results) > 0 and "error" in results[0]:
                with st.expander("오류 상세 내용 보기"):
                    st.warning(results[0].get("error"))

    st.header("🏢 브랜드 프로필 (자사)")
    st.json(res.get("brand_profile", {}))

    with st.expander("📰 뉴스 분석 및 인사이트 (자사)", expanded=False):
        brand_name = res.get("brand_profile", {}).get("brand", "brand")
        news_analysis = res.get("news_analysis", {})
        raw_docs = res.get("raw_news_docs", [])
        st.subheader("💡 LLM 요약 및 인사이트")
        insights = news_analysis.get("insights", [])
        if insights and "error" not in news_analysis:
            for item in insights:
                quote = item.get('quote', '')
                fragment_url = f"{item.get('source_url', '')}#:~:text={quote[:50]}" if quote else item.get('source_url', '')
                st.markdown(f"**- {item.get('insight', '')}**")
                st.caption(f"> {quote} [🔗Source]({fragment_url})")
        else:
            st.warning("뉴스에서 유의미한 인사이트를 추출하지 못했습니다.")
            st.json(news_analysis)
        st.divider()
        st.subheader("📥 수집된 뉴스 기사 목록")
        if raw_docs:
            docs_str = "\n".join([json.dumps(doc, ensure_ascii=False) for doc in raw_docs])
            st.download_button(label="뉴스 원본 데이터 다운로드 (.jsonl)", data=docs_str, file_name=f"{brand_name}_news_docs.jsonl", mime="application/jsonl")
            df_news = pd.DataFrame(raw_docs)
            for col in ["title", "source", "url"]:
                if col not in df_news.columns: df_news[col] = None
            st.dataframe(df_news[["title", "source", "url"]].head(), use_container_width=True, hide_index=True)
        else:
            st.info("수집된 뉴스 기사가 없습니다.")

    with st.expander("경쟁사 개별 프로필 (Raw 데이터)"):
        st.json(res.get("competitor_profiles", []))
    with st.expander("전체 리포트 원본 (JSON)"):
        st.json(res)

# 결과가 없으면 대화형 UI를 단계별로 표시
else:
    if st.session_state.step == 0:
        st.subheader("안녕하세요! 어떤 브랜드에 대해 리서치를 시작할까요?")
        with st.form(key="step0_form"):
            brand_input = st.text_input("브랜드 이름 또는 공식 웹사이트 URL을 입력해주세요.", key="brand_input")
            if st.form_submit_button("다음", use_container_width=True):
                if brand_input.strip():
                    st.session_state.user_inputs['seed'] = brand_input.strip()
                    st.session_state.step = 1
                    st.rerun()
                else:
                    st.warning("브랜드 이름이나 URL을 입력해주세요.")
    elif st.session_state.step == 1:
        st.info(f"분석 대상: **{st.session_state.user_inputs['seed']}**")
        st.subheader("어느 산업 분야에 속하나요?")
        with st.form(key="step1_form"):
            industry_input = st.text_input("산업군을 입력해주세요. (예: 뷰티/헤어)", key="industry_input")
            if st.form_submit_button("다음", use_container_width=True):
                if industry_input.strip():
                    st.session_state.user_inputs['industry'] = industry_input.strip()
                    st.session_state.step = 2
                    st.rerun()
                else:
                    st.warning("산업군을 입력해주세요.")
    elif st.session_state.step == 2:
        st.info(f"분석 대상: **{st.session_state.user_inputs['seed']}** (산업: {st.session_state.user_inputs['industry']})")
        st.subheader("특별히 집중해서 볼 타겟 고객이 있나요?")
        with st.form(key="step2_form"):
            audience_input = st.text_input("타겟 고객을 구체적으로 알려주세요.", key="audience_input")
            if st.form_submit_button("다음", use_container_width=True):
                if audience_input.strip():
                    st.session_state.user_inputs['audience'] = audience_input.strip()
                    st.session_state.step = 3
                    st.rerun()
                else:
                    st.warning("타겟 고객을 입력해주세요.")
    elif st.session_state.step == 3:
        st.info(f"분석 대상: ... 고객: {st.session_state.user_inputs['audience']}")
        st.subheader("분석할 경쟁사를 알려주세요.")
        with st.form(key="step3_form"):
            competitor_input = st.text_input("경쟁사 이름을 쉼표(,)로 구분하여 입력하세요.", value="다이슨, 보다나, 유닉스")
            if st.form_submit_button("계획 확인하기", use_container_width=True):
                st.session_state.user_inputs['competitors'] = [c.strip() for c in competitor_input.split(',') if c.strip()]
                st.session_state.step = 4
                st.rerun()
    elif st.session_state.step == 4:
        st.subheader("📝 리서치 계획을 확인해주세요.")
        st.json(st.session_state.user_inputs)
        st.markdown("---")
        cols = st.columns(2)
        if cols[0].button("🚀 네, 리서치 실행", type="primary", use_container_width=True):
            log_container.empty()
            st.info("🚀 리서치를 진행 중입니다... 사이드바에서 진행 로그를 확인하세요.")
            with st.spinner("Running main research pipeline... This may take a few minutes."):
                try:
                    res = run_research_v3(
                        seed_url=st.session_state.user_inputs.get("seed"),
                        industry=st.session_state.user_inputs.get("industry"),
                        audience=st.session_state.user_inputs.get("audience"),
                        keywords=[],  # 키워드 입력을 따로 안받으니 빈 리스트
                        competitor_list=st.session_state.user_inputs.get("competitors", []),
                        per_query_cap=per_cap,
                        preferred_provider=preferred_provider,
                        min_keep_threshold=min_keep_threshold,
                        progress=progress_callback
                    )
                    st.session_state.result_data = res
                    st.rerun()
                except Exception as e:
                    st.exception(e)
        if cols[1].button("🔄 처음부터 다시", use_container_width=True):
            reset_session()
