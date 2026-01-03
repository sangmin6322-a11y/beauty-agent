from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
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
from app.signals import fetch_reddit, build_pulse_from_signals, build_alerts_from_signals, fetch_social_signals
from app.insights import make_pulse, make_alerts

def respond(session, state, message, reply):
    """
    공통 응답 헬퍼:
    - 로그 저장(insert_log)
    - ChatOut 반환
    """
    try:
        import json
        slots = getattr(session, "slots", None)
        slots_json = json.dumps(slots, ensure_ascii=False) if slots else None
    except Exception:
        slots_json = None

    try:
        insert_log(session.user_id, state, message, reply, slots_json)
    except Exception:
        pass

    return ChatOut(user_id=session.user_id, state=state, reply=reply)
from app.llm import call_llm, call_radar
from app.slots import extract_slots_from_text, infer_slot, has_required_slots, render_launch_brief
from app.slots import extract_slots_from_text

# --- AUTO PATCH: social pulse (do not edit by hand) ---
from app.signals import fetch_social_signals, build_pulse_from_signals, build_alerts_from_signals
# --- /AUTO PATCH ---


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
app.mount("/static", StaticFiles(directory="app/static"), name="static")

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
from fastapi.staticfiles import StaticFiles
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












@app.get('/pulse')
def pulse(user_id: str, query: str = '', limit: int = 25):
  q = (query or '').strip()
  lim = max(1, min(int(limit or 25), 200))
  signals = fetch_social_signals(q, limit=lim) if q else []
  pulse = build_pulse_from_signals(signals)
  evidence = []
  for s in (signals or [])[:8]:
    evidence.append({
      'source': s.get('source') or 'reddit',
      'platform': s.get('platform') or 'reddit',
      'title': s.get('title') or '',
      'url': s.get('url') or '',
      'snippet': (s.get('text') or s.get('body') or '')[:240],
    })
  pulse['signals_count'] = len(signals)
  pulse['evidence'] = evidence
  return pulse@app.post("/pulse")
def pulse_post(payload: dict):
    user_id = (payload.get("user_id") or "").strip()
    query = (payload.get("query") or "").strip()
    limit = int(payload.get("limit") or 25)
    signals = fetch_social_signals(query, limit=limit)
    pulse = build_pulse_from_signals(signals)
    pulse["window"] = {"logs_count": 0, "signals_count": len(signals)}
    return pulse


@app.get("/alerts")
def alerts(user_id: str, limit: int = 50):
    rows = fetch_logs(user_id=user_id, limit=limit)
    return make_alerts(rows)

@app.post("/alerts")
def alerts_post(payload: dict):
    """
    POST /alerts
    payload: {"user_id": "...", "query": "...", "limit": 25}
    """
    user_id = (payload.get("user_id") or "").strip()
    query = (payload.get("query") or "").strip()
    limit = int(payload.get("limit") or 25)

    # 기존 GET /alerts 함수가 있으면 호출해서 로직 재사용
    try:
        return alerts(user_id=user_id, query=query, limit=limit)
    except TypeError:
        # 기존 alerts() 시그니처가 다르면 여기에서 직접 구성
        signals = fetch_social_signals(query, limit=limit) if query else []
        return {"alerts": build_alerts_from_signals(signals), "signals_count": len(signals)}



@app.get('/report')
def report(user_id: str, query: str, limit: int = 25):
  q = (query or '').strip()
  lim = max(1, min(int(limit or 25), 200))
  signals = fetch_social_signals(q, limit=lim) if q else []
  pulse = build_pulse_from_signals(signals)

  evidence = []
  for s in (signals or [])[:10]:
    evidence.append({
      'platform': s.get('platform') or s.get('source') or 'reddit',
      'title': s.get('title') or '',
      'url': s.get('url') or '',
      'snippet': (s.get('text') or s.get('body') or '')[:260],
    })

  return {
    'title': 'Social Signals Report',
    'query': q,
    'signals_count': len(signals),
    'insights': pulse.get('insights') or [],
    'core_evidence': evidence,
  }

# ===== BEGIN_REPORT_CARDS_V1 =====
# Card-news style report UI (HTML)

from datetime import datetime

def _escape_html(s: str) -> str:
  if s is None:
    return ""
  return (str(s)
    .replace("&","&amp;")
    .replace("<","&lt;")
    .replace(">","&gt;")
    .replace('"',"&quot;")
    .replace("'","&#39;"))

def _chips(top_list, label_map=None, max_n=8):
  label_map = label_map or {}
  out = []
  for item in (top_list or [])[:max_n]:
    try:
      k, v = item
    except Exception:
      continue
    name = label_map.get(k, k)
    out.append(f"<span class='chip'><b>{_escape_html(name)}</b> <span class='muted'>×{int(v)}</span></span>")
  if not out:
    out.append("<span class='muted'>No strong repeats detected (or filtered).</span>")
  return "".join(out)

def _pick_needs_and_risks(pulse: dict):
  needs, risks = [], []
  for it in (pulse.get("insights") or []):
    if not isinstance(it, dict):
      continue
    title = (it.get("title") or "").lower()
    top = it.get("top") or []
    # risk/faq 쪽
    if ("risk" in title) or ("faq" in title) or ("complaint" in title):
      risks = top
    else:
      # 첫 섹션을 needs로 간주
      if not needs:
        needs = top
  return needs, risks

@app.get("/report/cards", response_class=HTMLResponse)
def report_cards(user_id: str, query: str, limit: int = 25):
  q = (query or "").strip()
  lim = max(1, min(int(limit or 25), 200))

  signals = fetch_social_signals(q, limit=lim) if q else []
  pulse = build_pulse_from_signals(signals) if "build_pulse_from_signals" in globals() else {"insights": []}

  needs_top, risks_top = _pick_needs_and_risks(pulse)

  # label 조금 더 사람말로
  need_labels = {
    "sensitive": "Sensitive-friendly / soothing",
    "no_white_cast": "No white cast / invisible finish",
    "light_texture": "Light texture / non-greasy",
    "hydrating": "Hydrating",
    "oil_control": "Oil-control / matte",
    "no_eye_sting": "No eye sting",
  }
  risk_labels = {
    "breakouts": "Breakouts / clogged pores",
    "white_cast": "White cast",
    "pilling": "Pilling",
    "stings_eyes": "Stings eyes",
    "greasy": "Greasy / heavy",
    "drying": "Drying / tight",
    "irritation": "Irritation / redness",
    "fragrance": "Fragrance complaints",
  }

  # evidence cards
  ev_cards = []
  for s in (signals or [])[:10]:
    if not isinstance(s, dict):
      continue
    title = _escape_html(s.get("title") or "(no title)")
    url = _escape_html(s.get("url") or "")
    snippet = _escape_html((s.get("text") or s.get("body") or "")[:260])
    platform = _escape_html(s.get("platform") or s.get("source") or "social")
    ev_cards.append(f"""
      <div class="card">
        <div class="card-h">
          <div class="badge">{platform}</div>
          <a class="title" href="{url}" target="_blank" rel="noreferrer">{title}</a>
        </div>
        <div class="snippet">{snippet}</div>
      </div>
    """)

  if not ev_cards:
    ev_cards.append("<div class='muted'>No evidence items.</div>")

  now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

  html = f"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Social Signals Cards</title>
<style>
  :root {{
    --bg: #0b0c10;
    --card: #12141a;
    --stroke: rgba(255,255,255,.08);
    --text: rgba(255,255,255,.92);
    --muted: rgba(255,255,255,.62);
    --chip: rgba(255,255,255,.06);
    --chip2: rgba(255,255,255,.10);
  }}
  body {{
    margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
    background: radial-gradient(1200px 600px at 30% -10%, rgba(120,80,255,.25), transparent),
                radial-gradient(1000px 500px at 110% 20%, rgba(0,200,255,.18), transparent),
                var(--bg);
    color: var(--text);
  }}
  .wrap {{ max-width: 1060px; margin: 0 auto; padding: 24px; }}
  .top {{
    display:flex; gap:14px; align-items:flex-end; justify-content:space-between; flex-wrap:wrap;
    margin-bottom: 18px;
  }}
  .h1 {{ font-size: 22px; font-weight: 800; letter-spacing: .2px; }}
  .meta {{ color: var(--muted); font-size: 13px; }}
  .grid {{
    display:grid; grid-template-columns: repeat(12, 1fr); gap: 14px;
  }}
  .panel {{
    background: rgba(255,255,255,.03);
    border: 1px solid var(--stroke);
    border-radius: 16px;
    padding: 14px;
  }}
  .kpi {{
    display:flex; gap: 12px; align-items:center; justify-content:space-between;
  }}
  .kpi b {{ font-size: 18px; }}
  .sub {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
  .section-title {{ font-size: 14px; font-weight: 800; margin-bottom: 10px; }}
  .chip {{
    display:inline-flex; align-items:center; gap: 8px;
    background: var(--chip);
    border: 1px solid var(--stroke);
    padding: 8px 10px;
    border-radius: 999px;
    margin: 6px 6px 0 0;
    font-size: 13px;
  }}
  .muted {{ color: var(--muted); }}
  .badge {{
    display:inline-flex;
    border: 1px solid var(--stroke);
    background: var(--chip2);
    padding: 4px 8px;
    border-radius: 999px;
    font-size: 12px;
    color: var(--muted);
  }}
  .cards {{
    display:grid;
    grid-template-columns: repeat(2, minmax(0,1fr));
    gap: 14px;
  }}
  .card {{
    background: var(--card);
    border: 1px solid var(--stroke);
    border-radius: 16px;
    padding: 12px;
  }}
  .card-h {{
    display:flex; align-items:center; gap:10px; margin-bottom: 8px;
  }}
  .title {{
    color: var(--text);
    text-decoration: none;
    font-weight: 700;
    line-height: 1.25;
  }}
  .title:hover {{ text-decoration: underline; }}
  .snippet {{
    color: var(--muted);
    font-size: 13px;
    line-height: 1.45;
    overflow:hidden;
    display:-webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
  }}
  .col-12 {{ grid-column: span 12; }}
  .col-6 {{ grid-column: span 6; }}
  .col-4 {{ grid-column: span 4; }}
  .col-8 {{ grid-column: span 8; }}
  @media (max-width: 860px) {{
    .cards {{ grid-template-columns: 1fr; }}
    .col-6, .col-4, .col-8 {{ grid-column: span 12; }}
  }}
  .actions li {{ margin: 8px 0; color: var(--muted); }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <div class="h1">📌 Social Signals Card Report</div>
        <div class="meta">Query: <b>{_escape_html(q)}</b> · Generated: {now}</div>
      </div>
      <div class="panel kpi">
        <div>
          <div class="muted">Signals (cleaned)</div>
          <b>{len(signals)}</b>
        </div>
        <div class="muted">limit: {lim}</div>
      </div>
    </div>

    <div class="grid">
      <div class="panel col-6">
        <div class="section-title">① 글로벌 고객이 “기대하는 포인트” (Need)</div>
        <div>{_chips(needs_top, need_labels)}</div>
        <div class="sub">※ 반복 언급이 강한 키워드일수록 “기대 포인트” 가능성이 큼</div>
      </div>

      <div class="panel col-6">
        <div class="section-title">② 리뷰/FAQ 리스크 (Risk)</div>
        <div>{_chips(risks_top, risk_labels)}</div>
        <div class="sub">※ FAQ 문구·제형 테스트·클레임 가드레일 우선순위로 사용</div>
      </div>

      <div class="panel col-12">
        <div class="section-title">③ 핵심 판단 근거 (Evidence)</div>
        <div class="cards">
          {"".join(ev_cards)}
        </div>
      </div>

      <div class="panel col-12">
        <div class="section-title">④ 다음 액션 (Action)</div>
        <ul class="actions">
          <li><b>Need Top 1~2</b>를 제품 USP/카피로 고정하고, 경쟁 제품 리뷰에서 “반박 포인트(불만)”를 같이 수집</li>
          <li><b>Risk Top 1~3</b>는 “원인 가설 → 포뮬러/사용감 개선 → FAQ/사용법 가이드”로 패키징</li>
          <li>리테일(아마존/올영글로벌) 리뷰 키워드와 SNS 키워드가 겹치면 “진짜 니즈”로 확률 상승 → 알림 대상</li>
        </ul>
      </div>
    </div>
  </div>
</body>
</html>
"""
  return HTMLResponse(content=html)

# ===== END_REPORT_CARDS_V1 =====


# ===== BEGIN_HEALTH_V2 =====
@app.get("/health")
def health():
    return {"ok": True}
# ===== END_HEALTH_V2 =====
# ===== BEGIN_PULSE_POST_ALIAS_V2 =====
@app.post("/pulse")
def pulse_post(payload: dict):
    query = (payload.get("query") or "").strip()
    limit = int(payload.get("limit") or 25)
    limit = max(1, min(limit, 200))
    signals = fetch_social_signals(query, limit=limit) if query else []
    pulse = build_pulse_from_signals(signals)
    pulse["signals_count"] = len(signals)
    pulse["evidence"] = [
      {
        "platform": s.get("platform") or s.get("source") or "reddit",
        "title": s.get("title") or "",
        "url": s.get("url") or "",
        "snippet": (s.get("text") or s.get("body") or "")[:240],
      }
      for s in (signals or [])[:10] if isinstance(s, dict)
    ]
    return pulse
# ===== END_PULSE_POST_ALIAS_V2 =====
