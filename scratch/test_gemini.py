import os
import sys
from dotenv import load_dotenv

# .env 로드
load_dotenv()

print("=== Python Environment ===")
print("Python Executable:", sys.executable)
print("Python Version:", sys.version)

api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
print("GOOGLE_API_KEY configured (length):", len(api_key))
if api_key:
    print("API Key Prefix:", api_key[:6] + "..." if len(api_key) > 6 else "Too short")

print("\n=== Test 1: Direct google-generativeai ===")
try:
    import google.generativeai as genai
    print("google-generativeai version:", genai.__version__ if hasattr(genai, "__version__") else "unknown")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content("Hi")
    print("Direct Gemini Response:", response.text)
except Exception as e:
    print("Direct Gemini Error:", str(e))

print("\n=== Test 2: langchain-google-genai ===")
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=api_key)
    res = llm.invoke("Hi")
    print("LangChain Gemini Response:", res.content)
except Exception as e:
    print("LangChain Gemini Error:", str(e))
