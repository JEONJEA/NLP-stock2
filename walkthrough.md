# Stock-Agent 구현 완료 보고서 및 사용 가이드

주식 종목 입력 시 실시간으로 네이버 뉴스 검색 API를 통해 관련 뉴스를 가져와 분석하고, Google Gemini 1.5 Flash(LangChain Agent)를 활용해 호재/악재 판별 및 3줄 요약을 제공하는 MVP 웹 애플리케이션 구현을 마쳤습니다.

## 구현 결과

1. **[app.py](file:///C:/Users/전제서/study/NLP-project/app.py)**:
   - **`search_naver_news(query)`**: 사용자의 Naver API ID/Secret을 이용해 최신 실시간 뉴스 5개를 호출하는 LangChain Tool입니다. HTML 태그 및 언이스케이프 처리를 완벽하게 적용했습니다.
   - **`get_agent(...)`**: Streamlit의 `@st.cache_resource` 데코레이터를 사용하여 Gemini 모델 및 에이전트 인스턴스를 효과적으로 캐싱하고, API Key가 바뀔 때 유연하게 갱신되도록 하였습니다.
   - **Streamlit Web UI**: 사이드바를 통해 API Key 입력을 은닉화하여 처리하고, 메인 영역은 미려하고 현대적인 CSS 스타일 카드를 적용하여 결과를 보기 편하게 구성했습니다.

2. **[requirements.txt](file:///C:/Users/전제서/study/NLP-project/requirements.txt)**:
   - 애플리케이션 구동에 필수적인 외부 라이브러리 목록을 정의해 두었습니다.

---

## 실행 및 검증 방법

아래 가이드를 따라 설치하고 구동하여 실제 작동을 확인해 보실 수 있습니다.

### 1단계: 패키지 설치
VS Code의 터미널을 열고 다음 명령어를 입력하여 필요한 라이브러리를 한번에 설치합니다.
```bash
pip install -r requirements.txt
```

### 2단계: 애플리케이션 실행
설치가 완료되면 다음 명령어를 통해 Streamlit 개발 서버를 가동합니다.
```bash
streamlit run app.py
```
*실행 후 브라우저창이 자동으로 열리지 않으면 터미널에 표시되는 URL(예: `http://localhost:8501`)로 접속합니다.*

### 3단계: API 키 입력 및 주식 분석
1. 웹 브라우저 화면의 좌측 **사이드바**에 다음 API 키를 기입합니다:
   - **Google API Key**: Gemini API 호출 키
   - **Naver Client ID** 및 **Naver Client Secret**: 네이버 개발자 센터에서 발급받으신 네이버 검색 API 키
2. 메인 화면 입력란에 분석하고자 하는 주식 종목명(예: `삼성전자`, `테슬라`)을 입력합니다.
3. **[분석 시작]** 버튼을 클릭하고 로딩 스피너가 지나간 후 나타나는 마크다운 형태의 호재/악재 분석과 3줄 요약 결과를 확인합니다.
