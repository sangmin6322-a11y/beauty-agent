from fastapi import FastAPI
from pydantic import BaseModel
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict

import os
from app.llm import call_llm

app = FastAPI(title="Beauty Agent", version="0.3.1")

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
        return ChatOut(user_id=session.user_id, state="CHAT", reply="초기화했어. 다시 말해줘.")

    # BRIEF: 사용자가 답하면 pending_slot에 저장 후 다음 행동을 LLM에 요청
    if session.state == State.BRIEF:
        if session.pending_slot:
            session.slots[session.pending_slot] = msg

        data = call_llm(user_message="(brief 답변) " + msg, brief_answers=[f"{k}:{v}" for k, v in session.slots.items()])

        # final이면 종료
        if data.get("final"):
            session.state = State.CHAT
            session.pending_slot = None
            return ChatOut(user_id=session.user_id, state="CHAT", reply=data.get("reply", ""))

        # 계속 질문
        session.pending_slot = data.get("slot") or "misc"
        return ChatOut(user_id=session.user_id, state="BRIEF", reply=data.get("question") or "한 가지만 더 알려줘.")

    # CHAT: LLM이 라우팅
    data = call_llm(user_message=msg, brief_answers=[])

    if data.get("need_question"):
        session.state = State.BRIEF
        session.pending_slot = data.get("slot") or "misc"
        return ChatOut(user_id=session.user_id, state="BRIEF", reply=data.get("question") or "몇 가지만 물어볼게.")

    return ChatOut(user_id=session.user_id, state="CHAT", reply=data.get("reply", ""))
