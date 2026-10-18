#!/usr/bin/env python3
"""동네·상점가·골목·동 축제 수집 (Google News RSS). update_events에서 호출."""
import email.utils
import hashlib
import html
import re
import time
import urllib.parse

LOCAL_FEST_QUERIES = [
    "부산 상점가 축제",
    "부산 골목 축제",
    "부산 동 축제 OR 마을축제",
    "부산 젊음의거리 페스타 OR 상인회 축제",
    "부산 행정복지센터 축제 OR 주민자치회 축제",
    "부산 골목상권 축제 OR 야장 축제",
]

GU_HINTS = [
    ("해운대", "해운대구"), ("기장", "기장군"), ("사상", "사상구"), ("사하", "사하구"),
    ("수영", "수영구"), ("연제", "연제구"), ("금정", "금정구"), ("강서", "강서구"),
    ("동래", "동래구"), ("부산진", "부산진구"), ("영도", "영도구"), ("남구", "남구"),
    ("북구", "북구"), ("중구", "중구"), ("서구", "서구"), ("동구", "동구"),
    ("덕천", "북구"), ("광안", "수영구"), ("하단", "사하구"), ("감천", "사하구"),
    ("서면", "부산진구"), ("남포", "중구"), ("송정", "해운대구"), ("구포", "북구"),
    ("명륜", "동래구"), ("보수동", "중구"), ("하리단", "사하구"),
]

LOCAL_NEG = re.compile(
    r"성료|마무리|폐막|취소|연기|서울|인천|대구|광주|대전|울산(?!교대)|경기|강원|충청|전라|제주|"
    r"송파|용산|서산|칠곡|시흥|안성|포천|문학동|왜관|청라"
)


def _gu_from_text(text):
    for k, g in GU_HINTS:
        if k in text:
            return g
    return "부산 전역"


def scrape_local_festivals(U, limit_per_q=12):
    """U = update_events module. Returns list of event dicts (type=동네축제)."""
    out, seen = [], set()
    year_hint = U.NOW.year
    for q in LOCAL_FEST_QUERIES:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": q + " when:45d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
        )
        try:
            s = U.fetch(url, tries=1, timeout=12, verify=True)
        except Exception as e:
            U.log("local fest news fail", q, e)
            continue
        for it in re.findall(r"<item>(.*?)</item>", s or "", re.S)[:limit_per_q]:
            def g(tag, _it=it):
                m = re.search(fr"<{tag}(?:\s[^>]*)?>(.*?)</{tag}>", _it, re.S)
                return html.unescape((m.group(1) if m else "")).strip()

            title = re.sub(r"\s+-\s+[^-]+$", "", g("title"))
            link = g("link")
            src = re.sub(r"<[^>]+>", "", g("source")) or "뉴스"
            desc = re.sub(r"<[^>]+>", " ", html.unescape(g("description")))
            text = title + " " + desc
            if "부산" not in text:
                continue
            if LOCAL_NEG.search(title):
                continue
            if not re.search(r"축제|페스타|한마당|야장|페스티벌", text):
                continue
            if re.search(r"국제영화제|자갈치축제|불꽃축제|록페스티벌|비프|BIFF|벡스코", title):
                continue
            rng = U.parse_range(text, year_hint) or U.parse_range(title, year_hint)
            if not rng:
                m = re.search(r"(\d{1,2})\s*[~∼\-]\s*(\d{1,2})\s*일", title)
                m2 = re.search(r"(?<!\d)(\d{1,2})\s*일(?!\s*[:\d])", title)
                pub = g("pubDate")
                try:
                    dt = email.utils.parsedate_to_datetime(pub).astimezone(U.KST)
                    y, mo = dt.year, dt.month
                except Exception:
                    y, mo = U.NOW.year, U.NOW.month
                if m:
                    try:
                        a = __import__("datetime").date(y, mo, int(m.group(1)))
                        b = __import__("datetime").date(y, mo, int(m.group(2)))
                        if b < a:
                            if mo < 12:
                                b = __import__("datetime").date(y, mo + 1, int(m.group(2)))
                            else:
                                b = __import__("datetime").date(y + 1, 1, int(m.group(2)))
                        rng = (a.isoformat(), b.isoformat())
                    except ValueError:
                        rng = None
                elif m2:
                    try:
                        a = __import__("datetime").date(y, mo, int(m2.group(1)))
                        rng = (a.isoformat(), a.isoformat())
                    except ValueError:
                        rng = None
            if not rng:
                continue
            s0, e0 = rng
            if e0 < U.TODAY:
                continue
            # 이름: 따옴표 안 축제명 우선, 없으면 “…축제/페스타” 구문
            name = ""
            qm = re.search(r"[‘'\"“]([^’'\"”]{4,50}(?:축제|페스타|한마당|페스티벌)[^’'\"”]{0,20})[’'\"”]", title)
            if qm:
                name = qm.group(1).strip()
            if not name:
                km = re.search(r"([가-힣A-Za-z0-9][가-힣A-Za-z0-9 ·]{1,40}(?:젊음의거리\s*)?(?:축제|페스타|한마당|페스티벌))", title)
                if km:
                    name = km.group(1).strip()
            if not name:
                continue
            name = re.sub(r"^(제?\d+회\s*)", lambda m: m.group(1), name)  # keep 제N회
            name = re.sub(r"^(부산\s*|부산시\s*|부산\s*[가-힣]+구,\s*)", "", name).strip()
            # "감천문화마을서 31일 골목축제" → "감천문화마을 골목축제"
            name = re.sub(r"서\s*\d{1,2}일\s*", " ", name)
            name = re.sub(r"\s+", " ", name).strip()
            if len(name) < 4 or name in ("축제", "골목축제", "마을축제", "가을밤 축제"):
                # try rebuild from known patterns
                if "덕천" in title and ("젊음" in title or "페스타" in title):
                    name = "2026 덕천 젊음의거리 페스타"
                elif "감천" in title and "골목" in title:
                    name = "감천문화마을 골목축제"
                elif "어방골" in title:
                    name = "어방골 별별 한마당"
                elif "꿈꾸는 마을" in title:
                    name = "해운대 꿈꾸는 마을축제"
                elif "하리단" in title and "별빛" in title:
                    name = "하리단 별빛 축제"
                else:
                    continue
            if "덕천" in title and ("젊음" in title or "페스타" in title):
                name = "2026 덕천 젊음의거리 페스타"
            elif "감천" in title and "골목" in title:
                name = "감천문화마을 골목축제"
            elif "어방골" in title:
                name = "제7회 어방골 별별 한마당"
            elif "꿈꾸는 마을" in title:
                name = "해운대 꿈꾸는 마을축제"
            elif "하리단" in title and "별빛" in title:
                name = "하리단 별빛 축제"
            # 이틀간 / 3일간 after single day
            if s0 == e0:
                dm = re.search(r"(\d{1,2})\s*일(?:부터)?\s*(\d)\s*일간", title)
                if dm:
                    import datetime as _dt
                    try:
                        a = _dt.date.fromisoformat(s0)
                        e0 = (a + _dt.timedelta(days=int(dm.group(2)) - 1)).isoformat()
                    except Exception:
                        pass
                elif re.search(r"이틀간|2일간", title):
                    import datetime as _dt
                    try:
                        a = _dt.date.fromisoformat(s0)
                        e0 = (a + _dt.timedelta(days=1)).isoformat()
                    except Exception:
                        pass
            key = U.norm(name) + s0
            if key in seen:
                continue
            seen.add(key)
            gu = _gu_from_text(text)
            place = ""
            pm = re.search(
                r"([가-힣A-Za-z0-9]+(?:동|거리|길|시장|수목원|공원|광장|센터)(?:\s*일원|\s*일대)?)",
                text,
            )
            if pm:
                place = pm.group(1)
            eid = "local-" + hashlib.md5((U.norm(name) + s0).encode()).hexdigest()[:10]
            out.append({
                "id": eid, "n": name, "s": s0, "e": e0, "gu": gu, "type": "동네축제",
                "p": place or gu, "addr": "", "hours": "", "fee": "무료(기사 기준, 변동 가능)",
                "org": "", "tel": "", "u": link, "src": src, "srcu": link,
                "chk": U.TODAY, "st": "confirmed", "origin": "local_news",
                "x": title[:120],
            })
        time.sleep(0.35)
    U.log(f"[local] 동네축제 후보 {len(out)}건")
    return out
