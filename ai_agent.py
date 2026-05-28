import json
import streamlit as st
import google.generativeai as genai

# Google Gemini API 호출 및 프롬프트 제어를 도맡아 수행

#   •  analyze_sentiments(news_list, active_google_key) : 개별 뉴스의 호재/악재 판정 및 상세 근거 분석
#   •  analyze_risks(news_list, active_google_key) : 전체 분석 결과를 모아 거시경제/실적 등 다각도 투자 리스크 요인 3~5가지 추출
#   •  _sanitize_recommendations(text) : 금감원 권고 등을 준수한 금융 심의 어조 정제
#   •  generate_briefing(...) : 종합 분석 마크다운 보고서 생성 및 투자 면책 조항 강제 꼬리표 삽입
#   •  run_direct_gemini_chat(...) : 대화창에서 이전 대화 이력을 누적해 후속 질문에 지능적으로 응답


# 사용할 Gemini 모델명 정의
GEMINI_MODEL = "gemini-2.5-flash"

def analyze_sentiments(news_list: list, active_google_key: str) -> list:
    """
    각 기사에 대해 Gemini API를 호출하여 호재/악재/중립 판정 및 평가 근거를 받아옵니다.
    """
    genai.configure(api_key=active_google_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    analyzed_news = []
    
    for news in news_list:
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
    """
    수집된 뉴스 분석 결과를 종합하여 해당 주식의 투자 리스크 요인 3~5가지를 도출합니다.
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
        briefing = _sanitize_recommendations(briefing)
        disclaimer = """
---
⚠️ **면책조항 (DISCLAIMER)**: 본 브리핑은 수집된 뉴스 데이터 및 AI 분석을 기반으로 제공되는 단순 참고용 정보이며, 특정 종목에 대한 투자 권유나 추천이 아닙니다. 모든 투자 의사결정은 투자자 본인의 판단과 책임 하에 이루어져야 하며, 본 정보의 오류나 누락으로 인한 투자 결과에 대해 어떠한 법적 책임도 지지 않습니다."""
        return briefing + disclaimer
    except Exception as e:
        return f"브리핑 생성 중 오류 발생: {str(e)}"

def run_direct_gemini_chat(user_question: str, active_google_key: str, model_name: str) -> str:
    """
    분석 완료 후 대화방에서 유저의 후속 질문에 대답합니다.
    """
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
