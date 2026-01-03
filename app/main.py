from fastapi import FastAPI
from pydantic import BaseModel
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict

import os
import re
import json
from app.db import init_db, insert_log, fetch_logs
from app.llm import call_llm

app = FastAPI(title="Beauty Agent", version="0.3.1")

init_db()

class State(str, Enum):
    CHAT = "CHAT"
    BRIEF = "BRIEF"

@dataclass
class Session:
    user_id: str
    state: State = State.CHAT
    # LLM이 요구하는 정보들을 슬롯으로 저장
    slots: Dict[str, str] = field(default_factory=dict)
    # 지금 질문 중인 슬롯
    pending_slot: str | None = None

SESSIONS: Dict[str, Session] = {}

class ChatIn(BaseModel):
    user_id: str
    message: str

class ChatOut(BaseModel):
    user_id: str
    state: str
    reply: str

@app.get("/health")
def health():
    return {"ok": True, "version": "0.3.1"}

@app.post("/chat", response_model=ChatOut)
def chat(payload: ChatIn):
    session = SESSIONS.get(payload.user_id)
    if session is None:
        session = Session(user_id=payload.user_id)
        SESSIONS[payload.user_id] = session

    msg = payload.message.strip()

    # reset
    if msg in ["리셋", "reset", "/reset", "취소", "그만"]:
        session.state = State.CHAT
        session.slots = {}
        session.pending_slot = None
        return respond(session, "CHAT", msg, "초기화했어. 다시 말해줘.")

    # BRIEF: 사용자가 답하면 pending_slot에 저장 후 다음 행동을 LLM에 요청
    if session.state == State.BRIEF:
        if session.pending_slot:
            session.slots[session.pending_slot] = msg

        data = call_llm(user_message="(brief 답변) " + msg, brief_answers=[f"{k}:{v}" for k, v in session.slots.items()])

        # final이면 종료
        if data.get("final"):
            session.state = State.CHAT
            session.pending_slot = None
            return respond(session, "CHAT", msg, data.get("reply", ""))

        # 계속 질문
        q = data.get("question") or ""

        inferred = infer_slot(q)

        slot = data.get("slot")

        session.pending_slot = inferred if inferred != "misc" else (slot or "misc")
        return respond(session, "BRIEF", msg, data.get("question") or "한 가지만 더 알려줘.")

    # CHAT: LLM이 라우팅
    # 자동 슬롯 추출(초기 메시지에서 country/price/channel/category 등)

    auto = extract_slots_from_text(msg)

    for k, v in auto.items():

        session.slots.setdefault(k, v)


    data = call_llm(user_message=msg, brief_answers=[f"{k}:{v}" for k, v in session.slots.items()])

    if data.get("need_question"):
        session.state = State.BRIEF
        q = data.get("question") or ""

        inferred = infer_slot(q)

        slot = data.get("slot")

        session.pending_slot = inferred if inferred != "misc" else (slot or "misc")
        return respond(session, "BRIEF", msg, data.get("question") or "몇 가지만 물어볼게.")

    return respond(session, "CHAT", msg, data.get("reply", ""))

@app.get("/")
def root():
    return {
        "name": "Beauty Agent",
        "status": "ok",
        "endpoints": ["/health", "/chat"]
    }




def respond(session: Session, state: str, message: str, reply: str):
    slots_json = json.dumps(session.slots, ensure_ascii=False) if session.slots else None
    insert_log(session.user_id, state, message, reply, slots_json)
    return ChatOut(user_id=session.user_id, state=state, reply=reply)

from fastapi import Query

@app.get("/history")
def history(user_id: str, limit: int = Query(20, ge=1, le=200)):
    rows = fetch_logs(user_id, limit)
    return [
        {"ts": ts, "state": state, "message": message, "reply": reply, "slots_json": slots_json}
        for (ts, state, message, reply, slots_json) in rows
    ]


def infer_slot(question: str) -> str:
    q = question.lower()
    if "국가" in question or "지역" in question or "country" in q or "region" in q:
        return "country"
    if "카테고리" in question or "선크림" in question or "선스틱" in question or "category" in q:
        return "category"
    if "가격" in question or "price" in q or "만원" in question:
        return "price"
    if "채널" in question or "유통" in question or "amazon" in q or "올리브영" in question or "channel" in q:
        return "channel"
    if "타겟" in question or "고객" in question or "target" in q:
        return "target"
    if "니즈" in question or "문제" in question or "need" in q:
        return "need"
    return "misc"




import re

def extract_slots_from_text(text: str) -> dict:
    t = text.strip()

    slots = {}

    # country/region (아주 단순 룰)
    if "미국" in t: slots["country"] = "미국"
    elif "일본" in t: slots["country"] = "일본"
    elif "중국" in t or "샤오홍수" in t: slots["country"] = "중국"
    elif "유럽" in t: slots["country"] = "유럽"
    elif "동남아" in t: slots["country"] = "동남아"

    # category
    if "선크림" in t: slots["category"] = "선크림"
    elif "선스틱" in t: slots["category"] = "선스틱"
    elif "수딩" in t and ("젤" in t or "겔" in t): slots["category"] = "수딩젤"
    elif "선케어" in t: slots["category"] = "선케어"

    # price band (예: 2~3만원대, 20~30달러)
    m = re.search(r'(\d+)\s*~\s*(\d+)\s*만원대', t)
    if m:
        slots["price"] = f"{m.group(1)}~{m.group(2)}만원대"

    # channel
    channels = []
    if "아마존" in t or "amazon" in t.lower(): channels.append("아마존")
    if "올리브영" in t or "olive young" in t.lower(): channels.append("올리브영글로벌")
    if "틱톡" in t or "tiktok" in t.lower(): channels.append("TikTok")
    if "인스타" in t or "instagram" in t.lower(): channels.append("Instagram")
    if "샤오홍수" in t or "red" in t.lower(): channels.append("RED")
    if channels:
        slots["channel"] = " + ".join(dict.fromkeys(channels))

    # need (키워드)
    needs = []
    if "민감" in t: needs.append("민감피부")
    if "진정" in t: needs.append("진정")
    if "백탁" in t: needs.append("백탁 적음")
    if needs:
        slots["need"] = " / ".join(dict.fromkeys(needs))

    return slots


