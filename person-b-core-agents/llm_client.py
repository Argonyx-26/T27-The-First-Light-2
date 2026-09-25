import os, json, re
from dotenv import load_dotenv
from groq import Groq
import google.generativeai as genai

load_dotenv()
groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)

def _call_groq(system_prompt: str, user_prompt: str) -> dict:
    models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    errors = {}
    for model in models:
        try:
            resp = groq_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
            )
            return _extract_json(resp.choices[0].message.content)
        except Exception as e:
            errors[model] = str(e)
            continue
    raise RuntimeError(f"Both Groq models failed. Details: {errors}")

def _call_gemini(system_prompt: str, user_prompt: str) -> dict:
    model = genai.GenerativeModel("gemini-3.5-flash-lite", system_instruction=system_prompt)
    resp = model.generate_content(user_prompt)
    return _extract_json(resp.text)

def call_llm(system_prompt: str, user_prompt: str, primary: str = "groq") -> dict:
    order = [("groq", _call_groq), ("gemini", _call_gemini)] if primary == "groq" else [("gemini", _call_gemini), ("groq", _call_groq)]
    errors = {}
    for name, fn in order:
        try:
            return fn(system_prompt, user_prompt)
        except Exception as e:
            errors[name] = str(e)
            continue
    raise RuntimeError(f"Both providers failed. Errors: {errors}")
