import os
import json
from llm import call_llm

def generate_tutor_response(topic: str, history: list) -> dict:
    """
    history: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    Returns: {"text": "...", "persistent_misconception": "..."}
    """
    sys_prompt = f"""You are a master interactive tutor helping a student practice the topic: {topic}.

Your goal is to guide the student through a mastery progression:
1. Base Concept
2. Near Transfer
3. Far Transfer
4. Novel Concept

RULES:
- When you ask a question, provide multiple-choice options (A, B, C, D) or ask a short open-ended question.
- When the student answers, immediately evaluate it as Correct or Incorrect.
- IF CORRECT: Praise them briefly, then ask the next question in the mastery progression (e.g., move to Near Transfer, then Far Transfer, etc.). If they complete the Novel Concept, congratulate them and state "MASTERY_ACHIEVED".
- IF INCORRECT: Provide immediate inline remediation. Explain exactly what went wrong and identify the misconception. Then, ask a diagnostic follow-up question to resolve it.
- IF THEY FAIL REPEATEDLY on the same concept: Include the exact string "PERSISTENT_MISCONCEPTION: [Description of the misconception]" in your response. This will signal the system to log a learning gap.

Format your response as a friendly, conversational message. Do NOT use markdown code blocks like ```json. Just speak directly to the student. Include the question directly in your text.
"""
    
    # Format history for the LLM
    formatted_history = "Conversation so far:\n"
    for msg in history:
        role_name = "Tutor" if msg["role"] == "assistant" else "Student"
        formatted_history += f"{role_name}: {msg['content']}\n"
        
    formatted_history += "\nTutor (you): "

    try:
        response_text = call_llm(sys_prompt, formatted_history, primary="gemini")
        if not isinstance(response_text, str):
            response_text = str(response_text)
            
        misconception = None
        if "PERSISTENT_MISCONCEPTION:" in response_text:
            parts = response_text.split("PERSISTENT_MISCONCEPTION:")
            misconception = parts[1].split("\n")[0].strip()
            response_text = response_text.replace(f"PERSISTENT_MISCONCEPTION: {misconception}", "").strip()
            
        is_done = "MASTERY_ACHIEVED" in response_text
        if is_done:
            response_text = response_text.replace("MASTERY_ACHIEVED", "").strip()
            
        return {
            "text": response_text.strip(),
            "persistent_misconception": misconception,
            "is_done": is_done
        }
    except Exception as e:
        print(f"[TUTOR ERROR] {e}")
        return {"text": "I'm having trouble thinking right now. Let's try again in a moment.", "persistent_misconception": None, "is_done": False}
