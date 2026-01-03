import re
from collections import Counter

# 매우 라이트한 룰 기반 시그널 추출기 (외부 크롤링 없이 "입력된 텍스트" 기준)
INGREDIENTS = [
    "centella", "cica", "madecassoside", "panthenol", "ceramide", "hyaluronic",
    "niacinamide", "zinc", "titanium dioxide", "zinc oxide",
    "시카", "센텔라", "마데카소사이드", "판테놀", "세라마이드", "히알루론산", "나이아신아마이드",
    "징크", "티타늄", "징크옥사이드"
]

TEXTURES = [
    "gel", "essence", "serum", "watery", "milk", "cream", "stick", "lotion", "fluid",
    "젤", "에센스", "세럼", "워터리", "밀크", "크림", "스틱", "로션", "플루이드"
]

CLAIMS = [
    "soothing", "calming", "sensitive", "no white cast", "whitecast", "non-greasy",
    "fragrance-free", "reef-safe", "non-comedogenic", "mineral", "chemical", "hybrid",
    "SPF", "PA++++", "broad spectrum",
    "진정", "민감", "저자극", "백탁", "백탁없", "끈적", "무향", "향료무", "논코메도",
    "무기자차", "유기자차", "혼합자차", "SPF", "PA++++", "광범위"
]

PAINS = [
    "white cast", "whitecast", "pilling", "greasy", "sticky", "irritation", "sting",
    "breakout", "acne", "dry", "burn", "allergy",
    "백탁", "밀림", "번들", "끈적", "자극", "따가", "트러블", "여드름", "건조", "화끈", "알러지"
]

POS_WORDS = ["love", "great", "amazing", "recommend", "works", "holy grail", "good", "smooth", "light",
             "좋", "추천", "만족", "재구매", "인생템", "가벼", "부드", "편하", "최고"]
NEG_WORDS = ["hate", "bad", "worst", "burn", "irritat", "breakout", "doesn't", "not work",
             "별로", "최악", "실망", "자극", "따갑", "트러블", "환불", "안맞", "안되"]

def _norm(s: str) -> str:
    return (s or "").strip()

def _find_snippets(text: str, term: str, window: int = 40, max_snip: int = 4):
    t = text
    snips = []
    for m in re.finditer(re.escape(term), t, flags=re.IGNORECASE):
        a = max(0, m.start() - window)
        b = min(len(t), m.end() + window)
        snip = t[a:b].replace("\n", " ").strip()
        if snip and snip not in snips:
            snips.append(snip)
        if len(snips) >= max_snip:
            break
    return snips

def extract_signals(text: str) -> dict:
    t = _norm(text)
    tl = t.lower()

    # 간이 감성
    pos = sum(1 for w in POS_WORDS if w.lower() in tl)
    neg = sum(1 for w in NEG_WORDS if w.lower() in tl)
    sentiment = "pos" if pos > neg else ("neg" if neg > pos else "mixed")

    def count_terms(terms):
        c = Counter()
        for term in terms:
            if term.lower() in tl:
                c[term] += tl.count(term.lower())
        return c

    ing = count_terms(INGREDIENTS)
    tex = count_terms(TEXTURES)
    clm = count_terms(CLAIMS)
    pain = count_terms(PAINS)

    # 키워드(간단 토큰)
    tokens = re.findall(r"[A-Za-z가-힣0-9\+\#]{2,}", t)
    top_tokens = [w for (w, n) in Counter([x.lower() for x in tokens]).most_common(20)]

    # 근거 스니펫: pain/claim 중심
    evidence = []
    for term, _ in (pain.most_common(5) + clm.most_common(5)):
        for snip in _find_snippets(t, term):
            evidence.append({"term": term, "snippet": snip})
        if len(evidence) >= 12:
            break

    return {
        "sentiment": sentiment,
        "counts": {
            "ingredients": dict(ing),
            "textures": dict(tex),
            "claims": dict(clm),
            "pains": dict(pain),
        },
        "top_tokens": top_tokens,
        "evidence_snippets": evidence,
        "raw_len": len(t),
    }

def merge_signals(signals_list: list[dict]) -> dict:
    out = {"sentiment": "mixed", "counts": {"ingredients":{}, "textures":{}, "claims":{}, "pains":{}},
           "top_tokens": [], "evidence_snippets": []}

    c_ing = Counter()
    c_tex = Counter()
    c_clm = Counter()
    c_pain = Counter()
    tok = Counter()
    sent = Counter()

    for s in signals_list:
        sent[s.get("sentiment","mixed")] += 1
        for k, v in (s.get("counts", {}).get("ingredients", {}) or {}).items(): c_ing[k] += int(v)
        for k, v in (s.get("counts", {}).get("textures", {}) or {}).items(): c_tex[k] += int(v)
        for k, v in (s.get("counts", {}).get("claims", {}) or {}).items(): c_clm[k] += int(v)
        for k, v in (s.get("counts", {}).get("pains", {}) or {}).items(): c_pain[k] += int(v)
        for w in (s.get("top_tokens") or []): tok[w] += 1
        for e in (s.get("evidence_snippets") or []):
            if len(out["evidence_snippets"]) < 20:
                out["evidence_snippets"].append(e)

    out["counts"]["ingredients"] = dict(c_ing.most_common(15))
    out["counts"]["textures"] = dict(c_tex.most_common(15))
    out["counts"]["claims"] = dict(c_clm.most_common(20))
    out["counts"]["pains"] = dict(c_pain.most_common(20))
    out["top_tokens"] = [w for (w, n) in tok.most_common(25)]

    # 최빈 감성
    out["sentiment"] = sent.most_common(1)[0][0] if sent else "mixed"
    return out
