
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
    risks = _count_lex(signals, RISK_LEX)
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
    risks = _count_lex(signals, RISK_LEX)
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
