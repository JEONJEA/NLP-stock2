import streamlit as st
import os
from datetime import datetime
from dotenv import load_dotenv

# • UI 렌더링, 사이드바 분석 목록 출력 및 사용자의 인터랙션만 남겨놓고, 실제
#  비즈니스 로직은 위 3개 파일에서  import 하여 호출하도록 경량화합니다.
# • 기존 녹색 테마 커스텀 CSS, 5단계 로딩바 상태 출력, 상세 뉴스 카드 및 채팅 벌룬
#  렌더링 레이아웃은 그대로 유지됩니다.


# .env 파일에서 환경 변수를 로드합니다.
load_dotenv()

# 분할된 모듈들을 임포트합니다.
from utils import load_all_history, save_current_history
from news_agent import collect_news, filter_news
from ai_agent import analyze_sentiments, analyze_risks, generate_briefing, run_direct_gemini_chat, GEMINI_MODEL

# --- Streamlit 세션 상태(Session State) 변수 초기화 ---
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

# --- Streamlit UI 페이지 설정 및 커스텀 CSS 정의 ---
st.set_page_config(page_title="Stock-Agent: AI 투자 뉴스 비서", page_icon="📈", layout="centered")

# 세련된 네이버 금융 스타일로 변경하기 위한 CSS 인젝션
st.markdown("""
    <style>
    .stAppDeployButton,
    button[id="MainMenu"] {
        display: none !important;
    }
    /* 인기 종목 빠른 검색 버튼 스타일 커스텀 (조약돌 디자인) */
    div[data-testid="column"] div.stButton {
        height: 38px !important;
        min-height: 38px !important;
        max-height: 38px !important;
        margin: 0 0 8px 0 !important;
        padding: 0 !important;
    }
    div[data-testid="column"] button {
        background-color: #F1F3F4 !important;
        color: #1E1E23 !important;
        border: 1px solid #E4E8EB !important;
        border-radius: 20px !important;
        padding: 0.4rem 1rem !important;
        font-size: 0.86rem !important;
        font-weight: 700 !important;
        box-shadow: none !important;
        width: 100% !important;
        height: 38px !important;
        min-height: 38px !important;
        max-height: 38px !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        transition: all 0.2s ease !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    div[data-testid="column"] button:hover {
        background-color: #03C75A !important;
        color: #FFFFFF !important;
        border-color: #03C75A !important;
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

# 메인 타이틀
st.markdown('<div class="main-title">💡 AI 주식 분석 비서</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">실시간 네이버 뉴스 분석과 잠재적 리스크 분석을 토대로 한 프리미엄 종목 브리핑 서비스</div>', unsafe_allow_html=True)

# API 키 및 설정 정보 가져오기
active_google_key = os.environ.get("GOOGLE_API_KEY", "").strip()
active_naver_id = os.environ.get("NAVER_CLIENT_ID", "").strip()
active_naver_secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()

# --- 사이드바 영역 ---
st.sidebar.title("📁 대화 히스토리")

# 새 분석 시작 버튼
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

# 히스토리 데이터 로드 (utils 모듈의 함수 호출)
history_data = load_all_history()

if not history_data:
    st.sidebar.write("이전 분석 내역이 없습니다.")
else:
    # 가장 최근 시간 순서대로 정렬
    sorted_sessions = sorted(history_data.items(), key=lambda x: x[1]["created_at"], reverse=True)
    for sess_id, details in sorted_sessions:
        time_parsed = datetime.strptime(details["created_at"], "%Y-%m-%d %H:%M:%S").strftime("%m-%d %H:%M")
        button_label = f"📈 {details['stock_name']} ({time_parsed})"
        if st.sidebar.button(button_label, key=sess_id, use_container_width=True):
            # 이전 히스토리 정보 복구
            st.session_state["session_id"] = sess_id
            st.session_state["current_stock"] = details["stock_name"]
            st.session_state["news_context"] = details.get("news_context", "")
            st.session_state["news_context_raw"] = details.get("news_context_raw", [])
            st.session_state["risks"] = details.get("risks", [])
            st.session_state["chat_history"] = details["chat_history"]
            st.rerun()

# --- 메인 본문 영역 ---
if not st.session_state["current_stock"]:
    st.subheader("🔍 주식 종목 분석 시작")
    stock_input = st.text_input("분석할 주식 종목명을 입력하세요", placeholder="예: 삼성전자, 테슬라, SK하이닉스")
    
    # 실시간 인기 종목 빠른 검색 영역 추가 (3개씩 2줄 배치로 넓은 폭 확보)
    st.markdown("<div style='margin-top: 1rem; margin-bottom: 0.5rem; font-weight: 700; color: #1E1E23; font-size: 0.95rem;'>🔥 실시간 인기 종목 빠른 검색</div>", unsafe_allow_html=True)
    popular_stocks_1 = ["삼성전자", "SK하이닉스", "테슬라"]
    popular_stocks_2 = ["엔비디아", "애플", "에코프로"]
    
    cols1 = st.columns(3)
    clicked_stock = None
    for i, stock in enumerate(popular_stocks_1):
        if cols1[i].button(stock, key=f"pop_{stock}", use_container_width=True):
            clicked_stock = stock
            
    cols2 = st.columns(3)
    for i, stock in enumerate(popular_stocks_2):
        if cols2[i].button(stock, key=f"pop_{stock}", use_container_width=True):
            clicked_stock = stock
            
    st.markdown("<div style='margin-bottom: 1.5rem;'></div>", unsafe_allow_html=True)
    start_btn = st.button("뉴스 분석 시작", use_container_width=True)
    
    # 분석 시작 트리거 판정
    target_stock = ""
    should_start = False
    
    if start_btn:
        if not stock_input.strip():
            st.warning("분석할 종목명을 기입해 주세요.")
        else:
            target_stock = stock_input.strip()
            should_start = True
    elif clicked_stock:
        target_stock = clicked_stock
        should_start = True
        
    if should_start:
        st.session_state["current_stock"] = target_stock
        st.session_state["session_id"] = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            status_container = st.status("AI 주식 분석 진행 중...", expanded=True)
            with status_container as status:
                # 1단계: 뉴스 수집 (news_agent 모듈 호출)
                status.write(f"1단계: '{target_stock}' 관련 뉴스 수집 중... (10건)")
                collected = collect_news(target_stock)
                if not collected:
                    status.update(label="뉴스 수집 실패! API 설정을 확인하세요.", state="error")
                    st.session_state["current_stock"] = ""
                    st.session_state["session_id"] = ""
                    st.stop()
                status.write(f"1단계 완료! ✅ ({len(collected)}건 수집됨)")
                
                # 2단계: 필터링 (news_agent 모듈 호출)
                status.write("2단계: 중복 및 저품질 뉴스 필터링 중...")
                filtered = filter_news(collected)
                if not filtered:
                    status.update(label="필터링 결과 분석할 유효한 뉴스가 없습니다.", state="error")
                    st.session_state["current_stock"] = ""
                    st.session_state["session_id"] = ""
                    st.stop()
                status.write(f"2단계 완료! ✅ ({len(filtered)}건 남음)")
                
                # 3단계: 감성 분석 (ai_agent 모듈 호출)
                status.write("3단계: Gemini로 개별 뉴스 호재/악재 감성 분석 중...")
                analyzed = analyze_sentiments(filtered, active_google_key)
                status.write("3단계 완료! ✅")
                
                # 4단계: 리스크 분석 (ai_agent 모듈 호출)
                status.write("4단계: 투자 유의 리스크 요인 분석 중...")
                risks = analyze_risks(analyzed, active_google_key)
                status.write(f"4단계 완료! ✅ ({len(risks)}개 리스크 감지)")
                
                # 5단계: 브리핑 생성 (ai_agent 모듈 호출)
                status.write("5단계: 주식 분석 리포트 및 브리핑 생성 중...")
                briefing = generate_briefing(analyzed, risks, target_stock, active_google_key)
                status.write("5단계 완료! ✅ (금융 심의 필터 적용)")
                
                status.update(label="AI 분석 성공적으로 완료! 🎉", state="complete", expanded=False)
            
            # 결과 상태 저장
            st.session_state["news_context_raw"] = analyzed
            st.session_state["risks"] = risks
            
            # 컨텍스트 조립
            news_summary_text = []
            for i, news in enumerate(analyzed, 1):
                news_summary_text.append(f"[{i}] {news['title']}\n- 감성: {news['sentiment']}\n- 근거: {news['reason']}\n- 링크: {news['link']}")
            st.session_state["news_context"] = "\n\n".join(news_summary_text)
            
            # 대화 히스토리에 분석 시작 및 결과 추가
            st.session_state["chat_history"].append({"role": "user", "content": f"**{target_stock}** 주식 뉴스 분석 시작"})
            st.session_state["chat_history"].append({"role": "assistant", "content": briefing})
            
            # 히스토리 파일에 영구 저장 (utils 모듈 호출)
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

else:
    st.markdown(f"### 💬 **{st.session_state['current_stock']}** 분석 및 대화방")
    
    # 1. 감성 통계 배너 표시
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

    # 2. 대화방 말풍선 출력
    for idx, message in enumerate(st.session_state["chat_history"]):
        if message["role"] == "user":
            with st.chat_message("user"):
                st.markdown(f'<div class="user-chat-bubble">{message["content"]}</div>', unsafe_allow_html=True)
        else:
            with st.chat_message("assistant"):
                st.markdown(f'<div class="brief-container">{message["content"]}</div>', unsafe_allow_html=True)
                # 최초 분석 리포트(1번 인덱스) 아래 리스크 요약 박스 노출
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

    # 3. 상세 분석 카드 리스트 출력
    if raw_news:
        st.markdown("---")
        st.markdown("### 📰 분석 대상 뉴스 목록 (상세 분석)")
        for news in raw_news:
            sentiment = news.get("sentiment", "중립")
            if sentiment == "호재":
                badge_html = '<span style="background-color: #EBFBEE; color: #03C75A; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.78rem; border: 1px solid #03C75A; margin-right: 8px;">🟢 호재</span>'
            elif sentiment == "악재":
                badge_html = '<span style="background-color: #FCE8E6; color: #D93025; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.78rem; border: 1px solid #D93025; margin-right: 8px;">🔴 악재</span>'
            else:
                badge_html = '<span style="background-color: #F1F3F4; color: #5F6368; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.78rem; border: 1px solid #5F6368; margin-right: 8px;">🟡 중립</span>'
            
            with st.container(border=True):
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

    # 4. 사용자 후속 질문 채팅 입력 처리
    user_input = st.chat_input("추가로 궁금한 점을 질문해 보세요 (예: 악재 뉴스 기사명이 뭐야? 향후 전망은?)")
    if user_input:
        with st.chat_message("user"):
            st.markdown(f'<div class="user-chat-bubble">{user_input}</div>', unsafe_allow_html=True)
        st.session_state["chat_history"].append({"role": "user", "content": user_input})
        
        with st.spinner("생각 중..."):
            try:
                # ai_agent 모듈의 대화 답변 함수 호출
                response = run_direct_gemini_chat(
                    user_question=user_input,
                    active_google_key=active_google_key,
                    model_name=GEMINI_MODEL
                )
                st.session_state["chat_history"].append({"role": "assistant", "content": response})
                # 세션 히스토리 저장 (utils 모듈 호출)
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