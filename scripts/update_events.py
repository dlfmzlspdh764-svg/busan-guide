#!/usr/bin/env python3
"""부산 행사 자동 업데이트 스크립트 (표준 라이브러리만 사용).

- Visit Busan(visitbusan.net) 축제·행사 목록을 이번 달~내년 12월까지 다시 읽어 옵니다.
- data/events_manual.json(직접 확인한 항목·2027 예상 시기)은 그대로 유지합니다.
- 끝난 행사는 events.json에서 빠집니다.
- 수집이 실패하거나 결과가 비정상적으로 적으면 이전 Visit Busan 데이터를 유지합니다(데이터를 지우지 않음).
- 내용이 바뀐 경우에만 events.json을 다시 씁니다.
"""
import json, re, ssl, sys, html, time, datetime, urllib.request, urllib.parse, urllib.error, os

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
         "bexco": (BX + "/kor/Main.do", True), "concert": ("https://tickets.interpark.com/", True)}


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



# ───────────────────────── 가수 공연(콘서트) 수집 ─────────────────────────
# 예스24 티켓 콘서트 목록(전 지역, 페이지당 20건) + NOL(인터파크) 콘서트 페이지에서 부산 공연만 골라 type='콘서트'로 넣습니다.
# KOPIS 오픈API는 인증키가 필요하고, 멜론티켓은 봇 접속을 막아(423) 제외했어요.
CONCERT_END = "2026-12-31"
BUSAN_VENUE = (r"부산|벡스코|BEXCO|KBS\s*부산|소향\s*씨어터|드림\s*씨어터|시민회관|사직|영화의전당|해운대|광안|센텀|을숙도|"
               r"부경대|경성대|동아대|부산대|기장군|기장읍|금정문화|동래문화|BNK|롯데\s*콘서트홀\s*부산|부산콘서트홀|오디토리움\s*부산")
OTHER_CITY = r"^\s*[\[［]\s*(서울|대구|대전|광주|인천|울산|창원|수원|성남|고양|여수|전주|청주|천안|포항|진주|제주|강릉|원주|춘천|김해|구미|안동|익산|목포|순천)"


CONCERT_GU = [(r"KBS\s*부산", "수영구"), (r"부경대|경성대", "남구"), (r"소향|벡스코|BEXCO|영화의전당|센텀|해운대", "해운대구"),
              (r"가톨릭센터|광복|남포", "중구"), (r"시민회관", "동구"), (r"드림\s*씨어터|문현", "남구"), (r"사직", "동래구"), (r"을숙도", "사하구")]


def fetch_h(url, headers, timeout=25, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36", **headers})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa
            last = e; time.sleep(2 * (i + 1))
    raise last


def concert_artist(title):
    t = re.sub(r"[\[［(（][^\]］)）]*[\]］)）]", " ", title)
    t = re.sub(r"[〈<《「『＂\"‘'].*", " ", t)
    t = re.sub(r"^\s*(20\d\d(?:\s*-\s*\d\d)?)\s*", "", t.strip())
    parts = re.split(r"\s*(?:전국\s*투어|단독\s*콘서트|콘서트|CONCERT|Concert|LIVE|Live|TOUR|Tour|WORLD|투어|팬미팅|FAN\s*MEETING|내한공연|단독공연|토크\s*콘서트|-|:|in\s)", t, 1)
    if len(parts) < 2:
        return ""
    m = re.sub(r"\s*(라이브|\d+\s*주년|단독|뮤직|토크)$", "", parts[0].strip(" -:,")).strip()
    if not m or len(m) > 20 or re.search(r"\d+(th|회)", m) or re.search(r"페스티벌|축제|가요제|뮤직|어워드|AWARD|FESTIVAL|대학|합창|오케스트라", m, re.I):
        return ""
    return m


def concert_event(eid, title, s, e, venue, url, src, srcu, extra=None):
    title = re.sub(r"\s+", " ", html.unescape(title)).strip()
    venue = re.sub(r"\s+", " ", html.unescape(venue or "")).strip()
    art = concert_artist(title)
    ev = {"id": eid, "n": title, "s": s, "e": e or s, "gu": next((g for pat, g in CONCERT_GU if re.search(pat, venue)), None) or guess_gu(venue, title), "type": "콘서트", "p": venue, "addr": "", "hours": "", "fee": "",
          "org": "", "tel": "", "u": url, "srcu": srcu, "src": src, "chk": TODAY, "st": "confirmed", "origin": "concert",
          "lineup": ([{"name": art, "role": "출연", "src": src, "srcu": url, "chk": TODAY}] if art else [])}
    ev.update(extra or {})
    return ev


def scrape_concerts():
    out, errs, ok = {}, 0, 0
    # 1) 예스24 티켓 (genre 15456 = 콘서트 전체)
    base = "https://ticket.yes24.com/New/Genre/Ajax/GenreList_Data.aspx?genre=15456&sort=1&area=&genretype=1&pPageSize=20&pCurPage="
    seen, total = set(), 999
    for pg in range(1, 13):
        if (pg - 1) * 20 >= total:
            break
        try:
            page = fetch_h(base + str(pg), {"Referer": "https://ticket.yes24.com/New/Genre/GenreList.aspx?genretype=1&genre=15456", "X-Requested-With": "XMLHttpRequest"})
            ok += 1
        except Exception as e:  # noqa
            errs += 1; log(f"  [concert] yes24 p{pg} 실패: {e!r}"); continue
        m = re.search(r'id="ListTotalCnt" value="(\d+)"', page)
        if m:
            total = int(m.group(1))
        for b in re.split(r"(?=<a style='cursor:pointer;' onclick='jsf_base_GoToPerfDetail)", page):
            m = re.search(r"GoToPerfDetail\((\d+)\);' title='([^']*)'", b)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            ps = [html.unescape(x).strip() for x in re.findall(r"<p class='list-b-tit2[^']*'>([^<]*)</p>", b)]
            dates = re.findall(r"(20\d\d)\.(\d\d)\.(\d\d)", ps[0] if ps else "")
            title = html.unescape(m.group(2)); venue = ps[1] if len(ps) > 1 else ""
            if not dates or re.search(OTHER_CITY, title) or not re.search(BUSAN_VENUE, title + " " + venue):
                continue
            s_, e_ = "-".join(dates[0]), "-".join(dates[-1])
            u = f"https://ticket.yes24.com/Perf/{m.group(1)}"
            out["y" + m.group(1)] = concert_event("cc-y" + m.group(1), title, s_, e_, venue, u, "예스24 티켓", u)
    # 2) NOL(인터파크) 티켓 콘서트 장르 페이지
    try:
        page = fetch_h("https://tickets.interpark.com/contents/genre/concert", {})
        ok += 1
        for m in re.finditer(r'<a [^>]*?href="(https://nol\.yanolja\.com/ticket/[^"]*?products/(\d+))"[^>]*?aria-label="([^"]*)"', page):
            lab = html.unescape(m.group(3))
            mm = re.search(r"^(.*?), (?:단독판매, |좌석우위, |\d+위, )*공연장: (.*?), 공연 기간: (\d\d)\.(\d\d)\.(\d\d)\s*[-~]\s*(\d\d)\.(\d\d)\.(\d\d)", lab)
            if not mm:
                continue
            title, venue = re.sub(r"^(단독판매, )", "", mm.group(1)), mm.group(2)
            if "," in venue or re.search(OTHER_CITY, title) or not re.search(BUSAN_VENUE, venue + " " + title) or "서울" in venue:
                continue
            s_ = f"20{mm.group(3)}-{mm.group(4)}-{mm.group(5)}"; e_ = f"20{mm.group(6)}-{mm.group(7)}-{mm.group(8)}"
            if any(same({"n": title, "s": s_}, v) for v in out.values()):
                continue
            out.setdefault("i" + m.group(2), concert_event("cc-i" + m.group(2), title, s_, e_, venue, m.group(1), "NOL 티켓(인터파크)", m.group(1)))
    except Exception as e:  # noqa
        errs += 1; log(f"  [concert] interpark 실패: {e!r}")
    items = [v for v in out.values() if v["e"] >= TODAY and v["s"] <= CONCERT_END]
    if not ok:
        raise ConnectionError("콘서트 소스 모두 접속 실패")
    return items, 0


# ───────────────────────── 구·군청 홈페이지 행사 수집 ─────────────────────────
# 각 구·군청(및 구립 문화회관) 게시판 1페이지를 읽어 행사성 글만 골라 상세 본문에서
# 날짜·장소·출연진을 추출합니다. 소스별로 실패하면 그 소스의 이전 데이터를 유지합니다.
GU_SOURCES = [
    # (id, 구·군, 게시판 이름, 목록 URL, 종류)
    ("junggu", "중구", "중구청 공지사항", "https://www.bsjunggu.go.kr/index.junggu?menuCd=DOM_000000103001001000", "board"),
    ("seogu", "서구", "서구청 알림사항", "https://www.bsseogu.go.kr/board/list.bsseogu?boardId=BBS_0000039&menuCd=DOM_000000103001012000&contentsSid=877", "board"),
    ("donggu", "동구", "동구청 행사/교육", "https://www.bsdonggu.go.kr/index.donggu?menuCd=DOM_000000103001007000", "board"),
    ("yeongdo", "영도구", "영도구청 행사/교육", "https://www.yeongdo.go.kr/00000/00007/02409.web", "board"),
    ("yeongdo_art", "영도구", "영도문화예술회관 공연/전시", "https://www.yeongdo.go.kr/culture/01250/01251.web", "board"),
    ("busanjin", "부산진구", "부산진구청 공지사항", "https://www.busanjin.go.kr/board/list.busanjin?boardId=BBS_0000009&menuCd=DOM_000000110001001000&contentsSid=3", "board"),
    ("dongnae", "동래구", "동래구청 문화행사", "https://www.dongnae.go.kr/board/list.dongnae?boardId=BBS_0000023&menuCd=DOM_000000103003000000&startPage=1", "dongnae"),
    ("namgu", "남구", "남구청 행사/교육", "https://www.bsnamgu.go.kr/board/list.namgu?boardId=BBS_0000002&menuCd=DOM_000000105001003000&contentsSid=138", "board"),
    ("bukgu", "북구", "북구청 새소식", "https://www.bsbukgu.go.kr/board/list.bsbukgu?boardId=BBS_0000023&menuCd=DOM_000000105001001000&contentsSid=368", "board"),
    ("haeundae", "해운대구", "해운대구 연간행사안내", "https://www.haeundae.go.kr/index.do?menuCd=DOM_000000104002004000", "hd_calendar"),
    ("haeundae_art", "해운대구", "해운대문화회관 공지", "https://www.haeundae.go.kr/board/list.do?boardId=BBS_0000110&menuCd=DOM_000000904004000000&paging=ok&startPage=1", "board"),
    ("haeundae_tour", "해운대구", "해운대구 해운대소식", "https://www.haeundae.go.kr/tour/index.do?menuCd=DOM_000000307001000000", "board"),
    ("saha", "사하구", "사하구청 공지사항", "https://www.saha.go.kr/portal/bbs/list.do?ptIdx=22&mId=0301010000", "egov"),
    ("saha_eul", "사하구", "을숙도문화회관 공지", "https://www.saha.go.kr/eulsukdo/bbs/list.do?ptIdx=79&mId=0501000000", "board"),
    ("geumjeong", "금정구", "금정구 축제 게시판", "https://www.geumjeong.go.kr/festival/board/list.geumj?boardId=BBS_0000176&menuCd=DOM_000001103001000000&paging=ok&startPage=1", "board"),
    ("gangseo", "강서구", "강서구청 알림사항", "https://www.bsgangseo.go.kr/portal/board/post/list.do?bcIdx=500&mid=0501010000", "gangseo"),
    ("yeonje", "연제구", "연제구청 행사/교육", "https://www.yeonje.go.kr/portal/bbs/list.do?ptIdx=11&mId=0206020000", "egov"),
    ("yeonje_tour", "연제구", "연제구 문화행사", "https://www.yeonje.go.kr/tour/bbs/list.do?ptIdx=135&mId=0701000000", "egov"),
    ("suyeong", "수영구", "수영구청 행사안내", "https://www.suyeong.go.kr/board/list.suyeong?boardId=BBS_0000287&menuCd=DOM_000000103001011000&contentsSid=2659&categoryCode1=suyeong&type=calendar", "board"),
    ("sasang", "사상구", "사상구 공연/전시/행사", "https://www.sasang.go.kr/tour/board/list.sasang?boardId=BBS_0000006&menuCd=DOM_000000603004000000&contentsSid=746&cpath=%2Ftour", "board"),
    ("gijang", "기장군", "기장군청 알림사항", "https://www.gijang.go.kr/board/list.gijang?boardId=BBS_0000002&menuCd=DOM_000000101001001000&contentsSid=44", "board"),
    ("gijang_news", "기장군", "기장군 주요소식", "https://www.gijang.go.kr/board/list.gijang?boardId=BBS_0000010&menuCd=DOM_000000101001010000&contentsSid=53", "board"),
]
GU_VIEW_MAX = 14       # 소스별 상세 페이지 최대 조회 수
GU_BUDGET = 150        # 소스별 최대 150초
EV_POS = r"축제|페스티벌|페스타|공연|음악회|콘서트|연주회|가요제|전시|展|박람회|마켓|장터|야시장|버스킹|영화|뮤지컬|오페라|발레|연극|국악|문화|행사|큰잔치|잔치|한마당|어울림|대회|투어|캠핑|쇼|불꽃|트레킹|걷기|특강|강연|토크|체험|개최|열려|경연|공모전|오픈|기념식"
EV_STRONG = r"축제|페스티벌|페스타|공연|음악회|콘서트|가요제|버스킹|뮤지컬|오페라|발레|전시|박람회|마켓|야시장"
EV_NEG = (r"공모전|공모|공청회|설명회|간담회|입찰|채용|기간제|공무직|합격|심사결과|결과\s*발표|결과\s*알림|고시|열람|공시|단속|체납|납부|식단|위원회|위원\s*(모집|명단)|회의록|수강생|교육생|"
          r"정보화교육|민방위|예비군|세무|지방세|건축|주차|도로|공사|점용|보조금|지원사업|일자리\s*사업|참여자\s*모집|명단|감사|주민등록|수질|방역|"
          r"예방접종|검진|소독|대관|정기대관|수시대관|회원\s*모집|조례|임시휴관|휴관|운영\s*중단|일시중단|장학생|특별공급|분양|공매|경매|"
          r"교통|노선|선거|투표|통계조사|조사원|부고|공영장례|칼갈이|하수도|폐기물|분리배출|빈대|훈련|캠페인")
LINEUP_LABEL = r"(?:주요\s*)?(?:출\s*연\s*진?|출\s*연\s*자|출연\s*가수|초청\s*가수|초대\s*가수|축하\s*공연|게\s*스\s*트|공연\s*진|라\s*인\s*업|연\s*주|협\s*연|지\s*휘|사\s*회|강\s*사|연\s*사|MC)"


def _abs(base, href):
    return urllib.parse.urljoin(base, html.unescape(href))


def gu_list_rows(src_id, list_url, kind, page):
    """게시판 목록 → [(제목, 상세 URL, 목록에 있는 날짜들)]"""
    rows, seen = [], set()
    if kind == "gangseo":
        for m in re.finditer(r'data-req-get-p-idx="(\d+)"[^>]*>(.*?)</a>', page, re.S):
            t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
            rows.append((t, f"https://www.bsgangseo.go.kr/portal/board/post/view.do?bcIdx=500&mid=0501010000&idx={m.group(1)}", None))
        return rows
    if kind == "dongnae":
        for tr in re.findall(r"<tr>(.*?)</tr>", page, re.S):
            a = re.search(r'href="([^"]*epId=\d+)"[^>]*>(.*?)</a>', tr, re.S)
            ds = re.findall(r">(20\d\d-\d\d-\d\d)<", tr)
            if a and len(ds) >= 1:
                t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", a.group(2)))).strip()
                rows.append((t, _abs(list_url, a.group(1)), (ds[0], ds[-1])))
        return rows
    for m in re.finditer(r"<a([^>]*)>(.*?)</a>", page, re.S):
        attrs, inner = m.group(1), m.group(2)
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", inner))).strip()
        t = re.sub(r"\s*(새\s*글|NEW)\s*$", "", t)
        if len(t) < 6:
            continue
        h = re.search(r'href="([^"]*)"', attrs)
        oc = re.search(r"onclick=\"([^\"]*)\"", attrs)
        href = html.unescape(h.group(1)) if h else ""
        url = None
        if kind == "egov":
            g = re.search(r"goTo\.view\('list','(\d+)','(\d+)','(\d+)'\)", (oc.group(1) if oc else "") + href)
            b = re.search(r"boardView\('listForm',\s*'[^']*',\s*'[^']*',\s*'(\d+)',\s*'(\d+)',\s*'(\d+)'", (oc.group(1) if oc else "") + href)
            g = g or b
            if g:
                path = "/tour/bbs/view.do" if "/tour/" in list_url else "/portal/bbs/view.do"
                root = re.match(r"https?://[^/]+", list_url).group(0)
                url = f"{root}{path}?bIdx={g.group(1)}&ptIdx={g.group(2)}&mId={g.group(3)}"
        elif re.search(r"(view[^\"]*(dataSid|idx|bIdx)=\d+)|amode=view", href):
            url = _abs(list_url, href)
        if not url or url in seen:
            continue
        seen.add(url)
        # 제목에 본문 미리보기가 붙은 게시판(서구·영도·기장) → 앞부분만 제목으로
        t = re.split(r"\s+(?:[□○❍ㅇ■◎●▶※]|\d{4}-\d\d-\d\d\b)", t)[0].strip()
        t = re.sub(r"\s*\(\s*(공연|전시|행사|교육)\s*\)\s*$", "", t)
        t = re.sub(r"\s+20\d\d[.\-]\d\d[.\-]\d\d\.?$", "", t).strip()
        t = re.sub(r"\s*(새\s*글|NEW|N)\s*$", "", t).strip()
        k = t[:8]
        if len(t) > 16 and k and t.find(k, 6) > 0:   # 제목 뒤에 본문 미리보기가 제목부터 반복되는 경우
            t = t[:t.find(k, 6)].strip()
        t = re.sub(r"\s*(새\s*글|NEW)\s*$", "", t).strip()
        t = re.sub(r"\s+(\d{1,2}:\d\d)$", "", t)
        if len(t) > 26 and re.search(r"개최\s+\S", t):
            t = t[:re.search(r"개최\s+\S", t).start() + 2]
        rows.append((t[:90], url.replace(" ", "%20"), None))
    return rows


def is_event_title(t):
    if not re.search(EV_POS, t):
        return False
    if re.search(EV_NEG, t) and not re.search(EV_STRONG, t):
        return False
    if re.search(r"(수강생|교육생|위원)\s*모집|채용|입찰|심사결과|결과\s*(발표|안내|알림)|시상식\s*결과", t):
        return False
    return True


_DOW = r"(?:\s*\(\s*[월화수목금토일](?:요일)?\s*\)|\s*[월화수목금토일]요일)?"


def parse_range(text, year_hint):
    """'2026. 10. 17.(토) ~ 10. 18.(일)', '10월 13일(화)', '26.7.31.~8.2.' → (s, e) ISO 또는 None"""
    if not text:
        return None
    full = r"(20\d\d|'?[’‘']?\d\d)\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?\.?" + _DOW
    md = r"(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?\.?" + _DOW
    tm = r"(?:\s*(?:\d{1,2}:\d\d|\d{1,2}시(?:\s*\d{1,2}분)?|오[전후]\s*\d{1,2}시(?:\s*\d{1,2}분)?)(?:\s*[~\-]\s*(?:\d{1,2}:\d\d|\d{1,2}시))?)?"

    def y4(y):
        y = re.sub(r"\D", "", y)
        return int(y) if len(y) == 4 else 2000 + int(y)

    def ok(y, m, d):
        try:
            return datetime.date(y, m, d)
        except ValueError:
            return None

    m = re.search(full + tm + r"\s*[~∼\-–]\s*(?:" + full + r"|" + md + r"|(\d{1,2})(?![\d:])\s*일?(?!\s*[:\d])" + r")", text)
    if m:
        y = y4(m.group(1)); s = ok(y, int(m.group(2)), int(m.group(3)))
        if m.group(4):
            e = ok(y4(m.group(4)), int(m.group(5)), int(m.group(6)))
        elif m.group(7):
            e = ok(y, int(m.group(7)), int(m.group(8)))
        else:
            e = ok(y, int(m.group(2)), int(m.group(9)))
        if s and e and e < s and m.group(7):
            e = ok(y + 1, int(m.group(7)), int(m.group(8)))
        if s and e and s <= e and (e - s).days < 400:
            return s.isoformat(), e.isoformat()
    m = re.search(full, text)
    if m:
        s = ok(y4(m.group(1)), int(m.group(2)), int(m.group(3)))
        if s:
            return s.isoformat(), s.isoformat()
    m = re.search(r"(?<![\d.])" + md + tm + r"(?:\s*[~∼\-–]\s*" + md + r")?", text)
    if m and ("월" in m.group(0) or re.search(r"\d{1,2}\.\s*\d{1,2}\.", m.group(0))):
        s = ok(year_hint, int(m.group(1)), int(m.group(2)))
        e = ok(year_hint, int(m.group(3)), int(m.group(4))) if m.group(3) else s
        if s and e:
            if e < s:
                e = ok(year_hint + 1, e.month, e.day)
            return s.isoformat(), e.isoformat()
    return None


def body_lines(page, title):
    L = lines_of(re.sub(r"</td>|</th>|</tr>|</h\d>", "\n", page))
    key = norm(title)[:7]
    idx = [i for i, x in enumerate(L) if key and key in norm(x)]
    start = idx[1] if len(idx) > 1 else (idx[0] if idx else 0)
    out = []
    for x in L[start:start + 220]:
        if re.match(r"^(목록|이전글|다음글|담당부서|만족도|이 페이지에서 제공하는|현재 페이지의 만족도|공공누리|TOP)$", x) or x.startswith("이 페이지에서 제공"):
            break
        out.append(x)
    # 게시판 헤더(작성일·조회수 등) 제거
    clean, skip = [], False
    for x in out:
        if skip:
            skip = False
            continue
        if re.match(r"^(작성일|등록일|조회수|작성자|담당자|문의전화|최근업데이트|게시일)\s*:?$", x):
            skip = True
            continue
        if re.match(r"^(작성일|등록일|게시일|최근업데이트)\s*[:：]?\s*20\d\d", x):
            continue
        clean.append(x)
    return clean


LABEL_DATE = r"(?:행\s*사\s*)?(?:일\s*시|기\s*간|일\s*자|날\s*짜|행사\s*일|공연\s*일|운영\s*기간|운영\s*일자?|운영\s*일시|축제\s*기간|전시\s*기간|개최\s*일시?|공연\s*일시|행사\s*일시|교육\s*일시)"
LABEL_PLACE = r"(?:장\s*소|행사\s*장소|공연\s*장소|개최\s*장소|전시\s*장소|위\s*치|장소\s*및\s*시간)"
LABEL_FEE = r"(?:관람\s*료|참\s*가\s*비|요\s*금|입장\s*료|가\s*격|티\s*켓|관람\s*가격|참여\s*비)"


def labeled(B, label, maxlen=120):
    """'○ 일 시 : 값' 또는 '일시' 다음 줄 값."""
    for i, x in enumerate(B):
        m = re.match(r"^[\s○●■□▶\-\*·•※◎◆▪❍ㅇ✔✅☞▷◇\d\).가-나]{0,4}\s*" + label + r"\s*(?:[:：]|\s{1,3}(?=\S))\s*(.*)$", x)
        if m:
            v = m.group(1).strip(" :：/")
            j = i + 1
            while len(v) < 4 and j < len(B) and j < i + 6:
                v = (v + " " + B[j]).strip(" :：/"); j += 1
            return v[:maxlen]
        if re.fullmatch(r"[○●■□▶\-·•※◎◆▪❍ㅇ✔]?\s*" + label, x) and i + 1 < len(B):
            v = " ".join(B[i + 1:i + 4]).strip(" :：/")
            return v[:maxlen]
    return ""


def split_names(v):
    v = re.sub(r"\(.*?\)|\[.*?\]|등\s*$|외\s*\d*\s*(명|팀)?\s*$|외\s*다수.*$", "", v)
    parts = [p.strip(" .·-") for p in re.split(r"[,，、/·|]|\s+및\s+|\s*&\s*|\s+그리고\s+", v)]
    return [p for p in parts if 1 < len(p) <= 24 and not re.search(r"\d{1,2}:\d\d|\d+\s*(원|명|석)|미정|추후|예정|공개", p)]


def extract_lineup(B, src, srcu):
    out = []
    for x in B:
        m = re.match(r"^[\s○●■□▶\-\*·•※◎◆▪❍ㅇ✔✅☞▷◇\d\)]{0,4}\s*(" + LINEUP_LABEL + r")\s*[:：]\s*(.{2,120})$", x)
        if not m:
            continue
        role = re.sub(r"\s+", "", m.group(1))
        role = {"사회": "MC", "주요출연진": "출연", "출연진": "출연", "출연자": "출연", "게스트": "게스트"}.get(role, role)
        for n in split_names(m.group(2))[:12]:
            r2 = role
            mm = re.match(r"^(가수|배우|개그맨|개그우먼|방송인|아나운서|성악가|피아니스트|작가|교수|대표)\s+(.+)$", n)
            if mm:
                n, r2 = mm.group(2), f"{role}({mm.group(1)})"
            out.append({"name": n, "role": r2, "src": src, "srcu": srcu, "chk": TODAY})
    # 중복 제거
    seen, res = set(), []
    for x in out:
        if x["name"] not in seen:
            seen.add(x["name"]); res.append(x)
    return res[:16]


def gu_event_from_view(gu, src_name, title, url, list_dates):
    page = fetch(url, verify=False, timeout=20)
    B = body_lines(page, title)
    text = "\n".join(B)
    year_hint = NOW.year
    when = labeled(B, LABEL_DATE)
    rng = parse_range(when, year_hint) or (list_dates if list_dates else None) or parse_range(title, year_hint)
    if not rng:
        # 본문 첫 날짜(제목 아래 300자 이내)만 신뢰
        rng = parse_range(text[:300], year_hint)
    if not rng:
        return None
    s, e = rng
    place = labeled(B, LABEL_PLACE, 80)
    place = re.split(r"\s+(?:[○●■□▶※❍ㅇ]|\d\))\s*", place)[0].strip(" :")
    place = re.sub(r"\s*(홈페이지\s*)?예매(하기)?.*$|\s*지도\s*보기.*$", "", place).strip()
    if re.match(r"^\d|^[(:/]", place):
        place = ""
    fee = labeled(B, LABEL_FEE, 80)
    hours = ""
    mt = re.search(r"(\d{1,2}:\d\d\s*(?:[~\-]\s*\d{1,2}:\d\d)?|오[전후]\s*\d{1,2}시(?:\s*\d{1,2}분)?|\d{1,2}시(?:\s*\d{1,2}분)?)", when or "")
    if mt:
        hours = mt.group(1)
    g = gu
    if place:
        pg = guess_gu(place)
        if pg != "부산 전역" and src_name.endswith("문화회관 공지") is False and pg != gu and re.search(r"부산\s*(광역)?시?\s*" + pg, place):
            g = pg
    desc = ""
    for x in B[1:12]:
        if len(x) > 25 and not re.search(LABEL_DATE + r"|" + LABEL_PLACE, x):
            desc = x[:160]; break
    return {
        "n": title, "s": s, "e": e, "gu": g, "type": guess_type(title, text),
        "p": place[:80], "addr": "", "hours": hours, "fee": fee, "org": "", "tel": "",
        "u": "", "srcu": url, "src": src_name, "chk": TODAY, "st": "confirmed",
        "lineup": extract_lineup(B, src_name, url), "x": desc,
    }


def scrape_hd_calendar(list_url):
    """해운대구 '연간행사안내' 표: 구분|행사명|기간|장소|소관부서"""
    page = fetch(list_url, verify=False, timeout=25)
    evs = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        tds = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", td))).strip() for td in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(tds) < 4:
            continue
        if len(tds) >= 5:
            name, per, place = tds[1], tds[2], tds[3]
        else:
            name, per, place = tds[0], tds[1], tds[2]
        if not re.search(r"\d", per) or name in ("행사명",):
            continue
        rng = parse_range(per, NOW.year)
        if not rng:
            continue
        evs.append({"n": name, "s": rng[0], "e": rng[1], "gu": "해운대구", "type": guess_type(name), "p": place[:80], "addr": "",
                    "hours": "", "fee": "", "org": tds[-1] if len(tds) >= 5 else "", "tel": "", "u": "", "srcu": list_url,
                    "src": "해운대구 연간행사안내", "chk": TODAY, "st": "confirmed", "lineup": []})
    return evs


def scrape_gu_source(sid, gu, name, url, kind):
    errors = 0
    if kind == "hd_calendar":
        evs = scrape_hd_calendar(url)
    else:
        page = fetch(url, verify=False, timeout=25)
        rows = gu_list_rows(sid, url, kind, page)
        cand = [r for r in rows if is_event_title(r[0])][:GU_VIEW_MAX]
        evs = []
        for t, u, ld in cand:
            try:
                ev = gu_event_from_view(gu, name, t, u, ld)
            except TimeoutError:
                raise
            except Exception as e:  # noqa
                errors += 1
                log(f"  [{sid}] 상세 실패 {u}: {e!r}")
                if ld:
                    ev = {"n": t, "s": ld[0], "e": ld[1], "gu": gu, "type": guess_type(t), "p": "", "addr": "", "hours": "", "fee": "",
                          "org": "", "tel": "", "u": "", "srcu": u, "src": name, "chk": TODAY, "st": "confirmed", "lineup": []}
                else:
                    continue
            if ev:
                evs.append(ev)
    out = []
    horizon = (NOW.date() + datetime.timedelta(days=430)).isoformat()
    for ev in evs:
        if not ev or (ev["e"] or "") < TODAY or ev["s"] > horizon:
            continue
        if (ev["e"] and ev["s"] and (_date(ev["e"]) - _date(ev["s"])).days > 200) and not re.search(EV_STRONG, ev["n"]):
            continue  # 상시 모집·장기 운영 공지 제외
        pid = re.search(r"(?:dataSid|bIdx|idx|sno|epId)=(\d+)", ev["srcu"])
        ev["id"] = ("gu-" + sid + "-" + (pid.group(1) if pid else norm(ev["n"])[:16] + ev["s"])) if kind != "hd_calendar" else "gu-hd-" + norm(ev["n"])[:20] + ev["s"][:4]
        ev["origin"] = "gu:" + sid
        out.append(ev)
    return out, errors


def run_gu_sources(prev_events, status):
    allev, down = [], set()
    for sid, gu, name, url, kind in GU_SOURCES:
        origin = "gu:" + sid
        prev_src = [e for e in prev_events if e.get("origin") == origin and is_current(e)]
        host = urllib.parse.urlparse(url).netloc
        t0 = time.time()
        try:
            if host in down:
                raise ConnectionError(f"{host} 접속 불가(같은 실행에서 이미 실패)")
            DEADLINE["t"] = time.time() + GU_BUDGET
            items, errs = scrape_gu_source(sid, gu, name, url, kind)
            DEADLINE.pop("t", None)
            st = {"ok": True, "gu": gu, "name": name, "url": url, "count": len(items), "errors": errs}
            if not items and prev_src:
                st.update(ok=False, kept_previous=True, note="이번 수집 0건 → 이전 데이터 유지")
                items = prev_src
            log(f"[{origin}] {gu} {name}: {len(items)}건 ({time.time() - t0:.0f}s, 오류 {errs})")
        except Exception as e:  # noqa
            DEADLINE.pop("t", None)
            if isinstance(e, (TimeoutError, ConnectionError, OSError)) and not isinstance(e, urllib.error.HTTPError):
                down.add(host)
            st = {"ok": False, "gu": gu, "name": name, "url": url, "error": str(e)[:160], "kept_previous": bool(prev_src), "count": len(prev_src)}
            items = prev_src
            log(f"[{origin}] {gu} 수집 실패 → 이전 데이터 유지({len(prev_src)}건): {e!r}")
        status[origin] = st
        allev += items
    return allev


SCHEMA_NOTE = ("events[]: id(고유·불변), n(제목), s/e(시작·종료 YYYY-MM-DD, 예상 시기는 YYYY-MM), gu(구·군), p(장소), addr, hours, fee, "
               "type, st(confirmed|check|expected), url(공식 링크), lineup[{name, role, when?, src, srcu, chk}], lineup_status(공개|미공개), origin")


def apply_lineups(events, lineups):
    """events_manual.json의 lineups(직접 확인한 출연진)를 제목 일부+시작 연월로 매칭해 붙임. 자동 수집 출연진과 합침."""
    for lu in lineups:
        key = norm(lu.get("match"))
        hits = [e for e in events if key and key in norm(e.get("n")) and (e.get("s") or "").startswith(lu.get("s", "")) and e.get("st") != "expected"]
        for e in hits[:2]:
            cur = list(e.get("lineup") or [])
            names = {x.get("name") for x in cur}
            for x in lu.get("lineup", []):
                if x.get("name") and x["name"] not in names:
                    cur.append(dict(x)); names.add(x["name"])
            # 직접 확인한 항목을 앞에
            manual_names = [x["name"] for x in lu.get("lineup", [])]
            cur.sort(key=lambda x: manual_names.index(x["name"]) if x["name"] in manual_names else 999)
            e["lineup"] = cur


def finalize_schema(events):
    """텔레그램 알림 등 외부 사용을 위한 고정 스키마 보장."""
    used = set()
    for e in events:
        if not e.get("id"):
            e["id"] = "ev-" + norm(e.get("n"))[:24] + "-" + (e.get("s") or "")[:10]
        base, k = e["id"], 2
        while e["id"] in used:
            e["id"] = f"{base}-{k}"; k += 1
        used.add(e["id"])
        e.setdefault("e", e.get("s"))
        e.setdefault("p", "")
        e["url"] = e.get("u") or e.get("srcu") or ""
        lu = [x for x in (e.get("lineup") or []) if isinstance(x, dict) and x.get("name")]
        e["lineup"] = lu
        e["lineup_status"] = "공개" if lu else "미공개"


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
    cc, _ = run_source("concert", scrape_concerts, prev_events, status, min_ratio=0.4, min_abs=2) if os.environ.get("SKIP_CONCERT") != "1" else ([e for e in prev_events if e.get("origin") == "concert"], ())
    gu_ev = run_gu_sources(prev_events, status) if os.environ.get("SKIP_GU") != "1" else [e for e in prev_events if (e.get("origin") or "").startswith("gu:")]

    events = []
    for m in manual["events"]:
        events.append(dict(m))
    for group in (vb, kf, bx, cc, gu_ev):
        for v in group:
            hit = next((e for e in events if same(e, v)), None)
            if hit:
                merge_into(hit, v)
                if v.get("type") == "콘서트":
                    hit["type"] = "콘서트"
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
    apply_lineups(events, manual.get("lineups", []))
    finalize_schema(events)
    events.sort(key=lambda e: ((e.get("s") or "9999") + ("-99" if len(e.get("s") or "") == 7 else ""), e["n"]))

    data = {"updated": NOW.strftime("%Y-%m-%d %H:%M"), "tz": "KST", "status": status,
            "schema": SCHEMA_NOTE,
            "sources": {"visitbusan": "https://www.visitbusan.net/schedule/list.do?boardId=BBS_0000009&menuCd=DOM_000000204012000000",
                        "kfes": "https://korean.visitkorea.or.kr/kfes/list/wntyFstvlList.do",
                        "bexco": "https://www.bexco.co.kr/kor/CMS/EventScheduleMgr/list.do?mCode=MN214",
                        "concert": "https://ticket.yes24.com/New/Genre/GenreList.aspx?genretype=1&genre=15456 , https://tickets.interpark.com/contents/genre/concert",
                        **{"gu:" + x[0]: x[3] for x in GU_SOURCES}},
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
