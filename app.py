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

# .env 파일에서 환경 변수(API 키 등)를 로드합니다.
load_dotenv()

# 사용할 Google Gemini 모델명 설정
GEMINI_MODEL = "gemini-2.5-flash"
# 이전 대화 및 분석 결과를 저장할 로컬 JSON 파일 경로
HISTORY_FILE = "chat_history.json"

def load_all_history() -> dict:
    """
    로컬 JSON 파일(chat_history.json)로부터 기존의 모든 대화/분석 히스토리 데이터를 불러옵니다.
    파일이 없거나 읽기 에러 발생 시 빈 딕셔너리를 반환합니다.
    """
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_current_history(session_id: str, stock_name: str, news_context: str, chat_history: list, news_context_raw: list = None, risks: list = None):
    """
    현재 진행 중인 주식 분석 세션의 데이터를 로컬 JSON 파일에 누적하여 저장합니다.
    
    Args:
        session_id (str): 세션 고유 ID (시간 기반)
        stock_name (str): 검색한 주식 종목명
        news_context (str): 요약된 뉴스 컨텍스트 (Gemini 대화용)
        chat_history (list): 현재까지의 대화 목록
        news_context_raw (list, optional): 감성 분석까지 완료된 개별 뉴스 데이터 목록
        risks (list, optional): 도출된 투자 유의 리스크 목록
    """
    if not session_id:
        return
    all_hist = load_all_history()
    # 해당 세션 ID의 키 아래에 데이터 저장
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

# --- Streamlit 세션 상태(Session State) 변수 초기화 ---
# 대화방의 대화 기록 저장
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
# Gemini 후속 질문에 참고할 요약 뉴스 텍스트
if "news_context" not in st.session_state:
    st.session_state["news_context"] = ""
# 상세 뉴스 카드 목록을 그리기 위한 감성 분석 결과 포함 뉴스 리스트
if "news_context_raw" not in st.session_state:
    st.session_state["news_context_raw"] = []
# 도출된 리스크 요인 목록
if "risks" not in st.session_state:
    st.session_state["risks"] = []
# 현재 분석 중인 주식 종목명
if "current_stock" not in st.session_state:
    st.session_state["current_stock"] = ""
# 현재 세션의 고유 식별 ID
if "session_id" not in st.session_state:
    st.session_state["session_id"] = ""

# Google GenerativeAI 라이브러리가 제대로 임포트되는지 확인
try:
    import google.generativeai as genai
    HAS_GENAI = True
except Exception as e:
    HAS_GENAI = False
    print("Google GenAI SDK 임포트 실패:", e)

def clean_html(text: str) -> str:
    """
    네이버 뉴스 API 결과(제목, 요약문)에 섞여 있는 HTML 태그(예: <b>, &quot; 등)를 제거하고 디코딩합니다.
    """
    clean_re = re.compile('<.*?>')
    cleaned_text = re.sub(clean_re, '', text)
    return html.unescape(cleaned_text)

def get_jaccard_similarity(str1: str, str2: str) -> float:
    """
    두 문자열 간의 자카드 유사도(Jaccard Similarity)를 계산합니다. (중복도 판단용)
    """
    s1 = set(str1)
    s2 = set(str2)
    if not s1 and not s2:
        return 1.0
    return len(s1.intersection(s2)) / len(s1.union(s2))

def collect_news(query: str) -> list:
    """
    네이버 뉴스 API를 통해 정확도순(sim) 15건, 최신순(date) 15건의 기사를 수집합니다.
    
    Args:
        query (str): 검색할 주식 종목명
    Returns:
        list: 중복 링크가 배제된 원본 뉴스 딕셔너리 리스트
    """
    client_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return []
    
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }
    news_dict = {}
    
    # 1. 정확도순(sim), 2. 최신순(date) 각각 15개씩 요청하여 결합 (다양성 및 최신성 확보)
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
                    # 동일한 URL을 가진 기사는 한 번만 등록
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
    """
    수집된 뉴스 데이터에 대해 저품질 뉴스 제외, 오래된 뉴스 제외, 유사 제목 중복 제거를 진행합니다.
    
    Args:
        news_list (list): 수집된 뉴스 리스트
    Returns:
        list: 필터링이 완료된 최종 10건의 뉴스 리스트
    """
    filtered = []
    latest_dt = None
    parsed_news_list = []
    
    # 1단계: 발행일 파싱 및 수집된 뉴스 중 가장 최신 기사의 시점 파악
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
        
    if latest_dt is None:
        latest_dt = datetime.now()
        
    seen_keys = set()
    # 2단계: 조건 필터링 수행
    for news, pub_dt in parsed_news_list:
        title = news.get("title", "").strip()
        description = news.get("description", "").strip()
        link = news.get("link", "").strip()
        
        # 조건 A: 제목이 너무 짧거나 본문(요약)이 짧은 저품질 뉴스 필터링
        if len(title) < 8 or len(description) < 20:
            continue
            
        # 조건 B: 최신 기사 날짜 기준으로 14일(2주)보다 오래된 뉴스는 분석 제외
        if pub_dt:
            delta = latest_dt - pub_dt
            if delta.days > 14:
                continue
                
        # 조건 C: 제목의 앞 40글자와 도메인을 조합해 중복 뉴스 기사를 식별 및 제거 (Dedupe Key)
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
        
    # 최대 10건의 뉴스만 최종 분석 대상으로 선정
    return filtered[:10]

def analyze_sentiments(news_list: list, active_google_key: str) -> list:
    """
    각 기사에 대해 Gemini API를 호출하여 호재/악재/중립 판정 및 평가 근거를 받아옵니다.
    
    Args:
        news_list (list): 필터링된 기사 목록
        active_google_key (str): Google Gemini API 키
    Returns:
        list: 각 기사 정보 딕셔너리에 'sentiment'와 'reason'이 추가된 리스트
    """
    genai.configure(api_key=active_google_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    analyzed_news = []
    
    for news in news_list:
        # Gemini가 엄격하게 JSON 구조로만 답변하도록 프롬프트 작성
        prompt = """당신은 전문 금융 감성 분석가입니다. 아래 제공되는 기사의 제목과 요약을 분석하여, 이 뉴스가 해당 기업의 주가에 미칠 영향을 "호재", "악재", "중립" 중 하나로 평가하고 그 구체적인 근거를 한국어로 설명해 주세요.

[기사 정보]
제목: {title}
요약: {description}

반드시 아래 형식의 JSON 객체로만 응답해 주세요. 추가적인 설명이나 텍스트는 출력하지 마세요:
{
  "sentiment": "호재" | "악재" | "중립",
  "reason": "평가한 구체적인 근거(한글 문장)"
}"""
        prompt = prompt.replace("{title}", news.get('title', '')).replace("{description}", news.get('description', ''))
        try:
            response = model.generate_content(
                prompt,
                # JSON 응답을 보장하기 위한 API 설정
                generation_config={"response_mime_type": "application/json"}
            )
            data = json.loads(response.text.strip())
            news_copy = news.copy()
            news_copy["sentiment"] = data.get("sentiment", "중립")
            news_copy["reason"] = data.get("reason", "분석 불가")
            analyzed_news.append(news_copy)
        except Exception as e:
            # 예외 처리: 분석 실패 시 기본값으로 '중립' 반환
            news_copy = news.copy()
            news_copy["sentiment"] = "중립"
            news_copy["reason"] = f"감성 분석 오류: {str(e)}"
            analyzed_news.append(news_copy)
    return analyzed_news

def analyze_risks(news_list: list, active_google_key: str) -> list:
    """
    수집된 뉴스 분석 결과를 종합하여 해당 주식의 투자 리스크 요인 3~5가지를 도출합니다.
    
    Args:
        news_list (list): 감성 분석이 완료된 뉴스 목록
        active_google_key (str): Gemini API 키
    Returns:
        list: 도출된 리스크 문장 리스트
    """
    genai.configure(api_key=active_google_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    news_summary = []
    
    for i, news in enumerate(news_list, 1):
        news_summary.append(f"[{i}] {news['title']}\n- 감성: {news['sentiment']}\n- 근거: {news['reason']}")
    news_summary_str = "\n\n".join(news_summary)
    
    prompt = """당신은 리스크 관리 전문가입니다. 다음 수집된 뉴스 및 개별 감성 분석 결과들을 분석하여, 투자자가 해당 종목에 투자할 때 직면할 수 있는 투자 리스크 요인을 최소 3가지에서 최대 5가지 도출해 주세요. 거시경제(Macro), 기업 실적, 경쟁 구도, 주가 변동성 등의 관점을 반영하여 구체적으로 작성해야 합니다.

[뉴스 및 분석 데이터]
{news_summary_str}

반드시 아래 형식의 JSON 객체로만 응답해 주세요. 추가적인 설명이나 텍스트는 출력하지 마세요:
{
  "risks": [
    "리스크 요인 1 (구체적인 영향 및 이유 포함)",
    "리스크 요인 2 ...",
    ...
  ]
}"""
    prompt = prompt.replace("{news_summary_str}", news_summary_str)
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
    """
    금융 심의 준수를 위해 편향된 매수/매도/추천 직접 권유 단어들을 부드러운 중립 어조로 치환합니다.
    """
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
    """
    뉴스 분석 내용과 리스크 분석 결과를 취합하여 최종 투자 브리핑 리포트를 작성합니다.
    """
    genai.configure(api_key=active_google_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    news_summary = []
    
    for i, news in enumerate(news_list, 1):
        news_summary.append(f"[{i}] {news['title']}\n- 감성: {news['sentiment']}\n- 분석 근거: {news['reason']}")
    news_summary_str = "\n\n".join(news_summary)
    risks_str = "\n".join([f"- {risk}" for risk in risks])
    
    prompt = """당신은 전문 금융 분석가입니다. 수집된 뉴스 및 감성 분석 결과와 투자 리스크 요인을 종합하여 해당 종목에 대한 투자 요약 브리핑 리포트를 작성해 주세요.
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
    prompt = prompt.replace("{stock_name}", stock_name)
    prompt = prompt.replace("{news_summary_str}", news_summary_str)
    prompt = prompt.replace("{risks_str}", risks_str)
    
    try:
        response = model.generate_content(prompt)
        briefing = response.text.strip()
        # 매수/매도/투자 유도 단어 완화
        briefing = _sanitize_recommendations(briefing)
        # 하단에 투자자 보호를 위한 필수 면책 조항 강제 삽입
        disclaimer = """
---
⚠️ **면책조항 (DISCLAIMER)**: 본 브리핑은 수집된 뉴스 데이터 및 AI 분석을 기반으로 제공되는 단순 참고용 정보이며, 특정 종목에 대한 투자 권유나 추천이 아닙니다. 모든 투자 의사결정은 투자자 본인의 판단과 책임 하에 이루어져야 하며, 본 정보의 오류나 누락으로 인한 투자 결과에 대해 어떠한 법적 책임도 지지 않습니다."""
        return briefing + disclaimer
    except Exception as e:
        return f"브리핑 생성 중 오류 발생: {str(e)}"

def run_direct_gemini_chat(user_question: str, active_google_key: str, model_name: str) -> str:
    """
    분석 완료 후 대화방에서 유저의 후속 질문에 대답합니다.
    수집된 뉴스 내용과 이전 대화 맥락 전체를 프롬프트에 포함하여 일관성 있는 답변을 하도록 유도합니다.
    """
    genai.configure(api_key=active_google_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""당신은 전문 주식 투자 분석 에이전트입니다.
사용자가 수집된 최근 뉴스 정보 및 기존 대화 맥락을 기반으로 후속 질문을 하고 있습니다. 이에 대해 친절하고 전문적으로 한국어로 답변해 주세요.

[수집된 뉴스 정보]
{st.session_state.get("news_context", "")}

[이전 대화 기록]
"""
    # 이전 대화 기록 히스토리를 순차적으로 텍스트 프롬프트에 누적
    for msg in st.session_state["chat_history"]:
        prompt += f"{msg['role'].upper()}: {msg['content']}\n"
        
    prompt += f"""
USER: {user_question}
ASSISTANT:"""
    response = model.generate_content(prompt)
    return response.text

# --- Streamlit UI 페이지 설정 및 커스텀 CSS 정의 ---
st.set_page_config(page_title="Stock-Agent: AI 투자 뉴스 비서", page_icon="📈", layout="centered")

# Streamlit 기본 UI 요소들을 가리고 세련된 네이버 금융 스타일로 변경하기 위한 CSS 인젝션
st.markdown("""
    <style>
    header[data-testid="stHeader"] {
        visibility: hidden;
        height: 0px;
    }
    div[data-testid="stDecorator"] {
        display: none;
    }
    html, body, .stApp, 
    div[data-testid="stAppViewContainer"], 
    div[data-testid="stAppViewBlockContainer"], 
    div[data-testid="stMain"] {
        background-color: #F8F9FA !important;
    }
    .main-title {
        font-size: 2.1rem;
        font-weight: 800;
        color: #03C75A;
        margin-bottom: 0.3rem;
        font-family: 'NanumSquare', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .sub-title {
        font-size: 1.0rem;
        color: #555555;
        margin-bottom: 2rem;
    }
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
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #ECEFF1 !important;
    }
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
        color: #1E1E23 !important;
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
        color: #03C75A !important;
    }
    textarea[data-testid="stChatInputTextArea"] {
        border: 1.5px solid #1E1E23 !important;
        border-radius: 8px !important;
        background-color: #FFFFFF !important;
        color: #1E1E23 !important;
        font-weight: 500 !important;
    }
    .user-chat-bubble {
        background-color: #1E1E23 !important;
        color: #FFFFFF !important;
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
    textarea[data-testid="stChatInputTextArea"]::placeholder {
        color: #666666 !important;
        font-weight: 500 !important;
    }
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
    h3, 
    label, 
    div[data-testid="stWidgetLabel"] p {
        color: #1E1E23 !important;
        font-weight: 700 !important;
    }
    div[data-testid="stSpinner"] > div {
        color: #1E1E23 !important;
        font-weight: 700 !important;
    }
    </style>
""", unsafe_allow_html=True)

# 메인 헤더 표시
st.markdown('<div class="main-title">💡 AI 주식 분석 비서</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">실시간 네이버 뉴스 분석과 잠재적 리스크 분석을 토대로 한 프리미엄 종목 브리핑 서비스</div>', unsafe_allow_html=True)

# 환경 변수로부터 API 키 읽기
active_google_key = os.environ.get("GOOGLE_API_KEY", "").strip()
active_naver_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
active_naver_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()

# --- 사이드바 영역 설계 ---
st.sidebar.title("📁 대화 히스토리")

# 새 분석 세션 시작 버튼
if st.sidebar.button("➕ 새 주식 분석 시작", use_container_width=True):
    st.session_state["chat_history"] = []
    st.session_state["news_context"] = ""
    st.session_state["news_context_raw"] = []
    st.session_state["risks"] = []
    st.session_state["current_stock"] = ""
    st.session_state["session_id"] = ""
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### 📜 이전 분석 목록")

# 히스토리 데이터 파일로부터 전체 이력을 로드
history_data = load_all_history()

# 히스토리가 비었는지 검사 후 렌더링
if not history_data:
    st.sidebar.write("이전 분석 내역이 없습니다.")
else:
    # 가장 최근에 분석한 이력이 최상단에 오도록 정렬
    sorted_sessions = sorted(history_data.items(), key=lambda x: x[1]["created_at"], reverse=True)
    for sess_id, details in sorted_sessions:
        # 날짜 포맷팅: '월-일 시:분'
        time_parsed = datetime.strptime(details["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%m-%d %H:%M")
        button_label = f"📈 {details['stock_name']} ({time_parsed})"
        
        # 개별 세션 로드 버튼 클릭 이벤트
        if st.sidebar.button(button_label, key=sess_id, use_container_width=True):
            st.session_state["session_id"] = sess_id
            st.session_state["current_stock"] = details["stock_name"]
            st.session_state["news_context"] = details.get("news_context", "")
            st.session_state["news_context_raw"] = details.get("news_context_raw", [])
            st.session_state["risks"] = details.get("risks", [])
            st.session_state["chat_history"] = details["chat_history"]
            st.rerun()

# --- 메인 본문 영역 설계 ---
# 아직 주식을 검색하지 않은 초기 상태
if not st.session_state["current_stock"]:
    st.subheader("🔍 주식 종목 분석 시작")
    stock_input = st.text_input("분석할 주식 종목명을 입력하세요", placeholder="예: 삼성전자, 테슬라, SK하이닉스")
    start_btn = st.button("뉴스 분석 시작", use_container_width=True)
    
    if start_btn:
        # 입력값 예외 확인
        if not stock_input.strip():
            st.warning("분석할 종목명을 기입해 주세요.")
        # API 키 세팅 예외 확인
        elif not active_google_key or not active_naver_id or not active_naver_secret:
            st.error("🔑 API Key 설정이 비어있습니다. 프로젝트 내의 `.env` 파일에 API 키를 등록해 주세요.")
        else:
            st.session_state["current_stock"] = stock_input.strip()
            # 연월일_시분초 기반 고유 세션 ID 생성
            st.session_state["session_id"] = datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                # 5단계 파이프라인 처리를 실시간으로 보여주는 Streamlit Status 박스
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
                    
                    # 2단계: 필터링
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
                    
                    # 5단계: 최종 브리핑 리포트
                    status.write("5단계: 주식 분석 리포트 및 브리핑 생성 중...")
                    briefing = generate_briefing(analyzed, risks, stock_input, active_google_key)
                    status.write("5단계 완료! ✅ (금융 심의 필터 적용)")
                    
                    # 최종 완료 표시
                    status.update(label="AI 분석 성공적으로 완료! 🎉", state="complete", expanded=False)
                
                # 분석 결과를 세션 상태에 저장
                st.session_state["news_context_raw"] = analyzed
                st.session_state["risks"] = risks
                
                # Gemini 후속 채팅 시 맥락 파악을 용이하게 하도록 컨텍스트 문자열 포맷팅
                news_summary_text = []
                for i, news in enumerate(analyzed, 1):
                    news_summary_text.append(f"[{i}] {news['title']}\n- 감성: {news['sentiment']}\n- 근거: {news['reason']}\n- 링크: {news['link']}")
                st.session_state["news_context"] = "\n\n".join(news_summary_text)
                
                # 분석 시작 메시지와 생성된 보고서를 대화 내용에 추가
                st.session_state["chat_history"].append({"role": "user", "content": f"**{stock_input}** 주식 뉴스 분석 시작"})
                st.session_state["chat_history"].append({"role": "assistant", "content": briefing})
                
                # 파일에 실시간 누적 저장
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
                # 에러 발생 시 초기 상태로 복구
                st.session_state["current_stock"] = ""
                st.session_state["session_id"] = ""
                st.error(f"분석 중 오류 발생: {str(e)}")

# 주식이 이미 선택되어 대화방이 활성화된 화면
else:
    st.markdown(f"### 💬 **{st.session_state['current_stock']}** 분석 및 대화방")
    
    # 1. 상단 감성 통계 배너 렌더링
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

    # 2. 대화 기록 채팅으로 렌더링
    for idx, message in enumerate(st.session_state["chat_history"]):
        if message["role"] == "user":
            with st.chat_message("user"):
                st.markdown(f'<div class="user-chat-bubble">{message["content"]}</div>', unsafe_allow_html=True)
        else:
            with st.chat_message("assistant"):
                st.markdown(f'<div class="brief-container">{message["content"]}</div>', unsafe_allow_html=True)
                # 최초 브리핑 리포트 출력 직후에 노란색 "리스크 정보 박스"를 추가 렌더링
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

    # 3. 하단 상세 분석 기사 카드 목록 출력
    if raw_news:
        st.markdown("---")
        st.markdown("### 📰 분석 대상 뉴스 목록 (상세 분석)")
        for news in raw_news:
            sentiment = news.get("sentiment", "중립")
            # 감성 분석 종류에 따라 뱃지 컬러 동적 변화
            if sentiment == "호재":
                badge_html = '<span style="background-color: #EBFBEE; color: #03C75A; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.78rem; border: 1px solid #03C75A; margin-right: 8px;">🟢 호재</span>'
            elif sentiment == "악재":
                badge_html = '<span style="background-color: #FCE8E6; color: #D93025; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.78rem; border: 1px solid #D93025; margin-right: 8px;">🔴 악재</span>'
            else:
                badge_html = '<span style="background-color: #F1F3F4; color: #5F6368; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.78rem; border: 1px solid #5F6368; margin-right: 8px;">🟡 중립</span>'
            
            with st.container(border=True):
                # 뉴스 카드 구조 설계
                st.markdown(f"""
                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;">
                     <div>{badge_html} <span style="font-weight: 800; font-size: 1.05rem; color: #1E1E23;">{news['title']}</span></div>
                     <div style="font-size: 0.78rem; color: #888888;">발행일: {news['pub_date']}</div>
                </div>
                """, unsafe_allow_html=True)
                st.markdown(f"""
                <div style="margin-top: 8px; font-size: 0.92rem; line-height: 1.5; color: #555555;">
                     <b>기사 요약:</b> {news['description']}
                </div>
                """, unsafe_allow_html=True)
                st.markdown(f"""
                <div style="margin-top: 8px; padding: 8px 12px; background-color: #F8F9FA; border-radius: 6px; font-size: 0.9rem; color: #333333; border-left: 3px solid #D2D6DA;">
                     💡 <b>AI 판단 근거:</b> {news['reason']}
                </div>
                """, unsafe_allow_html=True)
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

    # 4. 사용자 후속 대화 채팅 입력창 처리
    user_input = st.chat_input("추가로 궁금한 점을 질문해 보세요 (예: 악재 뉴스 기사명이 뭐야? 향후 전망은?)")
    if user_input:
        # 화면에 즉시 사용자 질문 렌더링 및 세션에 추가
        with st.chat_message("user"):
            st.markdown(f'<div class="user-chat-bubble">{user_input}</div>', unsafe_allow_html=True)
        st.session_state["chat_history"].append({"role": "user", "content": user_input})
        
        with st.spinner("생각 중..."):
            try:
                if not HAS_GENAI:
                    st.error("google-generativeai 패키지가 로드되지 않아 후속 질문을 처리할 수 없습니다.")
                    response = "오류: google-generativeai 로드 실패"
                else:
                    # 이전 분석 맥락을 포함한 Gemini 답변 도출
                    response = run_direct_gemini_chat(
                        user_question=user_input,
                        active_google_key=active_google_key,
                        model_name=GEMINI_MODEL
                    )
                # 세션 데이터에 추가 및 파일 백업 후 리런(Rerun)
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
