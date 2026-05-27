import streamlit as st
import os
import requests
import re
import html
import json
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from dotenv import load_dotenv

# ==========================================
# 0. .env 파일 및 초기 로컬 히스토리 세팅
# ==========================================
load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"
HISTORY_FILE = "chat_history.json"

# 로컬 히스토리 파일 읽기/쓰기 함수
def load_all_history() -> dict:
    """로컬 JSON 파일에서 모든 과거 대화 내역을 불러옵니다."""
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_current_history(session_id: str, stock_name: str, news_context: str, chat_history: list, news_context_raw: list = None, risks: list = None):
    """현재 진행 중인 대화 내역을 로컬 JSON 파일에 실시간 저장합니다."""
    if not session_id:
        return
    all_hist = load_all_history()
    all_hist[session_id] = {
        "stock_name": stock_name,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "news_context": news_context,
        "news_context_raw": news_context_raw if news_context_raw is not None else [],
        "risks": risks if risks is not None else [],
        "chat_history": chat_history
    }
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(all_hist, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print("히스토리 저장 오류:", e)

# Session State 초기화
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "news_context" not in st.session_state:
    st.session_state["news_context"] = ""
if "news_context_raw" not in st.session_state:
    st.session_state["news_context_raw"] = []
if "risks" not in st.session_state:
    st.session_state["risks"] = []
if "current_stock" not in st.session_state:
    st.session_state["current_stock"] = ""
if "session_id" not in st.session_state:
    st.session_state["session_id"] = ""

# ==========================================
# 1. 패키지 임포트 및 Fallback 처리
# ==========================================
try:
    import google.generativeai as genai
    HAS_GENAI = True
except Exception as e:
    HAS_GENAI = False
    print("Google GenAI SDK 임포트 실패:", e)

# ==========================================
# 2. HTML 태그 정제 헬퍼 함수
# ==========================================
def clean_html(text: str) -> str:
    """네이버 API 결과에 포함된 HTML 태그 및 특수문자를 정제합니다."""
    clean_re = re.compile('<.*?>')
    cleaned_text = re.sub(clean_re, '', text)
    return html.unescape(cleaned_text)

# ==========================================
# 3. 네이버 뉴스 API 검색 함수
# ==========================================
def search_naver_news(query: str) -> str:
    """네이버 뉴스 검색 API를 호출하여 상위 5개의 기사 제목과 설명을 가져옵니다."""
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        return "오류: .env 파일에 NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET이 설정되지 않았습니다."

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }
    params = {
        "query": query,
        "display": 5,
        "sort": "sim"  # "date"(최신순) 대신 "sim"(정확도/유사도순)으로 변경하여 잡다한 증권 브리핑/CF 뉴스를 거르고 진짜 종목 뉴스를 우선 수집합니다.
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            items = data.get("items", [])
            if not items:
                return f"'{query}'에 대한 최신 검색 결과가 없습니다."
            
            result_texts = []
            for i, item in enumerate(items, 1):
                title = clean_html(item.get("title", ""))
                description = clean_html(item.get("description", ""))
                link = item.get("link", "")
                pub_date = item.get("pubDate", "")
                # 원문 하이퍼링크 문자열 결합
                link_str = f" [🔗 원문 링크]({link})" if link else ""
                result_texts.append(f"[{i}] {title}{link_str}\n- 요약: {description}\n- 작성일: {pub_date}")
            
            news_text = "\n\n".join(result_texts)
            st.session_state["news_context"] = news_text
            return news_text
        else:
            return f"네이버 뉴스 API 호출 실패 (상태 코드: {response.status_code}, 메시지: {response.text})"
    except Exception as e:
        return f"네이버 뉴스 검색 중 예외 발생: {str(e)}"

# ==========================================
# 4. 5단계 에이전트 주식 분석 파이프라인 함수
# ==========================================

def get_jaccard_similarity(str1: str, str2: str) -> float:
    """두 문자열의 자카드 유사도를 계산합니다."""
    s1 = set(str1)
    s2 = set(str2)
    if not s1 and not s2:
        return 1.0
    return len(s1.intersection(s2)) / len(s1.union(s2))

def collect_news(query: str) -> list:
    """네이버 뉴스 검색 API를 호출하여 최신성과 정확성을 모두 잡기 위해 sim 및 date 정렬 결과를 조합하여 수집합니다."""
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }
    
    # 최신성과 연관도를 모두 확보하기 위해 두 가지 정렬 방식으로 수집
    news_dict = {}
    for sort_type in ["sim", "date"]:
        params = {
            "query": query,
            "display": 15,
            "sort": sort_type
        }
        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                items = data.get("items", [])
                for item in items:
                    link = item.get("link", "")
                    if link not in news_dict:
                        news_dict[link] = {
                            "title": clean_html(item.get("title", "")),
                            "description": clean_html(item.get("description", "")),
                            "link": link,
                            "pub_date": item.get("pubDate", "")
                        }
        except Exception as e:
            print(f"뉴스 수집 오류 ({sort_type}):", e)

    return list(news_dict.values())

def filter_news(news_list: list) -> list:
    """제목/요약이 너무 짧은 기사, 수집된 뉴스 중 가장 최신 뉴스 기준 14일 이상 지난 오래된 뉴스 및 중복 뉴스를 필터링합니다."""
    filtered = []
    
    # 1. 수집된 뉴스 중 가장 최신 뉴스 날짜 찾기 (시스템 시각 왜곡 및 가상 연도 이슈 방어)
    latest_dt = None
    parsed_news_list = []
    
    for news in news_list:
        pub_date_str = news.get("pub_date", "").strip()
        pub_dt = None
        if pub_date_str:
            try:
                pub_dt = parsedate_to_datetime(pub_date_str)
                if latest_dt is None or pub_dt > latest_dt:
                    latest_dt = pub_dt
            except Exception:
                pass
        parsed_news_list.append((news, pub_dt))
        
    # 날짜 파싱이 모두 실패한 경우에만 로컬 시각을 기본값으로 사용
    if latest_dt is None:
        latest_dt = datetime.now()
    
    seen_keys = set()
    
    for news, pub_dt in parsed_news_list:
        title = news.get("title", "").strip()
        description = news.get("description", "").strip()
        link = news.get("link", "").strip()
        
        # 1. 저품질 뉴스 필터링 (길이 기반 제한)
        # - 제목 8자 미만 제외, 본문 요약 20자 미만 제외
        if len(title) < 8 or len(description) < 20:
            continue
            
        # 2. 날짜 필터링: 가장 최신 기사 시점 대비 14일보다 오래된 뉴스는 분석 잡음 제거를 위해 걸러냄
        if pub_dt:
            delta = latest_dt - pub_dt
            if delta.days > 14:  # 가장 최신 기사 대비 14일 초과 뉴스 제외
                continue
        
        # 3. 중복 뉴스 제거 (고유 키 생성 기반)
        # dedupe key 생성 공식: netloc + path + normalized_title[:40]
        try:
            parsed_url = urlparse(link)
            normalized_title = "".join(title.lower().split())
            dedupe_key = parsed_url.netloc + parsed_url.path + normalized_title[:40]
        except Exception:
            dedupe_key = link + title
            
        if dedupe_key in seen_keys:
            continue
            
        seen_keys.add(dedupe_key)
        filtered.append(news)
            
    # 최종적으로 최대 10건만 분석 대상으로 반환
    return filtered[:10]

def analyze_sentiments(news_list: list, active_google_key: str) -> list:
    """각 뉴스에 대해 Gemini를 사용해 호재/악재/중립 및 근거를 분석합니다."""
    genai.configure(api_key=active_google_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    
    analyzed_news = []
    for news in news_list:
        prompt = f"""당신은 전문 금융 감성 분석가입니다. 아래 제공되는 기사의 제목과 요약을 분석하여, 이 뉴스가 해당 기업의 주가에 미칠 영향을 "호재", "악재", "중립" 중 하나로 평가하고 그 구체적인 근거를 한국어로 설명해 주세요.
        
[기사 정보]
제목: {news['title']}
요약: {news['description']}

반드시 아래 형식의 JSON 객체로만 응답해 주세요. 추가적인 설명이나 텍스트는 출력하지 마세요:
{{
  "sentiment": "호재" | "악재" | "중립",
  "reason": "평가한 구체적인 근거(한글 문장)"
}}"""
        try:
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            data = json.loads(response.text.strip())
            news_copy = news.copy()
            news_copy["sentiment"] = data.get("sentiment", "중립")
            news_copy["reason"] = data.get("reason", "분석 불가")
            analyzed_news.append(news_copy)
        except Exception as e:
            news_copy = news.copy()
            news_copy["sentiment"] = "중립"
            news_copy["reason"] = f"감성 분석 오류: {str(e)}"
            analyzed_news.append(news_copy)
            
    return analyzed_news

def analyze_risks(news_list: list, active_google_key: str) -> list:
    """전체 뉴스 및 분석 결과를 바탕으로 투자자가 주의해야 할 리스크 3~5가지를 도출합니다."""
    genai.configure(api_key=active_google_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    
    news_summary = []
    for i, news in enumerate(news_list, 1):
        news_summary.append(f"[{i}] {news['title']}\n- 감성: {news['sentiment']}\n- 근거: {news['reason']}")
    news_summary_str = "\n\n".join(news_summary)
    
    prompt = f"""당신은 리스크 관리 전문가입니다. 다음 수집된 뉴스 및 개별 감성 분석 결과들을 분석하여, 투자자가 해당 종목에 투자할 때 직면할 수 있는 투자 리스크 요인을 최소 3가지에서 최대 5가지 도출해 주세요. 거시경제(Macro), 기업 실적, 경쟁 구도, 주가 변동성 등의 관점을 반영하여 구체적으로 작성해야 합니다.

[뉴스 및 분석 데이터]
{news_summary_str}

반드시 아래 형식의 JSON 객체로만 응답해 주세요. 추가적인 설명이나 텍스트는 출력하지 마세요:
{{
  "risks": [
    "리스크 요인 1 (구체적인 영향 및 이유 포함)",
    "리스크 요인 2 ...",
    ...
  ]
}}"""
    try:
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        data = json.loads(response.text.strip())
        return data.get("risks", ["추출된 리스크 요인이 없습니다."])
    except Exception as e:
        return [f"리스크 분석 중 오류 발생: {str(e)}"]

def _sanitize_recommendations(text: str) -> str:
    """금융 심의 필터링: 투자 권유성 단어를 중립적인 분석 단어로 순화합니다."""
    replacements = {
        "강력 매수": "매우 긍정적 전망",
        "매수 추천": "관심 종목 분석",
        "매수 권유": "관심 요인 제시",
        "매수를 권장": "긍정적으로 평가",
        "매수 요인": "호재 요인",
        "매도 요인": "리스크 요인",
        "매수를 유도": "판단을 보조",
        "매도 추천": "보수적인 접근",
        "투자 추천": "투자 검토",
        "매수할 것": "진입을 신중히 검토할 것",
        "매도할 것": "비중 조절을 신중히 검토할 것"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

def generate_briefing(news_list: list, risks: list, stock_name: str, active_google_key: str) -> str:
    """뉴스 분석, 감성 분석, 리스크 요소를 종합하여 최종적인 보고서 형태의 브리핑 원고를 작성합니다."""
    genai.configure(api_key=active_google_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    
    news_summary = []
    for i, news in enumerate(news_list, 1):
        news_summary.append(f"[{i}] {news['title']}\n- 감성: {news['sentiment']}\n- 분석 근거: {news['reason']}")
    news_summary_str = "\n\n".join(news_summary)
    
    risks_str = "\n".join([f"- {risk}" for risk in risks])
    
    prompt = f"""당신은 전문 금융 분석가입니다. 수집된 뉴스 및 감성 분석 결과와 투자 리스크 요인을 종합하여 해당 종목에 대한 투자 요약 브리핑 리포트를 작성해 주세요.
작성 시 전문적이고 객관적인 톤을 유지해야 합니다.

[종목명]
{stock_name}

[뉴스 및 감성 분석 요약]
{news_summary_str}

[도출된 투자 리스크]
{risks_str}

[작성 지침]
- 반드시 한국어로 구조화하여 마크다운 양식으로 작성해 주세요.
- 다음 항목을 포함해야 합니다:
  1. **뉴스 분석 요약**: 최근 수집된 뉴스들의 핵심 트렌드를 종합 설명합니다.
  2. **호재와 악재**: 주요 호재 요인과 악재 요인을 일목요연하게 정리합니다.
  3. **투자 리스크 전망**: 분석된 리스크 요인이 향후 주가나 기업에 미칠 잠재적 영향을 종합적으로 분석합니다.
  4. **최종 브리핑 요약**: 투자자 관점의 핵심 메시지를 3줄 요약하여 서술합니다.
- (주의: "매수", "매도", "추천", "강력 추천" 등 투자 권유를 나타내는 직접적인 표현은 사용하지 마십시오.)

최종 보고서 작성 시작:"""
    try:
        response = model.generate_content(prompt)
        briefing = response.text.strip()
        
        # 금융 심의 필터 적용
        briefing = _sanitize_recommendations(briefing)
        
        # 투자 책임 면책 조항 부착
        disclaimer = """
---
⚠️ **면책조항 (DISCLAIMER)**: 본 브리핑은 수집된 뉴스 데이터 및 AI 분석을 기반으로 제공되는 단순 참고용 정보이며, 특정 종목에 대한 투자 권유나 추천이 아닙니다. 모든 투자 의사결정은 투자자 본인의 판단과 책임 하에 이루어져야 하며, 본 정보의 오류나 누락으로 인한 투자 결과에 대해 어떠한 법적 책임도 지지 않습니다."""
        
        return briefing + disclaimer
    except Exception as e:
        return f"브리핑 생성 중 오류 발생: {str(e)}"

# ==========================================
# 5. Gemini SDK 직접 실행 함수 (후속 질문용)
# ==========================================
def run_direct_gemini_chat(user_question: str, active_google_key: str, model_name: str) -> str:
    """수집된 뉴스 정보 및 대화 맥락을 기반으로 추가 후속 질문에 대답하는 챗봇 함수입니다."""
    genai.configure(api_key=active_google_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""당신은 전문 주식 투자 분석 에이전트입니다.
사용자가 수집된 최근 뉴스 정보 및 기존 대화 맥락을 기반으로 후속 질문을 하고 있습니다. 이에 대해 친절하고 전문적으로 한국어로 답변해 주세요.

[수집된 뉴스 정보]
{st.session_state.get("news_context", "")}

[이전 대화 기록]
"""
    for msg in st.session_state["chat_history"]:
        prompt += f"{msg['role'].upper()}: {msg['content']}\n"
        
    prompt += f"""
USER: {user_question}
ASSISTANT:"""
    
    response = model.generate_content(prompt)
    return response.text

# ==========================================
# 6. Streamlit Web UI 구현
# ==========================================
st.set_page_config(page_title="Stock-Agent: AI 투자 뉴스 비서", page_icon="📈", layout="centered")

# CSS 스타일
st.markdown("""
    <style>
    /* 1. 상단 헤더 및 Deploy 버튼 감추기 */
    header[data-testid="stHeader"] {
        visibility: hidden;
        height: 0px;
    }
    div[data-testid="stDecorator"] {
        display: none;
    }
    
    /* 2. 네이버 스타일 전체 폰트 및 배경 톤 설정 */
    html, body, .stApp, 
    div[data-testid="stAppViewContainer"], 
    div[data-testid="stAppViewBlockContainer"], 
    div[data-testid="stMain"] {
        background-color: #F8F9FA !important;
    }
    
    /* 3. 타이틀 영역 */
    .main-title {
        font-size: 2.1rem;
        font-weight: 800;
        color: #03C75A; /* NAVER Green */
        margin-bottom: 0.3rem;
        font-family: 'NanumSquare', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .sub-title {
        font-size: 1.0rem;
        color: #555555;
        margin-bottom: 2rem;
    }
    
    /* 4. 입력박스 테두리 네이버 그린 포커스 적용 */
    div[data-baseweb="input"] {
        border-radius: 6px !important;
        border: 1px solid #D2D6DA !important;
        background-color: #FFFFFF !important;
        transition: border-color 0.2s ease !important;
    }
    div[data-baseweb="input"]:focus-within {
        border-color: #03C75A !important;
        box-shadow: 0 0 0 1px #03C75A !important;
    }
    
    /* 5. 분석 시작 버튼을 네이버 그린 버튼으로 커스텀 */
    div.stButton > button {
        background-color: #03C75A !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 6px !important;
        padding: 0.6rem 1.5rem !important;
        font-weight: 700 !important;
        font-size: 1.05rem !important;
        width: 100% !important;
        box-shadow: 0 2px 4px rgba(3, 199, 90, 0.15) !important;
        transition: background-color 0.15s ease, transform 0.1s ease !important;
    }
    div.stButton > button:hover {
        background-color: #17B75E !important;
        color: #FFFFFF !important;
        transform: translateY(-1px);
    }
    div.stButton > button:active {
        transform: translateY(1px);
    }

    /* 6. 네이버 금융 리서치 카드 스타일 분석 결과 컨테이너 */
    .brief-container {
        background-color: #FFFFFF;
        padding: 1.5rem;
        border-radius: 10px;
        border: 1px solid #E4E8EB;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
        border-left: 6px solid #03C75A;
        color: #1E1E23;
        line-height: 1.7;
        margin-top: 1rem;
        margin-bottom: 1rem;
        font-size: 0.98rem;
    }
    
    /* 7. 사이드바 디자인 리폼 (글씨체 검은색 강조) */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #ECEFF1 !important;
    }
    /* 사이드바 내부 모든 텍스트(제목, 마크다운, 버튼 글자 등)를 짙은 검은색으로 강제 설정 */
    section[data-testid="stSidebar"] h1, 
    section[data-testid="stSidebar"] h2, 
    section[data-testid="stSidebar"] h3, 
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] div {
        color: #1E1E23 !important;
        font-weight: 700 !important;
    }
    section[data-testid="stSidebar"] button {
        background-color: #F8F9FA !important;
        color: #1E1E23 !important; /* 짙은 검은색 */
        border: 1px solid #E4E8EB !important;
        border-radius: 6px !important;
        font-size: 0.9rem !important;
        font-weight: 700 !important;
        margin-bottom: 0.3rem !important;
        transition: all 0.2s ease !important;
    }
    section[data-testid="stSidebar"] button:hover {
        background-color: #EAECEE !important;
        border-color: #D2D6DA !important;
        color: #03C75A !important; /* 호버 시 네이버 그린 포인트 */
    }

    /* 8. 추가 질문 입력창(st.chat_input) 및 버튼 네이버 그린 적용 */
    textarea[data-testid="stChatInputTextArea"] {
        border: 1.5px solid #1E1E23 !important; /* 짙은 검은색 테두리로 강조 */
        border-radius: 8px !important;
        background-color: #FFFFFF !important;
        color: #1E1E23 !important;
        font-weight: 500 !important;
    }
    
    /* 8-1. 사용자 대화 버블 어두운 계열 커스텀 */
    .user-chat-bubble {
        background-color: #1E1E23 !important; /* 어두운 차콜/블랙 */
        color: #FFFFFF !important;            /* 흰색 텍스트 */
        padding: 0.7rem 1.1rem !important;
        border-radius: 10px !important;
        display: inline-block !important;
        line-height: 1.5 !important;
        font-weight: 500 !important;
    }
    textarea[data-testid="stChatInputTextArea"]:focus {
        border-color: #03C75A !important;
        box-shadow: 0 0 0 1px #03C75A !important;
    }
    /* st.chat_input 플레이스홀더(안내 문구) 글씨 선명하게 변경 */
    textarea[data-testid="stChatInputTextArea"]::placeholder {
        color: #666666 !important;
        font-weight: 500 !important;
    }
    /* 전송 아이콘 및 동그라미 버튼을 네이버 그린 테마로 리폼 */
    button[data-testid="stChatInputSubmitButton"] {
        background-color: #03C75A !important;
        color: #FFFFFF !important;
        border-radius: 50% !important;
        transition: background-color 0.15s ease !important;
    }
    button[data-testid="stChatInputSubmitButton"]:hover {
        background-color: #17B75E !important;
    }
    button[data-testid="stChatInputSubmitButton"] svg {
        color: #FFFFFF !important;
    }

    /* 9. 메인 화면 제목, 서브헤더, 입력 인풋 라벨 글씨체 검은색 강조 */
    h3, 
    label, 
    div[data-testid="stWidgetLabel"] p {
        color: #1E1E23 !important;
        font-weight: 700 !important;
    }

    /* 10. 로딩 스피너(st.spinner) 대기 글씨 검은색 강제 강조 */
    div[data-testid="stSpinner"] > div {
        color: #1E1E23 !important;
        font-weight: 700 !important;
    }

    </style>
""", unsafe_allow_html=True)

# 타이틀 및 헤더 (네이버 증권/금융 스타일)
st.markdown('<div class="main-title">💡 AI 주식 분석 비서</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">실시간 네이버 뉴스 분석과 잠재적 리스크 분석을 토대로 한 프리미엄 종목 브리핑 서비스</div>', unsafe_allow_html=True)

# API 키 가져오기 (.env)
active_google_key = os.environ.get("GOOGLE_API_KEY", "").strip()
active_naver_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
active_naver_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()

# ------------------------------------------------
# 사이드바: 과거 대화 로컬 히스토리 관리
# ------------------------------------------------
st.sidebar.title("📁 대화 히스토리")

# "새 종목 분석하기" 버튼 상단 배치
if st.sidebar.button("➕ 새 주식 분석 시작", use_container_width=True):
    st.session_state["chat_history"] = []
    st.session_state["news_context"] = ""
    st.session_state["current_stock"] = ""
    st.session_state["session_id"] = ""
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### 📜 이전 분석 목록")

# 로컬 JSON 파일로부터 전체 대화 기록 로딩
history_data = load_all_history()

if not history_data:
    st.sidebar.write("이전 분석 내역이 없습니다.")
else:
    # 생성 역순(최신순)으로 정렬하여 사이드바에 노출
    sorted_sessions = sorted(history_data.items(), key=lambda x: x[1]["created_at"], reverse=True)
    
    for sess_id, details in sorted_sessions:
        # 가시성 좋은 레이블 (예: "삼성전자 (05-27 18:00)")
        time_parsed = datetime.strptime(details["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%m-%d %H:%M")
        button_label = f"📈 {details['stock_name']} ({time_parsed})"
        
        # 버튼을 클릭하면 해당 과거 데이터로 세션 세팅
        if st.sidebar.button(button_label, key=sess_id, use_container_width=True):
            st.session_state["session_id"] = sess_id
            st.session_state["current_stock"] = details["stock_name"]
            st.session_state["news_context"] = details.get("news_context", "")
            st.session_state["news_context_raw"] = details.get("news_context_raw", [])
            st.session_state["risks"] = details.get("risks", [])
            st.session_state["chat_history"] = details["chat_history"]
            st.rerun()

# ------------------------------------------------
# 단계 1: 관심 주식 종목 검색 (초기 1회 검색)
# ------------------------------------------------
if not st.session_state["current_stock"]:
    st.subheader("🔍 주식 종목 분석 시작")
    stock_input = st.text_input("분석할 주식 종목명을 입력하세요", placeholder="예: 삼성전자, 테슬라, SK하이닉스")
    start_btn = st.button("뉴스 분석 시작", use_container_width=True)
    
    if start_btn:
        if not stock_input.strip():
            st.warning("분석할 종목명을 기입해 주세요.")
        elif not active_google_key or not active_naver_id or not active_naver_secret:
            st.error("🔑 API Key 설정이 비어있습니다. 프로젝트 내의 `.env` 파일에 API 키를 등록해 주세요.")
        else:
            st.session_state["current_stock"] = stock_input.strip()
            # 고유한 세션 ID 발급 (실시간 저장을 위해 사용)
            st.session_state["session_id"] = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 최초 분석 시작 (5단계 에이전트 플로우)
            try:
                status_container = st.status("AI 주식 분석 진행 중...", expanded=True)
                with status_container as status:
                    # 1단계: 뉴스 수집
                    status.write("1단계: 관련 뉴스 수집 중... (10건)")
                    collected = collect_news(stock_input)
                    if not collected:
                        status.update(label="뉴스 수집 실패! API 설정을 확인하세요.", state="error")
                        st.session_state["current_stock"] = ""
                        st.session_state["session_id"] = ""
                        st.stop()
                    status.write(f"1단계 완료! ✅ ({len(collected)}건 수집됨)")
                    
                    # 2단계: 뉴스 필터링
                    status.write("2단계: 중복 및 저품질 뉴스 필터링 중...")
                    filtered = filter_news(collected)
                    if not filtered:
                        status.update(label="필터링 결과 분석할 유효한 뉴스가 없습니다.", state="error")
                        st.session_state["current_stock"] = ""
                        st.session_state["session_id"] = ""
                        st.stop()
                    status.write(f"2단계 완료! ✅ ({len(filtered)}건 남음)")
                    
                    # 3단계: 감성 분석
                    status.write("3단계: Gemini로 개별 뉴스 호재/악재 감성 분석 중...")
                    analyzed = analyze_sentiments(filtered, active_google_key)
                    status.write("3단계 완료! ✅")
                    
                    # 4단계: 리스크 분석
                    status.write("4단계: 투자 유의 리스크 요인 분석 중...")
                    risks = analyze_risks(analyzed, active_google_key)
                    status.write(f"4단계 완료! ✅ ({len(risks)}개 리스크 감지)")
                    
                    # 5단계: 최종 브리핑 작성
                    status.write("5단계: 주식 분석 리포트 및 브리핑 생성 중...")
                    briefing = generate_briefing(analyzed, risks, stock_input, active_google_key)
                    status.write("5단계 완료! ✅ (금융 심의 필터 적용)")
                    
                    status.update(label="AI 분석 성공적으로 완료! 🎉", state="complete", expanded=False)
                
                # 분석 결과 세션 저장
                st.session_state["news_context_raw"] = analyzed
                st.session_state["risks"] = risks
                
                # 후속 질문 응답용 텍스트 컨텍스트 구성
                news_summary_text = []
                for i, news in enumerate(analyzed, 1):
                    news_summary_text.append(f"[{i}] {news['title']}\n- 감성: {news['sentiment']}\n- 근거: {news['reason']}\n- 링크: {news['link']}")
                st.session_state["news_context"] = "\n\n".join(news_summary_text)
                
                # 대화 기록 기록
                st.session_state["chat_history"].append({"role": "user", "content": f"**{stock_input}** 주식 뉴스 분석 시작"})
                st.session_state["chat_history"].append({"role": "assistant", "content": briefing})
                
                save_current_history(
                    st.session_state["session_id"],
                    st.session_state["current_stock"],
                    st.session_state["news_context"],
                    st.session_state["chat_history"],
                    news_context_raw=st.session_state["news_context_raw"],
                    risks=st.session_state["risks"]
                )
                st.rerun()
                
            except Exception as e:
                st.session_state["current_stock"] = ""
                st.session_state["session_id"] = ""
                st.error(f"분석 중 오류 발생: {str(e)}")

# ------------------------------------------------
# 단계 2: 대화 및 후속 질문 (챗봇 모드)
# ------------------------------------------------
else:
    st.markdown(f"### 💬 **{st.session_state['current_stock']}** 분석 및 대화방")
    
    # 1. 감정 분석 요약 배너 렌더링
    raw_news = st.session_state.get("news_context_raw", [])
    if raw_news:
        good = sum(1 for n in raw_news if n.get("sentiment") == "호재")
        bad = sum(1 for n in raw_news if n.get("sentiment") == "악재")
        neutral = sum(1 for n in raw_news if n.get("sentiment") == "중립")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f'<div style="background-color: #EBFBEE; border-left: 5px solid #03C75A; padding: 10px; border-radius: 5px; text-align: center;"><span style="color: #03C75A; font-weight: bold; font-size: 0.95rem;">🟢 호재 뉴스</span><br><span style="font-size: 1.3rem; font-weight: 800; color: #1E1E23;">{good}건</span></div>', unsafe_allow_html=True)
        with col2:
            st.markdown(f'<div style="background-color: #FCE8E6; border-left: 5px solid #D93025; padding: 10px; border-radius: 5px; text-align: center;"><span style="color: #D93025; font-weight: bold; font-size: 0.95rem;">🔴 악재 뉴스</span><br><span style="font-size: 1.3rem; font-weight: 800; color: #1E1E23;">{bad}건</span></div>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<div style="background-color: #F1F3F4; border-left: 5px solid #5F6368; padding: 10px; border-radius: 5px; text-align: center;"><span style="color: #5F6368; font-weight: bold; font-size: 0.95rem;">🟡 중립 뉴스</span><br><span style="font-size: 1.3rem; font-weight: 800; color: #1E1E23;">{neutral}건</span></div>', unsafe_allow_html=True)
        st.markdown("<div style='margin-bottom: 1.5rem;'></div>", unsafe_allow_html=True)

    # 2. 대화 기록 렌더링 (최초 브리핑 요약과 리스크 주의사항 강조)
    for idx, message in enumerate(st.session_state["chat_history"]):
        if message["role"] == "user":
            with st.chat_message("user"):
                st.markdown(f'<div class="user-chat-bubble">{message["content"]}</div>', unsafe_allow_html=True)
        else:
            with st.chat_message("assistant"):
                # 메인 브리핑
                st.markdown(f'<div class="brief-container">{message["content"]}</div>', unsafe_allow_html=True)
                
                # 최초 브리핑 메시지(인덱스 1) 바로 뒤에 리스크 리스트 렌더링
                if idx == 1:
                    risks = st.session_state.get("risks", [])
                    if risks:
                        st.markdown("#### ⚠️ 투자자 유의 리스크 요인")
                        risk_html = "<div style='background-color: #FFF8E1; border-left: 6px solid #FFB300; padding: 1.2rem; border-radius: 8px; color: #1E1E23; font-size: 0.95rem; line-height: 1.6; margin-bottom: 1.5rem;'>"
                        risk_html += "<ul style='margin: 0; padding-left: 20px;'>"
                        for r in risks:
                            risk_html += f"<li style='margin-bottom: 6px;'><b>{r}</b></li>"
                        risk_html += "</ul></div>"
                        st.markdown(risk_html, unsafe_allow_html=True)

    # 3. 뉴스 기사 카드 목록 렌더링 (대화 로그 하단에 고정 표시)
    if raw_news:
        st.markdown("---")
        st.markdown("### 📰 분석 대상 뉴스 목록 (상세 분석)")
        
        for news in raw_news:
            sentiment = news.get("sentiment", "중립")
            
            # 감성에 따른 뱃지 스타일 지정
            if sentiment == "호재":
                badge_html = '<span style="background-color: #EBFBEE; color: #03C75A; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.78rem; border: 1px solid #03C75A; margin-right: 8px;">🟢 호재</span>'
            elif sentiment == "악재":
                badge_html = '<span style="background-color: #FCE8E6; color: #D93025; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.78rem; border: 1px solid #D93025; margin-right: 8px;">🔴 악재</span>'
            else:
                badge_html = '<span style="background-color: #F1F3F4; color: #5F6368; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.78rem; border: 1px solid #5F6368; margin-right: 8px;">🟡 중립</span>'
                
            with st.container(border=True):
                # 헤더 영역
                st.markdown(f"""
                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;">
                    <div>{badge_html} <span style="font-weight: 800; font-size: 1.05rem; color: #1E1E23;">{news['title']}</span></div>
                    <div style="font-size: 0.78rem; color: #888888;">발행일: {news['pub_date']}</div>
                </div>
                """, unsafe_allow_html=True)
                
                # 본문 설명
                st.markdown(f"""
                <div style="margin-top: 8px; font-size: 0.92rem; line-height: 1.5; color: #555555;">
                    <b>기사 요약:</b> {news['description']}
                </div>
                """, unsafe_allow_html=True)
                
                # AI 분석 근거
                st.markdown(f"""
                <div style="margin-top: 8px; padding: 8px 12px; background-color: #F8F9FA; border-radius: 6px; font-size: 0.9rem; color: #333333; border-left: 3px solid #D2D6DA;">
                    💡 <b>AI 판단 근거:</b> {news['reason']}
                </div>
                """, unsafe_allow_html=True)
                
                # 링크 버튼
                if news.get("link"):
                    st.markdown(f"""
                    <div style="margin-top: 10px;">
                        <a href="{news['link']}" target="_blank" style="text-decoration: none;">
                            <button style="background-color: #FFFFFF; color: #03C75A; border: 1px solid #03C75A; border-radius: 4px; padding: 4px 10px; font-size: 0.82rem; font-weight: bold; cursor: pointer; transition: all 0.2s;">
                                🔗 원문 기사 읽기
                            </button>
                        </a>
                    </div>
                    """, unsafe_allow_html=True)

    # 4. 후속 질문 입력 받기
    user_input = st.chat_input("추가로 궁금한 점을 질문해 보세요 (예: 악재 뉴스 기사명이 뭐야? 향후 전망은?)")
    
    if user_input:
        with st.chat_message("user"):
            st.markdown(f'<div class="user-chat-bubble">{user_input}</div>', unsafe_allow_html=True)
        st.session_state["chat_history"].append({"role": "user", "content": user_input})
        
        with st.spinner("생각 중..."):
            try:
                if not HAS_GENAI:
                    st.error("google-generativeai 패키지가 로드되지 않아 후속 질문을 처리할 수 없습니다.")
                    response = "오류: google-generativeai 로드 실패"
                else:
                    response = run_direct_gemini_chat(
                        user_question=user_input,
                        active_google_key=active_google_key,
                        model_name=GEMINI_MODEL
                    )
                
                st.session_state["chat_history"].append({"role": "assistant", "content": response})
                save_current_history(
                    st.session_state["session_id"],
                    st.session_state["current_stock"],
                    st.session_state["news_context"],
                    st.session_state["chat_history"],
                    news_context_raw=st.session_state["news_context_raw"],
                    risks=st.session_state["risks"]
                )
                st.rerun()
                
            except Exception as e:
                st.error(f"답변 중 오류 발생: {str(e)}")
