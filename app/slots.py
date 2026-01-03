import re

REQUIRED_SLOTS = ["country", "category", "target", "need", "price", "channel"]

def infer_slot(question: str) -> str:
    q = (question or "").lower()
    if ("국가" in question) or ("지역" in question) or ("country" in q) or ("region" in q):
        return "country"
    if ("카테고리" in question) or ("선크림" in question) or ("선스틱" in question) or ("category" in q):
        return "category"
    if ("가격" in question) or ("price" in q) or ("만원" in question):
        return "price"
    if ("채널" in question) or ("유통" in question) or ("amazon" in q) or ("올리브영" in question) or ("channel" in q):
        return "channel"
    if ("타겟" in question) or ("고객" in question) or ("target" in q):
        return "target"
    if ("니즈" in question) or ("문제" in question) or ("need" in q):
        return "need"
    return "misc"

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

def extract_slots_from_text(text: str) -> dict:
    t = (text or "").strip()
    tl = t.lower()
    slots: dict[str, str] = {}

    # country
    if "미국" in t or "usa" in tl or "u.s" in tl or "united states" in tl:
        slots["country"] = "미국"
    elif "일본" in t or "japan" in tl:
        slots["country"] = "일본"
    elif "동남아" in t:
        slots["country"] = "동남아"

    # category
    if "선크림" in t:
        slots["category"] = "선크림"
    elif "선스틱" in t:
        slots["category"] = "선스틱"
    elif "선케어" in t:
        slots["category"] = "선케어"

    # price
    m = re.search(r'(\d+)\s*~\s*(\d+)\s*만원대', t)
    if m:
        slots["price"] = f'{m.group(1)}~{m.group(2)}만원대'
    else:
        m2 = re.search(r'(\d+)\s*만원대', t)
        if m2:
            slots["price"] = f'{m2.group(1)}만원대'

    # channel
    chans = []
    if "아마존" in t or "amazon" in tl:
        chans.append("아마존")
    if "올리브영" in t or "olive young" in tl or "올영" in t:
        if "글로벌" in t or "global" in tl:
            chans.append("올리브영글로벌")
        else:
            chans.append("올리브영")
    if "qoo10" in tl or "큐텐" in t:
        chans.append("큐텐")
    if chans:
        slots["channel"] = " + ".join(dict.fromkeys(chans))

    # target
    m = re.search(r'(\d+)\s*~\s*(\d+)\s*대\s*(여성|남성)?', t)
    if m:
        age = f"{m.group(1)}~{m.group(2)}대"
        gender = (m.group(3) or "").strip()
        slots["target"] = (age + (" " + gender if gender else "")).strip()
    elif "20대" in t and "30대" in t:
        g = "여성" if "여성" in t else ("남성" if "남성" in t else "")
        slots["target"] = (("20~30대") + (" " + g if g else "")).strip()

    # need
    need_keys = []
    for k in ["민감", "진정", "백탁", "보습", "유분", "트러블", "톤업", "끈적", "가벼움"]:
        if k in t:
            need_keys.append(k)
    if need_keys:
        slots["need"] = " / ".join(dict.fromkeys(need_keys))

    return slots
