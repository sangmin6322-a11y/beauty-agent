from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
import traceback
from pydantic import BaseModel
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict

import os
import re
import re
import json
from app.db import init_db, insert_log, fetch_logs
from app.llm import call_llm, call_radar
from app.slots import extract_slots_from_text, infer_slot, has_required_slots, render_launch_brief
from app.slots import extract_slots_from_text

def normalize_log_row(row):
    """
    fetch_logs가 dict / sqlite3.Row / tuple(list) 무엇을 주든
    항상 {"ts","state","message","reply","slots_json"} dict로 변환한다.
    """
    if row is None:
        return {"ts": None, "state": None, "message": None, "reply": "", "slots_json": None}

    # already dict
    if isinstance(row, dict):
        return {
            "ts": row.get("ts"),
            "state": row.get("state"),
            "message": row.get("message"),
            "reply": row.get("reply"),
            "slots_json": row.get("slots_json"),
        }

    # sqlite3.Row 같은 mapping
    try:
        if hasattr(row, "keys"):
            return {
                "ts": row["ts"] if "ts" in row.keys() else None,
                "state": row["state"] if "state" in row.keys() else None,
                "message": row["message"] if "message" in row.keys() else None,
                "reply": row["reply"] if "reply" in row.keys() else "",
                "slots_json": row["slots_json"] if "slots_json" in row.keys() else None,
            }
    except Exception:
        pass

    # tuple/list
    if isinstance(row, (tuple, list)) and len(row) >= 5:
        ts, state, message, reply, slots_json = row[0], row[1], row[2], row[3], row[4]
        return {"ts": ts, "state": state, "message": message, "reply": reply, "slots_json": slots_json}

    # fallback
    return {"ts": None, "state": None, "message": None, "reply": str(row), "slots_json": None}


app = FastAPI(title="Beauty Agent", version="0.3.3")

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    # 모든 500 에러를 JSON으로 보여줘서 원인 추적 가능하게 함
    return JSONResponse(
        status_code=500,
        content={"error": repr(exc), "trace": traceback.format_exc()},
    )

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

class RadarIn(BaseModel):
    user_id: str
    brief: str | None = None
    notes: str | None = None

class RadarOut(BaseModel):
    user_id: str
    reply: str

@app.get("/health")
def health():
    return {"ok": True, "version": "0.3.3"}

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

            # BRIEF 답변에서도 자동 슬롯 추출(가격/채널/니즈 등)

            auto = extract_slots_from_text(msg)

            session.slots.update(auto)
# 슬롯이 충분하면 LLM 추가 질문 없이 바로 종료


        if has_required_slots(session.slots):


            session.state = State.CHAT


            session.pending_slot = None


            return respond(session, "CHAT", msg, render_launch_brief(session.slots))



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

    session.slots.update(auto)
    data = call_llm(user_message=msg, brief_answers=[f"{k}:{v}" for k, v in session.slots.items()])
    if data.get("need_question"):
        session.state = State.BRIEF
        q = data.get("question") or ""

        inferred = infer_slot(q)

        slot = data.get("slot")

        session.pending_slot = inferred if inferred != "misc" else (slot or "misc")
        return respond(session, "BRIEF", msg, data.get("question") or "몇 가지만 물어볼게.")

    return respond(session, "CHAT", msg, data.get("reply", ""))

@app.get("/", include_in_schema=False)
def home():
    import os
    here = os.path.dirname(__file__)
    return FileResponse(os.path.join(here, "static", "index.html"))

@app.get("/api", include_in_schema=False)
def api_meta():
    return {"name":"Beauty Agent","status":"ok","endpoints":["/health","/chat","/history","/radar"]}
@app.get("/history")
def history(user_id: str, limit: int = 20):
    return fetch_logs(user_id=user_id, limit=limit)





@app.post("/radar", response_model=RadarOut)
def radar(payload: RadarIn):
    user_id = payload.user_id
    brief = (payload.brief or "").strip()
    notes = (payload.notes or "").strip()

    # brief가 없으면 DB history에서 최근 Launch Brief를 찾아 사용
    if not brief:
        logs = fetch_logs(user_id=user_id, limit=20)
        for row in logs:
            r = row.get("reply") or ""
            if r.startswith("[Launch Brief]"):
                brief = r
                break

    if not brief:
        return RadarOut(user_id=user_id, reply="최근 Launch Brief를 찾지 못했어. 먼저 /chat으로 Launch Brief를 만들어줘.")

    data = call_radar(launch_brief=brief, extra_notes=notes)
    return RadarOut(user_id=user_id, reply=data.get("reply", ""))


# ---- DEBUG ENDPOINTS (temporary) ----
from fastapi import Request
import traceback

@app.post("/debug/radar")
async def debug_radar(req: Request):
    try:
        body = await req.json()
        user_id = (body.get("user_id") or "").strip()
        extra_notes = body.get("extra_notes") or ""

        logs = [normalize_log_row(r) for r in fetch_logs(user_id=user_id, limit=50)]

        launch = None
        for row in logs:
            r = (row.get("reply") or "")
            if r.lstrip().startswith("[Launch Brief]"):
                launch = r
                break

        if not launch:
            return {"user_id": user_id, "reply": "no launch brief found", "logs_count": len(logs)}

        radar = call_radar(launch_brief=launch, extra_notes=extra_notes)
        return {"user_id": user_id, **radar}

    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}








