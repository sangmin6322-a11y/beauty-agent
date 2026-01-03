from fastapi import FastAPI
from pydantic import BaseModel
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict

import os
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

        session.pending_slot = data.get("slot") or infer_slot(q)
        return respond(session, "BRIEF", msg, data.get("question") or "한 가지만 더 알려줘.")

    # CHAT: LLM이 라우팅
    data = call_llm(user_message=msg, brief_answers=[])

    if data.get("need_question"):
        session.state = State.BRIEF
        q = data.get("question") or ""

        session.pending_slot = data.get("slot") or infer_slot(q)
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


