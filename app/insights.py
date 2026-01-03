import json
from collections import Counter

def _row_to_dict(row):
    # row가 dict이면 그대로
    if isinstance(row, dict):
        return row
    # tuple(ts,state,message,reply,slots_json) 형태 대응
    try:
        ts, state, message, reply, slots_json = row
        return {"ts": ts, "state": state, "message": message, "reply": reply, "slots_json": slots_json}
    except Exception:
        return {"ts": None, "state": None, "message": str(row), "reply": "", "slots_json": None}

def _extract_slots(row):
    d = _row_to_dict(row)
    sj = d.get("slots_json")
    if not sj:
        return {}
    try:
        return json.loads(sj)
    except Exception:
        return {}

def make_pulse(rows):
    """최근 로그(launch brief/brief 답변)를 기반으로 트렌드 요약 + 근거를 생성"""
    slots = [_extract_slots(r) for r in rows]
    slots = [s for s in slots if s]

    c_country = Counter([s.get("country") for s in slots if s.get("country")])
    c_cat     = Counter([s.get("category") for s in slots if s.get("category")])
    c_need    = Counter([s.get("need") for s in slots if s.get("need")])
    c_price   = Counter([s.get("price") for s in slots if s.get("price")])
    c_channel = Counter([s.get("channel") for s in slots if s.get("channel")])

    # 근거(evidence): 상위 항목이 실제로 어떤 메시지/브리프에서 나왔는지 샘플 3개
    def evidence_for(key, value, n=3):
        out = []
        for r in rows:
            s = _extract_slots(r)
            if s.get(key) == value:
                d = _row_to_dict(r)
                out.append({"ts": d.get("ts"), "message": d.get("message"), "slots": s})
            if len(out) >= n:
                break
        return out

    top_country = c_country.most_common(3)
    top_cat     = c_cat.most_common(3)
    top_need    = c_need.most_common(5)
    top_price   = c_price.most_common(3)
    top_channel = c_channel.most_common(5)

    return {
        "window": {"logs_count": len(rows)},
        "signals": {
            "top_country": top_country,
            "top_category": top_cat,
            "top_need": top_need,
            "top_price": top_price,
            "top_channel": top_channel,
        },
        "insights": [
            {
                "title": "글로벌 고객이 기대하는 포인트(니즈) 상위",
                "summary": "최근 입력 데이터(brief/launch) 기준으로 니즈 키워드가 반복 출현.",
                "evidence": [{"need": v, "count": c, "examples": evidence_for("need", v)} for (v, c) in top_need[:3]]
            },
            {
                "title": "채널 믹스 상위",
                "summary": "구매 여정이 리테일(리뷰) + SNS(바이럴) 결합이므로 채널이 의사결정의 중심.",
                "evidence": [{"channel": v, "count": c, "examples": evidence_for("channel", v)} for (v, c) in top_channel[:3]]
            }
        ]
    }

def make_alerts(rows):
    """리스크/이슈 키워드(불만 가능) 기반 간단 알림 + 근거"""
    alerts = []
    for r in rows:
        d = _row_to_dict(r)
        s = _extract_slots(r)
        need = (s.get("need") or "")
        msg = (d.get("message") or "")

        # 예시 룰(추후 실제 리뷰 데이터 기반으로 정교화)
        if "백탁" in need or "white cast" in need.lower():
            alerts.append({
                "type": "review_risk",
                "title": "백탁(white cast) 관련 불만 위험",
                "why": "선케어에서 가장 빠르게 악평이 쌓이는 전형적 포인트.",
                "evidence": {"ts": d.get("ts"), "message": msg, "slots": s},
                "action": ["텍스처/흡수/톤업 여부 명확히 표기", "전/후 사진 가이드", "피부톤별 테스트 문구"]
            })
        if "민감" in need or "sensitive" in need.lower():
            alerts.append({
                "type": "claims_risk",
                "title": "민감피부 타겟 → 성분/자극 관련 검증 요구 증가",
                "why": "‘진정/저자극’ 클레임은 근거(테스트/성분) 요구가 강함.",
                "evidence": {"ts": d.get("ts"), "message": msg, "slots": s},
                "action": ["민감피부 패널 테스트/인체적용시험", "향료/알러젠 표시", "전성분 FAQ 준비"]
            })

    # 중복 줄이기(같은 title은 1개만)
    uniq = {}
    for a in alerts:
        uniq[a["title"]] = a
    return {
        "alerts_count": len(uniq),
        "alerts": list(uniq.values())[:10]
    }
