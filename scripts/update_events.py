#!/usr/bin/env python3
"""부산 행사 자동 업데이트 스크립트 (표준 라이브러리만 사용).

- Visit Busan(visitbusan.net) 축제·행사 목록을 이번 달~내년 12월까지 다시 읽어 옵니다.
- data/events_manual.json(직접 확인한 항목·2027 예상 시기)은 그대로 유지합니다.
- 끝난 행사는 events.json에서 빠집니다.
- 수집이 실패하거나 결과가 비정상적으로 적으면 이전 Visit Busan 데이터를 유지합니다(데이터를 지우지 않음).
- 내용이 바뀐 경우에만 events.json을 다시 씁니다.
"""
import json, re, ssl, sys, html, time, datetime, urllib.request, urllib.parse, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "events.json")
MANUAL = os.path.join(ROOT, "data", "events_manual.json")
KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = datetime.datetime.now(KST)
TODAY = NOW.date().isoformat()
VB = "https://www.visitbusan.net"
LIST = VB + "/schedule/list.do?boardId=BBS_0000009&menuCd=DOM_000000204012000000&month={m}&year={y}&startPage={p}"
VIEW = VB + "/schedule/view.do?boardId=BBS_0000009&menuCd=DOM_000000204012000000&dataSid={sid}"
CTX = ssl.create_default_context()
CTX_NOVERIFY = ssl._create_unverified_context()  # visitbusan.net 인증서 체인 누락 대응

GUS = ["부산진구", "해운대구", "영도구", "동래구", "사하구", "금정구", "강서구", "연제구", "수영구", "사상구", "기장군", "중구", "서구", "동구", "남구", "북구"]
VENUE_GU = [
    ("벡스코|BEXCO|영화의전당|센텀|해운대|송정|달맞이|청사포|APEC|누리마루|동백섬|마린시티|구남로", "해운대구"),
    ("광안리|민락|수영|광안대교|밀락", "수영구"),
    ("시민공원|서면|전포|부산진|범내골|양정|어린이대공원|초읍", "부산진구"),
    ("문화회관|UN|유엔|이기대|오륙도|용호|대연|경성대|부경대|못골|남구", "남구"),
    ("사직|동래|온천장|금강공원|명륜|복천", "동래구"),
    ("삼락|사상|덕포|괘법", "사상구"),
    ("화명|구포|덕천|만덕|금곡|북구", "북구"),
    ("다대포|감천|을숙도|하단|장림|괴정|사하", "사하구"),
    ("송도|암남|구덕|충무동|서구", "서구"),
    ("자갈치|남포|광복|BIFF|용두산|국제시장|보수동|중앙동|부평", "중구"),
    ("부산역|초량|차이나타운|이바구|좌천|수정동|범일|드림씨어터|동구", "동구"),
    ("영도|태종대|흰여울|봉래|아미르", "영도구"),
    ("금정|범어사|부산대|장전|구서|노포|금정산성", "금정구"),
    ("대저|가덕|명지|강서|녹산|맥도|강서체육공원", "강서구"),
    ("연산|연제|거제동|토곡|월드컵빌리지|아시아드", "연제구"),
    ("기장|오시리아|일광|정관|장안|임랑|죽성|롯데월드|아난티", "기장군"),
]
TYPE_RULES = [
    ("스포츠", r"마라톤|대회|리그|경기|레이스|서핑|요트|철인|그란폰도|선수권|야구|축구|농구|배구|골프|e스포츠|런\b|런닝|러닝"),
    ("마켓", r"마켓|장터|야시장|플리|바자|직거래|팝업"),
    ("축제", r"축제|페스티벌|페스타|영화제|불꽃|문화제|Festival"),
    ("전시", r"전시|박람회|엑스포|비엔날레|아트페어|페어|모터쇼|지스타|G-STAR|쇼케이스|특별전|기획전|아트"),
    ("공연", r"공연|콘서트|음악회|뮤지컬|연극|오페라|발레|버스킹|재즈|오케스트라|국악|무용|리사이틀"),
    ("체험·프로그램", r"체험|투어|클래스|프로그램|캠프|교실|원데이|강좌|걷기|트레킹|해설"),
]


DEADLINE = {}
SOURCE_BUDGET = 9 * 60  # 소스별 최대 9분 → 넘으면 해당 소스는 이전 데이터 유지


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fetch(url, tries=2, verify=True, timeout=20):
    last = None
    dl = DEADLINE.get("t")
    if dl and time.time() > dl:
        raise TimeoutError("source time budget exceeded")
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (busan-guide events bot; +https://github.com/dlfmzlspdh764-svg/busan-guide)"})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX if verify else CTX_NOVERIFY) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise last


def lines_of(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>|</p>|</li>|</div>|</dd>|</dt>|</span>|</strong>|</a>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return [re.sub(r"\s+", " ", x).strip() for x in s.split("\n") if x.strip()]


def guess_gu(*texts):
    t = " ".join(x for x in texts if x)
    m = re.search(r"부산(?:광역시|시)?\s*(" + "|".join(GUS) + ")", t)
    if m:
        return m.group(1)
    for g in GUS:
        if re.search(r"(^|\s)" + g + r"(\s|$|\)|,)", t):
            return g
    best = None
    for pat, g in VENUE_GU:
        m = re.search(pat, t)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), g)
    return best[1] if best else "부산 전역"


def guess_type(name, body=""):
    if re.search(r"공연예술|뮤직쇼|드론라이트쇼|드론×레이저쇼", name):
        return "공연"
    if re.search(r"필름마켓|콘텐츠.?마켓", name):
        return "전시"
    for t, pat in TYPE_RULES:
        if re.search(pat, name, re.I):
            return t
    for t, pat in TYPE_RULES:
        if re.search(pat, body[:600], re.I):
            return t
    return "축제"


def pdate(s):
    m = re.search(r"(20\d\d)[.\-]\s*(\d{1,2})[.\-]\s*(\d{1,2})", s or "")
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def kv_after(L, label, stop=8):
    """구조화된 하단 표: '주최' 다음 줄 값."""
    for i, x in enumerate(L):
        if x == label and i + 1 < len(L):
            v = L[i + 1]
            if v in ("일자", "주최", "주관", "문의처", "장소", "주소", "홈페이지", "첨부파일 다운로드", "찾아오시는 길"):
                return ""
            return v
    return ""


def bullet(L, keys):
    """본문의 '○ 요금 : 값' / '- 일 시 : 값' 형태. keys: 공백 없는 라벨 목록."""
    for i, x in enumerate(L[:400]):
        m = re.match(r"^[○●■□▶\-\*·•※◎◆▪]?\s*([가-힣 /·]{1,12}?)\s*[:：]\s*(.*)$", x)
        if not m:
            continue
        k = re.sub(r"[\s/·]", "", m.group(1))
        if k not in keys:
            continue
        v = m.group(2).strip()
        j = i + 1
        while len(v) < 2 and j < len(L) and j < i + 3:
            v = (v + " " + L[j]).strip(); j += 1
        return v[:160]
    return ""


def parse_view(sid):
    s = fetch(VIEW.format(sid=sid), verify=False)
    L = lines_of(s)
    try:
        start = L.index("기간") - 1
    except ValueError:
        start = 0
    name = L[start] if start > 0 else ""
    name = re.split(r"[｜|]", name)[0].strip()
    # 기간: '일자' 다음 두 줄
    ds = de = None
    for i, x in enumerate(L):
        if x == "일자":
            seg = " ".join(L[i + 1:i + 3])
            ds_all = re.findall(r"20\d\d\.\s*\d{1,2}\.\s*\d{1,2}", seg)
            if ds_all:
                ds = pdate(ds_all[0]); de = pdate(ds_all[-1])
            break
    if not ds:
        for i, x in enumerate(L):
            if x == "기간":
                seg = " ".join(L[i + 1:i + 3])
                ds_all = re.findall(r"20\d\d\.\s*\d{1,2}\.\s*\d{1,2}", seg)
                if ds_all:
                    ds = pdate(ds_all[0]); de = pdate(ds_all[-1])
                break
    org = kv_after(L, "주최") or bullet(L, {"주최", "주최주관"})
    org2 = kv_after(L, "주관")
    tel = kv_after(L, "문의처")
    place = kv_after(L, "장소") or bullet(L, {"장소", "장 소"})
    addr = kv_after(L, "주소")
    hp = ""
    m = re.search(r"홈페이지</[^>]+>\s*<[^>]+>\s*<a[^>]+href=\"(https?://[^\"]+)\"", s)
    if m:
        hp = m.group(1)
    if not hp:
        v = bullet(L, {"홈페이지", "공식홈페이지", "누리집"})
        m = re.search(r"https?://\S+", v)
        if m:
            hp = m.group(0).rstrip(")")
    ig = ""
    for x in L[:400]:
        m = re.search(r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9_.]+", x)
        if m:
            ig = m.group(0); break
    body = " ".join(L[start:start + 120])
    fee = bullet(L, {"요금", "참가비", "관람료", "입장료", "이용료", "참여비", "참가비용", "관람요금", "티켓", "비용", "입장", "관람"})
    if not fee and re.search(r"무료\s*(관람|입장|참여|행사)|관람료\s*무료|입장료\s*무료|참가비\s*무료", body):
        fee = "무료"
    hours = bullet(L, {"시간", "운영시간", "행사시간", "관람시간", "공연시간", "일시", "운영"})
    if hours and not re.search(r"\d{1,2}\s*:\s*\d\d|\d{1,2}\s*시", hours):
        hours = ""
    if hours and re.fullmatch(r"\d+", hours):
        hours = ""
    return {
        "id": "vb" + str(sid), "n": name, "s": ds, "e": de or ds,
        "gu": guess_gu(addr, place, name), "type": guess_type(name, body),
        "p": place, "addr": addr, "hours": hours, "fee": fee,
        "org": " · ".join(x for x in dict.fromkeys([org, org2]) if x), "tel": tel,
        "u": hp, "ig": ig, "srcu": VIEW.format(sid=sid), "src": "Visit Busan",
        "chk": TODAY, "st": "confirmed" if ds else "check", "origin": "visitbusan",
    }


def scrape_visitbusan():
    sids, errors, months = [], 0, 0
    y, m = NOW.year, NOW.month
    end = (NOW.year + 1, 12)
    while (y, m) <= end:
        p = 1
        while p <= 6:
            try:
                s = fetch(LIST.format(m=m, y=y, p=p), verify=False)
            except Exception as e:  # noqa
                errors += 1; print("list fail", y, m, p, e, file=sys.stderr); break
            found = re.findall(r"dataSid=(\d+)\"\s*title", s)
            for x in found:
                if x not in sids:
                    sids.append(x)
            if f"fn_go_page({p + 1})" not in s:
                break
            p += 1
        months += 1
        m += 1
        if m == 13:
            y, m = y + 1, 1
    out = []
    for sid in sids:
        try:
            ev = parse_view(sid)
            if ev["n"]:
                out.append(ev)
        except Exception as e:  # noqa
            errors += 1; print("view fail", sid, e, file=sys.stderr)
        time.sleep(0.3)
    return out, errors, months


BX = "https://www.bexco.co.kr"
BX_LIST = BX + "/kor/CMS/EventScheduleMgr/list.do?mCode=MN214&page={p}"
BX_VIEW = BX + "/kor/CMS/EventScheduleMgr/view.do?mCode=MN214&event_seq={seq}"


def scrape_bexco():
    """벡스코 행사일정(전시·공연·이벤트). 회의·세미나는 제외."""
    rows, errors = [], 0
    limit = f"{NOW.year + 1}-12-31"
    for p in range(1, 21):
        try:
            s = fetch(BX_LIST.format(p=p))
        except Exception as e:  # noqa
            errors += 1; print("bexco list fail", p, e, file=sys.stderr); break
        page_rows = []
        for chunk in re.split(r'EventScheduleMgr/view\.do\?[^"]*?event_seq=', s)[1:]:
            seq = re.match(r"(\d+)", chunk).group(1)
            chunk = chunk.split("</li>")[0]
            g = lambda c: (lambda m: html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()) if m else "")(re.search(r'<span class="' + c + r'"[^>]*>(.*?)</span>', chunk, re.S))
            dates = re.findall(r"20\d\d-\d\d-\d\d", g("date"))
            if not dates:
                continue
            cat = (lambda m: m.group(1) if m else "")(re.search(r'<span class="eventIcon[^"]*">([^<]*)</span>', chunk))
            page_rows.append({"seq": seq, "cat": cat.strip(), "n": g("subject"), "s": dates[0], "e": dates[-1], "hall": g("place")})
        if not page_rows:
            break
        rows += page_rows
        if page_rows and min(r["s"] for r in page_rows) > limit:
            break
        if f"page={p + 1}" not in s:
            break
    out = []
    for r in rows:
        if r["cat"] in ("회의", "기타") or r["e"] < TODAY or r["s"] > limit:
            continue
        if re.search(r"채용|설명회|세미나|컨퍼런스|콘퍼런스|포럼|총회|심포지엄|학술|시험|워크숍|교육|입학|환송|기념식|발대식|입주|수주회|면접|증진대회|데이터위크|창업박람회|위크$", r["n"]):
            continue
        ev = {"id": "bx" + r["seq"], "n": r["n"], "s": r["s"], "e": r["e"], "gu": "해운대구",
              "type": "전시" if r["cat"] == "전시" else guess_type(r["n"]),
              "p": "벡스코 " + r["hall"], "addr": "부산 해운대구 APEC로 55 (벡스코)", "hours": "", "fee": "", "org": "", "tel": "",
              "u": "", "srcu": BX_VIEW.format(seq=r["seq"]), "src": "벡스코 행사일정",
              "chk": TODAY, "st": "confirmed", "origin": "bexco"}
        try:
            L = lines_of(fetch(BX_VIEW.format(seq=r["seq"])))
            try:
                i = L.index(r["s"].replace("-", "."))
                after = L[i + 3:i + 5]
                if after and not re.search(r"홀|룸|회의실|오디토리움|광장|전시장", after[0]):
                    ev["hours"] = after[0][:120]
            except ValueError:
                pass
            for lab, key in (("주최/주관", "org"), ("관람료", "fee"), ("홈페이지", "u")):
                if lab in L:
                    v = L[L.index(lab) + 1]
                    if key == "u":
                        if v.startswith("http"):
                            ev["u"] = v
                    elif v not in ("전화", "홈페이지", "관람료"):
                        ev[key] = v[:160]
            time.sleep(0.3)
        except Exception as e:  # noqa
            errors += 1
        if re.fullmatch(r"\d{1,2}(시|:\d\d)", ev["hours"] or ""):
            ev["hours"] = ev["hours"] + " 시작"
        if r["cat"] != "전시" and ev["type"] == "축제" and "축제" not in ev["n"] and "페스티벌" not in ev["n"]:
            ev["type"] = "공연" if re.search(r"석\s*[\d,]+원|콘서트|공연|음악회", (ev["fee"] or "") + ev["n"]) else "체험·프로그램"
        out.append(ev)
    return out, errors


KF_LIST = "https://korean.visitkorea.or.kr/kfes/list/selectWntyFstvlList.do"
KF_VIEW = "https://korean.visitkorea.or.kr/kfes/detail/fstvlDetail.do?fstvlCntntsId={id}"


def scrape_kfes():
    """한국관광공사 '대한민국 구석구석 축제' 부산 목록(월별). 지난 회차는 다음 개최 예상의 근거(series)로만 사용."""
    allr, errors = {}, 0
    for m in ["%02d" % i for i in range(1, 13)]:
        idx = 0
        for _ in range(10):
            data = urllib.parse.urlencode(dict(startIdx=idx, searchType="A", searchDate=m, searchArea="6", searchCate="",
                                               locationx="undefined", locationy="undefined", filterExcluded="true")).encode()
            if DEADLINE.get("t") and time.time() > DEADLINE["t"]:
                raise TimeoutError("source time budget exceeded")
            try:
                req = urllib.request.Request(KF_LIST, data=data, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://korean.visitkorea.or.kr/kfes/list/wntyFstvlList.do"})
                d = json.loads(urllib.request.urlopen(req, timeout=20, context=CTX).read().decode("utf-8"))
            except Exception as e:  # noqa
                errors += 1; print("kfes fail", m, e, file=sys.stderr); break
            r = d.get("resultList") or []
            for x in r:
                allr[x["fstvlCntntsId"]] = x
            idx += len(r)
            if not r or idx >= int(d.get("totalCnt") or 0):
                break
    evs, series = [], []
    for x in allr.values():
        if "부산" not in (x.get("adres") or "") and "부산" not in (x.get("areaNm") or ""):
            continue
        s_, e_ = pdate(x.get("fstvlBgngDe")), pdate(x.get("fstvlEndDe"))
        if not s_:
            continue
        hp = (lambda m: m.group(1) if m else "")(re.search(r'href="([^"]+)"', x.get("fstvlHmpgUrl") or "")) or (x.get("fstvlHmpgUrl") or "").strip()
        if hp and not hp.startswith("http"):
            hp = ""
        fee = re.sub(r"<[^>]+>", " ", html.unescape(x.get("fstvlUtztFareInfo") or "")).strip()
        fee = re.sub(r"\s+", " ", fee)[:160]
        org = " · ".join(v for v in dict.fromkeys([(x.get("fstvlAspcsNm") or "").strip(), (x.get("fstvlMngtNm") or "").strip()]) if v)
        ev = {"id": "kf" + x["fstvlCntntsId"][:8], "n": x["cntntsNm"].strip(), "s": s_, "e": e_ or s_,
              "gu": guess_gu(x.get("adres"), x["cntntsNm"]), "type": guess_type(x["cntntsNm"]),
              "p": (x.get("dtadr") or "").strip(), "addr": (x.get("adres") or "").strip(), "hours": "", "fee": fee, "org": org,
              "tel": (x.get("fstvlAspcsTelno") or "").strip(), "u": hp,
              "ig": (x.get("instaUrl") or "").strip(), "srcu": KF_VIEW.format(id=x["fstvlCntntsId"]),
              "src": "한국관광공사 대한민국 구석구석 축제", "chk": TODAY, "st": "confirmed", "origin": "kfes"}
        if ev["type"] not in ("마켓", "스포츠", "공연", "전시", "체험·프로그램"):
            ev["type"] = "축제"
        series.append(dict(ev))  # 매년 열리는 지역축제 → 다음 회차 예상 근거
        if (ev["e"] or "") >= TODAY:
            evs.append(ev)
    return evs, series, errors


def make_expected(series_list, events):
    """지난 회차 날짜를 근거로 '예상 시기(일정 미발표)' 항목 생성. 정확한 날짜는 만들지 않음."""
    out, seen = [], set()
    last_year = NOW.year + 1
    for sr in series_list:
        key = norm(sr.get("series") or sr["n"])
        if not key or key in seen:
            continue
        s0 = sr.get("last_s") or sr.get("s")
        e0 = sr.get("last_e") or sr.get("e") or s0
        if not s0:
            continue
        base_y = int(s0[:4])
        mon = int(s0[5:7])
        every = int(sr.get("every", 1))
        for y in range(base_y + every, last_year + 1, every):
            if (y, mon) < (NOW.year, NOW.month):
                continue
            # 해당 연도 확정 일정이 이미 있으면 건너뜀
            if any(key in norm(e["n"]) or norm(e["n"]) in key
                   for e in events if e.get("st") != "expected" and (e.get("s") or "")[:4] == str(y)):
                continue
            span = (int(e0[:4]) - base_y) * 12 + int(e0[5:7]) - mon
            em_y, em_m = divmod((y * 12 + mon - 1) + max(span, 0), 12)
            when = f"{y}년 {mon}월" + (f"~{em_y if em_y != y else ''}{'년 ' if em_y != y else ''}{em_m + 1}월" if span > 0 else "")
            out.append({
                "id": "ex" + str(y) + "-" + key[:24], "n": re.sub(r"^\s*(20\d\d년?\s*)?(제\s*\d+\s*회\s*)?", "", sr.get("series") or sr["n"]).strip(),
                "s": f"{y}-{mon:02d}", "e": f"{em_y}-{em_m + 1:02d}", "gu": sr.get("gu", "부산 전역"), "type": sr.get("type", "축제"),
                "p": sr.get("p", ""), "addr": sr.get("addr", ""), "fee": ("(지난 회차 기준) " + sr["fee"]) if sr.get("fee") else "", "org": sr.get("org", ""),
                "u": sr.get("u", ""), "srcu": sr.get("srcu", ""), "src": sr.get("src", ""), "chk": TODAY,
                "st": "expected", "origin": "expected",
                "exp": f"{when}경 예상 (일정 미발표)",
                "basis": sr.get("basis") or f"최근 개최: {s0.replace('-', '.')}~{e0.replace('-', '.')}" + (" · 격년 개최" if every == 2 else ""),
            })
        seen.add(key)
    return out


def norm(s):
    s = re.sub(r"20\d\d|제\s*\d+\s*회|\(.*?\)|\[.*?\]", "", s or "")
    return re.sub(r"[^가-힣A-Za-z0-9]", "", s).lower()


def _date(x):
    try:
        return datetime.date.fromisoformat(x[:10]) if x and len(x) >= 10 else None
    except ValueError:
        return None


def same(a, b):
    na, nb = norm(a["n"]), norm(b["n"])
    if not na or not nb:
        return False
    if not (na in nb or nb in na or (len(na) >= 6 and na[:6] == nb[:6])):
        return False
    da, db = _date(a.get("s")), _date(b.get("s"))
    if da and db:
        return abs((da - db).days) < 45
    return False


def merge_into(base, extra):
    for k, v in extra.items():
        if v and not base.get(k):
            base[k] = v
    srcs = base.setdefault("srcs", [])
    for x in ([{"src": extra.get("src"), "u": extra.get("srcu")}] if extra.get("srcu") else []):
        if x["u"] != base.get("srcu") and x not in srcs:
            srcs.append(x)


def is_current(e):
    end = e.get("e") or e.get("s") or "9999"
    return end >= (TODAY[:7] if len(end) == 7 else TODAY)


PROBE = {"visitbusan": (VB + "/index.do", False), "kfes": ("https://korean.visitkorea.or.kr/kfes/list/wntyFstvlList.do", True),
         "bexco": (BX + "/kor/Main.do", True)}


def run_source(name, fn, prev_events, status, min_ratio=0.5, min_abs=3):
    prev_src = [e for e in prev_events if e.get("origin") == name]
    t0 = time.time()
    try:
        url, verify = PROBE[name]
        fetch(url, tries=1, verify=verify, timeout=15)  # 접속 불가면 바로 실패 처리
        DEADLINE["t"] = time.time() + SOURCE_BUDGET
        log(f"[{name}] 수집 시작")
        res = fn()
        DEADLINE.pop("t", None)
        log(f"[{name}] {len(res[0])}건 ({time.time() - t0:.0f}s)")
        items, extra = res[0], res[1:]
        errs = extra[-1] if extra else 0
        status[name] = {"ok": True, "count": len(items), "errors": errs}
        floor = max(min_abs, int(len([e for e in prev_src if is_current(e)]) * min_ratio))
        if time.time() - t0 > SOURCE_BUDGET or (isinstance(errs, int) and errs > max(3, len(items) * 0.2)):
            log(f"{name}: 시간 초과 또는 오류 {errs}건 → 이전 데이터 유지")
            status[name]["ok"] = False
            status[name]["kept_previous"] = True
            return prev_src, (extra if name != "kfes" else ())
        if len(items) < floor:
            print(f"{name}: 결과 {len(items)}건 < 기준 {floor} → 이전 데이터 유지", file=sys.stderr)
            status[name]["ok"] = False
            status[name]["kept_previous"] = True
            return prev_src, extra
        return items, extra
    except Exception as e:  # noqa
        DEADLINE.pop("t", None)
        log(f"{name}: 수집 실패 → 이전 데이터 유지: {e!r} ({time.time() - t0:.0f}s)")
        status[name] = {"ok": False, "error": str(e)[:200], "kept_previous": True}
        return prev_src, ()


def main():
    try:
        prev = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        prev = {"events": []}
    manual = json.load(open(MANUAL, encoding="utf-8"))  # 없거나 깨지면 예외 → 기존 파일 그대로
    prev_events = prev.get("events", [])
    status = {}

    vb, _ = run_source("visitbusan", lambda: scrape_visitbusan()[:2], prev_events, status, min_abs=5)
    kf, kx = run_source("kfes", scrape_kfes, prev_events, status, min_abs=3)
    kf_series = kx[0] if len(kx) >= 2 else prev.get("kfes_series", [])
    bx, _ = run_source("bexco", scrape_bexco, prev_events, status, min_abs=3)

    events = []
    for m in manual["events"]:
        events.append(dict(m))
    for group in (vb, kf, bx):
        for v in group:
            hit = next((e for e in events if same(e, v)), None)
            if hit:
                merge_into(hit, v)
            else:
                events.append(dict(v))

    series = list(manual.get("series", []))
    keys = {norm(x.get("series") or x["n"]) for x in series}
    for x in sorted(kf_series, key=lambda x: x.get("s") or "", reverse=True):
        k = norm(x["n"])
        if k and k not in keys:
            keys.add(k)
            series.append(x)
    events += make_expected(series, events)

    events = [e for e in events if is_current(e)]
    for e in events:
        if (e.get("s") or "") and len(e["s"]) == 10 and e.get("st") == "confirmed" and e["s"] > f"{NOW.year + 1}-12-31":
            e["st"] = "check"
    events.sort(key=lambda e: ((e.get("s") or "9999") + ("-99" if len(e.get("s") or "") == 7 else ""), e["n"]))

    data = {"updated": NOW.strftime("%Y-%m-%d %H:%M"), "tz": "KST", "status": status,
            "sources": {"visitbusan": "https://www.visitbusan.net/schedule/list.do?boardId=BBS_0000009&menuCd=DOM_000000204012000000",
                        "kfes": "https://korean.visitkorea.or.kr/kfes/list/wntyFstvlList.do",
                        "bexco": "https://www.bexco.co.kr/kor/CMS/EventScheduleMgr/list.do?mCode=MN214"},
            "kfes_series": kf_series, "events": events}
    if prev.get("events") == events and prev.get("kfes_series") == kf_series:
        print("변경 없음 (events.json 유지)", len(events), status)
        return 0
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    json.load(open(tmp, encoding="utf-8"))  # 검증
    os.replace(tmp, OUT)
    print("events.json 업데이트:", len(events), "건", status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
