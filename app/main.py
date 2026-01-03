from fastapi import FastAPI
from fastapi.responses import JSONResponse
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
    # target (예: 20~30대 여성 / 20대~30대 여성)
    m = re.search(r'(\d+)\s*~\s*(\d+)\s*대\s*(여성|남성)?', t)
    if m:
        age = f"{m.group(1)}~{m.group(2)}대"
        gender = (m.group(3) or "").strip()
        slots["target"] = (age + (" " + gender if gender else "")).strip()
    elif ("20대" in t and "30대" in t) or "20~30대" in t:
        g = "여성" if "여성" in t else ("남성" if "남성" in t else "")
        slots["target"] = (("20~30대") + (" " + g if g else "")).strip()

    # need (키워드)
    needs = []
    if "민감" in t: needs.append("민감피부")
    if "진정" in t: needs.append("진정")
    if "백탁" in t: needs.append("백탁 적음")
    if needs:
        slots["need"] = " / ".join(dict.fromkeys(needs))

    return slots




REQUIRED_SLOTS = ["country", "category", "target", "need", "price", "channel"]

def has_required_slots(slots: dict) -> bool:
    return all(slots.get(k) for k in REQUIRED_SLOTS)

def render_launch_brief(slots: dict) -> str:
    country = slots.get("country", "N/A")
    category = slots.get("category", "N/A")
    target = slots.get("target", "N/A")
    need = slots.get("need", "N/A")
    price = slots.get("price", "N/A")
    channel = slots.get("channel", "N/A")

    core_claim = f"{target}을 위한 {need} 컨셉의 {category}"
    next_action = "경쟁 제품/리뷰 기반 USP 3개 확정"

    return (
        "[Launch Brief]\n"
        f"- Country/Region: {country}\n"
        f"- Category: {category}\n"
        f"- Target: {target}\n"
        f"- Key Need: {need}\n"
        f"- Price Band: {price}\n"
        f"- Channel Mix: {channel}\n"
        f"- Core Claim (한 문장): {core_claim}\n"
        f"- Next Action (1개): {next_action}\n"
    )





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




