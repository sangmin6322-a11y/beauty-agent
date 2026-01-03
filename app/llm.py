import os
import json
from openai import OpenAI

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM = """너는 K-Beauty 글로벌 트렌드/런칭 기획 AI 에이전트다.
반드시 JSON만 출력한다. 코드블록 금지.

스키마:
{
  "intent": "RADAR" | "LAUNCH" | "CHAT",
  "need_question": true | false,
  "slot": "country" | "category" | "need" | "price" | "channel" | "target" | "misc" | null,
  "question": string | null,
  "final": true | false,
  "reply": string
}

규칙:
- 런칭/기획/출시 의도이면 intent="LAUNCH".
- 트렌드/리뷰/랭킹/바이럴 분석이면 intent="RADAR".
- 그냥 대화면 intent="CHAT".
- LAUNCH에서 핵심 정보(country/category/need/price/channel/target)가 부족하면 need_question=true, slot을 지정하고 질문은 1개만.\n- 단, 질문은 가능한 한 "한 문장에 2~3개 항목"을 묶어서 물어봐서 2턴 안에 끝내라.\n- known_slots에 이미 있는 항목은 다시 묻지 마라.\n- 질문은 반드시 한 문장으로. (줄바꿈 금지)\n- need_question=true이면 slot은 반드시 지정해야 하며 null이면 안 된다.\n- need_question=true이면 slot은 반드시 지정해야 하며 null이면 안 된다.
- 정보가 충분하면 final=true로 하고 Launch Brief를 아래 템플릿으로 구조화해서 reply에 출력.\n\n템플릿:\n[Launch Brief]\n- Country/Region:\n- Category:\n- Target:\n- Key Need:\n- Price Band:\n- Channel Mix:\n- Core Claim (한 문장):\n- Next Action (1개):\n
- RADAR면 레이다 요약 형태로 reply에 출력.
- 항상 JSON만 출력.\n- Country/Region이 없으면 final=true로 끝내지 말고 slot="country" 질문을 우선하라.\n"""

def call_llm(user_message: str, brief_answers: list[str]) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key)

    payload = {"user_message": user_message, "known_slots": brief_answers}

    resp = client.responses.create(
        model=MODEL,
        input=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )

    text = resp.output_text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise





def call_radar(launch_brief: str, extra_notes: str = "") -> dict:
    # Radar: (1) 핵심 인사이트 (2) 리뷰/FAQ 리스크 (3) 차별화 각도 (4) 다음 리서치 액션
    system = (
        "You are a K-Beauty product/marketing strategist. "
        "Given a Launch Brief, create a concise 'Radar' report: "
        "1) Key insights (3 bullets), "
        "2) Likely review/FAQ risks & objections (3 bullets), "
        "3) Differentiation angles (3 bullets), "
        "4) Next research actions (3 bullets). "
        "Write in Korean. Keep it practical and specific."
    )

    user = f"""[Launch Brief]
{launch_brief}

[Extra Notes]
{extra_notes}
"""

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

    client = OpenAI(api_key=api_key)
    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.4,
    )

    text = ""
    try:
        text = resp.output_text
    except Exception:
        text = str(resp)

    return {"reply": (text or "").strip()}
