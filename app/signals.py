
import os
import re
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import httpx

# -------------------------
# Utilities
# -------------------------
def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def normalize_created_at(s: str) -> str:
    # best-effort normalize to ISO; if unknown just return now
    try:
        # if already iso-like
        if "T" in s and ("+" in s or "Z" in s):
            return s.replace("Z", "+00:00")
        # unix?
        if s.isdigit():
            return datetime.fromtimestamp(int(s), tz=timezone.utc).isoformat()
    except Exception:
        pass
    return _now_iso()

def _truncate(t: str, n: int = 220) -> str:
    t = (t or "").strip().replace("\n", " ")
    return t[:n]

# -------------------------
# Fetchers (policy-safe)
# -------------------------

def fetch_reddit(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    """
    Public reddit search JSON. (No login / no bypass)
    """
    q = (query or "").strip()
    if not q:
        return []
    lim = max(1, min(int(limit or 25), 100))
    url = "https://www.reddit.com/search.json"
    headers = {"User-Agent": "beauty-agent/0.1 (by u/yourteam)"}  # required-ish
    params = {"q": q, "limit": lim, "sort": "new"}
    out = []
    try:
        with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as c:
            r = c.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        for ch in (data.get("data", {}).get("children", []) or []):
            d = ch.get("data", {}) or {}
            permalink = d.get("permalink") or ""
            out.append({
                "source": "reddit",
                "platform": "reddit",
                "created_at": normalize_created_at(str(d.get("created_utc") or "")),
                "url": ("https://www.reddit.com" + permalink) if permalink else (d.get("url") or ""),
                "title": d.get("title") or "",
                "text": _truncate(d.get("selftext") or ""),
                "metrics": {
                    "score": d.get("score") or 0,
                    "comments": d.get("num_comments") or 0,
                    "subreddit": d.get("subreddit") or ""
                }
            })
    except Exception:
        return []
    return out

def fetch_google_news_rss(query: str, limit: int = 25) -> List[Dict[str, Any]]:
    """
    Public Google News RSS search (no key). Good for 'retail/news chatter' signals.
    """
    q = (query or "").strip()
    if not q:
        return []
    lim = max(1, min(int(limit or 25), 50))
    # NOTE: RSS is public; we only parse XML.
    url = "https://news.google.com/rss/search"
    params = {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    headers = {"User-Agent": "beauty-agent/0.1"}
    out = []
    try:
        with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as c:
            r = c.get(url, params=params)
            r.raise_for_status()
            xml = r.text
        # minimal xml parsing without extra deps
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        items = root.findall(".//item")[:lim]
        for it in items:
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            pub = (it.findtext("pubDate") or "").strip()
            desc = (it.findtext("description") or "").strip()
            out.append({
                "source": "google_news_rss",
                "platform": "news",
                "created_at": normalize_created_at(pub),
                "url": link,
                "title": title,
                "text": _truncate(desc),
                "metrics": {}
            })
    except Exception:
        return []
    return out

def fetch_serper_search(*args, **kwargs):
    return []


NEED_LEX = {
    "sensitive/soothing": [r"\bsensitive\b", r"\bsooth(ing|e)?\b", r"\bcalm(ing)?\b", r"\birritat(ed|ion)\b"],
    "no-white-cast": [r"white cast", r"\bno[- ]?cast\b", r"\binvisible\b", r"\btransparent\b"],
    "lightweight": [r"\blightweight\b", r"\bnon[- ]?greasy\b", r"\bfast[- ]?absor(b|ption)\b"],
    "hydrating": [r"\bhydrat(ing|ion)\b", r"\bmoistur(ize|izing|izing)\b", r"\bdewy\b"],
}

def _count_lex(signals: List[Dict[str, Any]], lex: Dict[str, List[str]]) -> Dict[str, int]:
    counts = {k: 0 for k in lex.keys()}
    for s in (signals or []):
        txt = ((s.get("title") or "") + " " + (s.get("text") or "")).lower()
        for k, pats in lex.items():
            for p in pats:
                if re.search(p, txt):
                    counts[k] += 1
                    break
    # drop zeros
    return {k: v for k, v in counts.items() if v > 0}

def build_pulse_from_signals(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    risks = _count_lex(signals, globals().get("RISK_LEX", DEFAULT_RISK_LEX))
    needs = _count_lex(signals, NEED_LEX)

    # evidence: keep top 8 with url+snippet
    evidence = [{
        "source": s.get("source"),
        "platform": s.get("platform"),
        "title": s.get("title"),
        "url": s.get("url"),
        "snippet": _truncate(s.get("text") or "", 180),
    } for s in (signals or [])[:8]]

    insights = []
    if needs:
        top = sorted(needs.items(), key=lambda x: x[1], reverse=True)[:5]
        insights.append({
            "title": "湲濡쒕쾶 怨좉컼??湲곕??섎뒗 ?ъ씤???덉쫰) ?곸쐞",
            "summary": "SNS/由ы뀒???좏샇?먯꽌 諛섎났 ?깆옣???덉쫰 ?ㅼ썙??湲곗? ?곸쐞 ??ぉ.",
            "top": top,
            "evidence": evidence[:4],
        })
    if risks:
        top = sorted(risks.items(), key=lambda x: x[1], reverse=True)[:5]
        insights.append({
            "title": "由щ럭/FAQ 由ъ뒪???곸쐞",
            "summary": "遺덈쭔/由ъ뒪???ㅼ썙???멸툒??湲곕컲 ?곸쐞 ??ぉ.",
            "top": top,
            "evidence": evidence[:4],
        })
    if not insights:
        insights.append({
        "title": "",
            "summary": "?꾩옱 荑쇰━?먯꽌 ?좎쓽誘명븳 ?좏샇媛 異⑸텇???섏쭛?섏? ?딆븯?? (?ㅼ썙??援ъ껜??沅뚯옣)",
            "top": [],
            "evidence": evidence[:4],
        })

    return {
        "signals_count": len(signals or []),
        "evidence": evidence,
        "insights": insights,
    }

def build_alerts_from_signals(signals: List[Dict[str, Any]], threshold: int = 4) -> Dict[str, Any]:
    risks = _count_lex(signals, globals().get("RISK_LEX", DEFAULT_RISK_LEX))
    alerts = []
    for k, v in sorted(risks.items(), key=lambda x: x[1], reverse=True):
        if v >= threshold:
            alerts.append({
                "type": "review_risk",
                "risk": k,
                "count": v,
                "message": f"由ъ뒪??'{k}' ?멸툒??{v}嫄?愿李곕맖. FAQ/?쒗삎 蹂댁셿 ?ъ씤???먭? ?꾩슂."
            })
    return {"alerts": alerts, "signals_count": len(signals or [])}


# --- Added: unified social signals fetcher (alias) ---
def fetch_social_signals(query: str, limit: int = 25):
    """
    Unified social signals fetcher.
    Currently uses Reddit as the primary signal source.
    Future: TikTok/Instagram/RED(Xiaohongshu)/YouTube/OliveYoung Global can be added here.
    """
    q = (query or "").strip()
    lim = max(1, min(int(limit or 25), 200))

    # Prefer existing fetch_reddit if available
    if "fetch_reddit" in globals() and callable(globals().get("fetch_reddit")):
        return fetch_reddit(q, limit=lim)

    # Fallback: empty list (prevents server crash)
    return []


# --- Lexicons (added to prevent NameError) ---
# risk lexicon: 키 = 리스크 타입, 값 = 매칭할 키워드 리스트
RISK_LEX = {
    "white_cast": ["white cast", "whitecast", "ashy", "gray cast", "tone-up too much", "톤업 과함", "백탁", "회색끼"],
    "pilling": ["pilling", "pill", "balls up", "rolling", "밀림", "때처럼", "각질처럼"],
    "breakouts": ["breakout", "breakouts", "acne", "pimples", "clog", "comedone", "트러블", "여드름", "모공 막힘"],
    "stings_eyes": ["stings eyes", "burns eyes", "eye sting", "irritates eyes", "눈시림", "눈 따가움", "눈물"],
    "greasy": ["greasy", "oily", "shiny", "heavy", "번들", "기름짐", "유분", "무거움"],
    "drying": ["dry", "drying", "tight", "flaky", "건조", "당김", "각질"],
    "irritation": ["irritation", "irritated", "rash", "redness", "sensitive", "자극", "따가움", "붉어짐", "민감"],
    "fragrance": ["fragrance", "perfume", "scent", "smell", "향", "향료", "냄새"],
}

# (선택) 니즈/선호 lexicon이 필요하면 여기 추가로 확장 가능
NEED_LEX = {
    "soothing": ["soothing", "calming", "cica", "centella", "진정", "시카", "민감"],
    "no_white_cast": ["no white cast", "zero white cast", "transparent", "백탁 없음", "백탁 적음"],
    "light_texture": ["light", "lightweight", "watery", "serum", "가벼움", "워터리", "산뜻"],
    "tone_up": ["tone up", "tone-up", "톤업"],
}

# --- Default lexicons (hotfix: prevent NameError) ---
DEFAULT_RISK_LEX = {
    "white_cast": ["white cast", "whitecast", "ashy", "gray cast", "톤업 과함", "백탁", "회색끼"],
    "pilling": ["pilling", "pill", "balls up", "rolling", "밀림", "때처럼", "각질처럼"],
    "breakouts": ["breakout", "breakouts", "acne", "pimples", "clog", "comedone", "트러블", "여드름", "모공 막힘"],
    "stings_eyes": ["stings eyes", "burns eyes", "eye sting", "irritates eyes", "눈시림", "눈 따가움", "눈물"],
    "greasy": ["greasy", "oily", "shiny", "heavy", "번들", "기름짐", "유분", "무거움"],
    "drying": ["dry", "drying", "tight", "flaky", "건조", "당김", "각질"],
    "irritation": ["irritation", "irritated", "rash", "redness", "sensitive", "자극", "따가움", "붉어짐", "민감"],
    "fragrance": ["fragrance", "perfume", "scent", "smell", "향", "향료", "냄새"],
}


# --- Relevance filtering for social signals ---
import re
from urllib.parse import urlparse

BLACKLIST_DOMAINS = {"wogame.store", "wordens.wogame.store"}

def _tokenize_query(q: str):
  q = (q or "").lower()
  toks = [t for t in re.split(r"[^a-z0-9가-힣]+", q) if len(t) >= 3]
  return toks

def _looks_like_spam(sig: dict) -> bool:
  url = (sig.get("url") or "").strip()
  if url:
    d = urlparse(url).netloc.lower()
    if any(bad in d for bad in BLACKLIST_DOMAINS):
      return True
  title = (sig.get("title") or "").lower()
  text = (sig.get("text") or sig.get("body") or "").lower()
  if "read online" in title or "prologue" in title or "read online" in text:
    return True
  return False

def _is_relevant(sig: dict, q: str) -> bool:
  if not isinstance(sig, dict):
    return False
  if _looks_like_spam(sig):
    return False

  toks = _tokenize_query(q)
  hay = ((sig.get("title") or "") + " " + (sig.get("text") or sig.get("body") or "")).lower()

  must = ["sunscreen","spf","uv","sun","white cast","sensitive","korean","k-beauty","skincare"]
  if not any(m in hay for m in must):
    if toks and not any(t in hay for t in toks):
      return False

  if toks and not any(t in hay for t in toks):
    return False

  return True

def clean_signals(signals: list, query: str):
  seen = set()
  out = []
  dropped = 0
  for s in signals or []:
    if not isinstance(s, dict):
      dropped += 1
      continue
    url = (s.get("url") or "").strip()
    if url and url in seen:
      dropped += 1
      continue
    if not _is_relevant(s, query):
      dropped += 1
      continue
    if url:
      seen.add(url)
    out.append(s)
  return out, dropped

# ===== BEGIN_OVERRIDE_CLEAN_V2 =====
# This block is appended by patch_fix_noise_and_mojibake.ps1
# It overrides filtering + pulse titles safely (last-definition wins).

import re
from urllib.parse import urlparse

NEGATIVE_KEYWORDS = [
  "read online", "prologue", "novel", "romance", "shortstory",
  "microsoft rewards", "egift", "beermoney", "robisons", "robinsons",
  "giveaway", "coupon", "promo code"
]

BLACKLIST_DOMAINS = {
  "wogame.store", "wordens.wogame.store"
}

def _tokenize_query_v2(q: str):
  q = (q or "").lower()
  toks = [t for t in re.split(r"[^a-z0-9가-힣]+", q) if len(t) >= 3]
  # 너무 흔한 토큰 제거(잡음 방지)
  stop = {"korean", "beauty", "k", "be", "skin", "care"}
  return [t for t in toks if t not in stop]

def _looks_like_spam_v2(sig: dict) -> bool:
  url = (sig.get("url") or "").strip()
  if url:
    d = urlparse(url).netloc.lower()
    if any(bad in d for bad in BLACKLIST_DOMAINS):
      return True

  title = (sig.get("title") or "").lower()
  text = (sig.get("text") or sig.get("body") or "").lower()
  hay = title + " " + text

  for kw in NEGATIVE_KEYWORDS:
    if kw in hay:
      return True
  return False

def _is_relevant_v2(sig: dict, q: str) -> bool:
  if not isinstance(sig, dict):
    return False
  if _looks_like_spam_v2(sig):
    return False

  title = (sig.get("title") or "").lower()
  text = (sig.get("text") or sig.get("body") or "").lower()
  hay = title + " " + text

  # "선케어/스킨케어" 컨텍스트 최소 조건 강화
  must_any = [
    "sunscreen", "sun screen", "spf", "uv", "uva", "uvb",
    "skincare", "skin care", "skin", "dermat", "moistur", "irritat",
    "white cast", "sensitive"
  ]
  if not any(m in hay for m in must_any):
    return False

  # query 토큰 최소 2개 이상 매칭(잡음 제거)
  toks = _tokenize_query_v2(q)
  if toks:
    hit = sum(1 for t in toks if t in hay)
    if hit < min(2, len(toks)):  # 토큰이 많을수록 더 엄격
      return False

  return True

def clean_signals(signals: list, query: str):
  seen = set()
  out = []
  dropped = 0
  for s in (signals or []):
    if not isinstance(s, dict):
      dropped += 1
      continue
    url = (s.get("url") or "").strip()
    if url and url in seen:
      dropped += 1
      continue
    if not _is_relevant_v2(s, query):
      dropped += 1
      continue
    if url:
      seen.add(url)
    out.append(s)
  return out, dropped

def fetch_social_signals(query: str, limit: int = 25):
  """
  Unified signals fetcher: Reddit -> clean_signals (V2 strict)
  """
  q = (query or "").strip()
  lim = max(1, min(int(limit or 25), 200))
  raw = fetch_reddit(q, limit=lim) if "fetch_reddit" in globals() and callable(globals().get("fetch_reddit")) else []
  cleaned, _dropped = clean_signals(raw, q)
  return cleaned

# Fix mojibake: override titles/summaries to ASCII (stable in any encoding)
try:
  _build_pulse_from_signals_old = build_pulse_from_signals
except Exception:
  _build_pulse_from_signals_old = None

def build_pulse_from_signals(signals):
  pulse = _build_pulse_from_signals_old(signals) if _build_pulse_from_signals_old else {"insights": []}
  ins = pulse.get("insights") or []
  if isinstance(ins, list):
    if len(ins) >= 1 and isinstance(ins[0], dict):
      ins[0]["title"] = "Top customer expectations (needs)"
      ins[0]["summary"] = "Most repeated need keywords observed in social/retail signals."
    if len(ins) >= 2 and isinstance(ins[1], dict):
      ins[1]["title"] = "Top review risks / FAQ triggers"
      ins[1]["summary"] = "Most repeated complaint/risk keywords observed."
    pulse["insights"] = ins
  return pulse

# ===== END_OVERRIDE_CLEAN_V2 =====

