import os
import sys
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("GOOGLE_API_KEY", "").strip()

print("=== Diagnostics ===")
print("API Key configured (length):", len(api_key))

try:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    
    print("\n=== Listing Models ===")
    models = list(genai.list_models())
    if not models:
        print("No models found!")
    for m in models:
        # 지원 모델명과 지원하는 메소드들을 상세 출력
        print(f"Model: {m.name}")
        print(f"  DisplayName: {m.display_name}")
        print(f"  SupportedMethods: {m.supported_generation_methods}")
except Exception as e:
    print("\nError listing models:", str(e))
