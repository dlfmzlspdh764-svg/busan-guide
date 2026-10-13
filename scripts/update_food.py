#!/usr/bin/env python3
"""주간 맛집 업데이트 (카카오맵 기준, stdlib only).
- food.json 이 없으면 index.html 의 FOOD/SUSHI 로 시드하고 index.html 에 food.json 로더를 붙임
- 구·군별 후보 재검색 → 상세 갱신 → RANKING 10 / 스시뷔페 TOP 10 재계산
- 새로 랭킹 10에 든 곳은 first_seen 기록(2주간 🆕 NEW) 후 텔레그램 알림
- 실패하면 기존 데이터를 그대로 둠 (절대 비우지 않음)"""
import json, os, re, sys, time, urllib.request, urllib.parse, datetime
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML, FJ = os.path.join(ROOT, "index.html"), os.path.join(ROOT, "food.json")
APP = "https://dlfmzlspdh764-svg.github.io/busan-guide/"
KST = datetime.timezone(datetime.timedelta(hours=9))
TODAY = datetime.datetime.now(KST).strftime("%Y-%m-%d")
GUS = ["중구","서구","동구","영도구","부산진구","동래구","남구","북구","해운대구","사하구","금정구","강서구","연제구","수영구","사상구","기장군"]
QS = ["맛집","한식","중식","일식","양식","밀면","돼지국밥","횟집","고기","국밥","태국음식","베트남음식","초밥"]
SQS = ["초밥뷔페","스시뷔페","무한리필 초밥","쿠우쿠우","스시에버","해산물뷔페"]
HS = {"Referer": "https://map.kakao.com/", "User-Agent": "Mozilla/5.0"}
HP = {"Referer": "https://place.map.kakao.com/", "pf": "web", "User-Agent": "Mozilla/5.0", "Accept": "application/json"}
CH = re.compile(r'맥도날드|버거킹|롯데리아|KFC|맘스터치|교촌|BBQ|bhc|굽네|이삭토스트|김밥천국|본죽|빕스|아웃백|애슐리|쿠우쿠우|명륜진사|두끼|홍콩반점|역전할머니|새마을식당|한신포차|봉구스|서브웨이|도미노|피자헛|파파존스|미스터피자|신전떡볶이|엽기떡볶이|청년다방|하남돼지|연안식당|채선당|샤브올데이|생활맥주|백종원|빽|본도시락|한솥|고봉민|김가네|국수나무|원할머니|놀부|이차돌|등촌|역전우동|스시로|일미리|담소|설빙|조폭떡볶이|땅땅치킨|60계|노랑통닭|처갓집|네네|페리카나|푸라닭|자담|호식이')
DAY = {'monday':'월','tuesday':'화','wednesday':'수','thursday':'목','friday':'금','saturday':'토','sunday':'일'}

def jget(url, h):
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20))
        except Exception:
            time.sleep(2 + i * 2)
    return None

def search(q, p):
    return jget("https://search.map.kakao.com/mapsearch/map.daum?callback=&q=%s&msFlag=A&sort=0&page=%d" % (urllib.parse.quote(q), p), HS)

def detail(i):
    d = jget("https://place-api.map.kakao.com/places/panel3/" + i, HP)
    time.sleep(0.25)
    return i, (d if d and d.get("summary") else None)

# ---------- 1) 데이터 로드 / 최초 이전 ----------
def inline(s, name):
    m = re.search(r'^(?:const|let|var) %s=(\[.*?\]);$' % name, s, re.M)
    return json.loads(m.group(1)) if m else None

LOADER = r'''<script>
/* food.json 주간 자동 업데이트 로더 (실패하면 위 내장 데이터 사용) */
(async()=>{try{const r=await fetch("food.json?t="+Date.now(),{cache:"no-store"});if(!r.ok)return;const j=await r.json();
if(j&&Array.isArray(j.food)&&j.food.length>100){FOOD=j.food;if(Array.isArray(j.sushi)&&j.sushi.length)SUSHI=j.sushi;FUPD=j.updated||FUPD;if(typeof tab!=="undefined"&&tab==="food")render()}}catch(_){}})();
</script>
'''
JS_HELPERS = 'let FUPD="2026-10-13";\nconst isNewF=p=>p.fs&&p.fs!=="seed"&&(Date.now()-Date.parse(p.fs+"T00:00:00+09:00"))<14*864e5;\n'

def patch_html(s):
    if "food.json?t=" in s:
        return s
    s = re.sub(r'^const FOOD=', 'var FOOD=', s, count=1, flags=re.M)
    s = re.sub(r'^const SUSHI=', 'var SUSHI=', s, count=1, flags=re.M)
    s = s.replace("const ALLF=()=>", JS_HELPERS + "const ALLF=()=>", 1)
    # NEW 배지 + 업데이트 날짜
    s = s.replace('<span class="rank">${i+1}</span>${esc(p.n)}</h3>',
                  '<span class="rank">${i+1}</span>${esc(p.n)}${isNewF(p)?` <span class="tag" style="background:#ff3b30;color:#fff">🆕 NEW</span>`:""}</h3>', 1)
    s = s.replace('${list.length}곳 · ${FSORTS[fsort]}</span></div>`+sorts+cats+',
                  '${list.length}곳 · ${FSORTS[fsort]}</span></div><div class="src" style="margin:-4px 0 6px">🔄 맛집 업데이트: ${FUPD} (매주 월요일 자동)</div>`+sorts+cats+', 1)
    i = s.rindex("</body>")
    return s[:i] + LOADER + s[i:]

html = open(HTML, encoding="utf-8").read()
if os.path.exists(FJ):
    DB = json.load(open(FJ, encoding="utf-8"))
else:
    DB = {"updated": "2026-10-13", "food": inline(html, "FOOD"), "sushi": inline(html, "SUSHI"), "first_seen": None}
newhtml = patch_html(html)
if newhtml != html:
    assert "food.json?t=" in newhtml and "isNewF(p)" in newhtml and "맛집 업데이트" in newhtml, "index.html 패치 실패"
    open(HTML, "w", encoding="utf-8").write(newhtml)
    print("index.html: food.json 로더 추가")
OLD, OLDS = DB["food"], DB["sushi"] or []
SEED = DB.get("first_seen") is None
FS = DB.get("first_seen") or {}
OLDMAP = {p["id"]: p for p in OLD}

# ---------- 2) 후보 재검색 ----------
def cands(gu):
    out = {}
    for q in QS:
        for pg in (1, 2):
            j = search(f"부산 {gu} {q}", pg)
            if j is None: return gu, None
            pl = j.get("place") or []
            for x in pl:
                t = (x.get("address") or "").split()
                if len(t) < 2 or t[0] != "부산" or t[1] != gu or x.get("cate_name_depth1") != "음식점": continue
                allc = " ".join(x.get(k) or "" for k in ("cate_name_depth2", "cate_name_depth3", "cate_name_depth4"))
                if re.search("카페|간식|술집", allc) or x.get("brand") or x.get("openoff_status") not in ("Y", None): continue
                if CH.search(x["name"]): continue
                out[x["confirmid"]] = int(x.get("rating_count") or 0)
            if len(pl) < 15: break
            time.sleep(0.3)
    return gu, out

newids, okgu = [], 0
with ThreadPoolExecutor(4) as ex:
    for gu, o in ex.map(cands, GUS):
        if o is None: print("검색 실패", gu); continue
        okgu += 1
        L = sorted([k for k, v in o.items() if v >= 10], key=lambda k: -o[k])[:22]
        newids += [k for k in L if k not in OLDMAP]
print("검색 성공 구", okgu, "새 후보", len(newids))
if okgu < 12:
    print("검색 실패가 많아 기존 데이터 유지"); sys.exit(0)

sushi_c = set(p["id"] for p in OLDS)
for q in SQS:
    j = search("부산 " + q, 1) or {}
    for x in j.get("place") or []:
        allc = " ".join(x.get(k) or "" for k in ("cate_name_depth2", "cate_name_depth3", "cate_name_depth4"))
        if (x.get("address") or "").startswith("부산") and "뷔페" in allc + x["name"] and re.search("초밥|스시|쿠우쿠우|해산물|씨푸드", allc + x["name"]):
            sushi_c.add(x["confirmid"])
    time.sleep(0.3)

# ---------- 3) 상세 조회 ----------
ids = list(dict.fromkeys([p["id"] for p in OLD] + newids + list(sushi_c)))
DET = {}
with ThreadPoolExecutor(4) as ex:
    for i, d in ex.map(detail, ids):
        if d: DET[i] = d
print("상세 성공", len(DET), "/", len(ids))
if len(DET) < 0.7 * len(ids):
    print("상세 조회 실패가 많아 기존 데이터 유지"); sys.exit(0)

def closed(sm):
    return sm.get("status") not in ("Y", None) or re.search("폐업|휴업", sm.get("name") or "")

def img(d):
    for x in ((d.get("menu") or {}).get("menus") or {}).get("items", []):
        if x.get("photo_url") and "kakaocdn" in x["photo_url"]: return x["photo_url"].replace("http:", "https:")
    for x in ((d.get("photos") or {}).get("photos") or []):
        if "kakaocdn" in x.get("url", "") and x.get("media_type", "PHOTO") == "PHOTO": return x["url"].replace("http:", "https:")
    return None

def hours(d):
    h = []
    for wp in ((d.get("open_hours") or {}).get("week_from_today") or {}).get("week_periods", []):
        for day in wp.get("days", []):
            h.append([re.sub(r"\(.*?\)", "", day.get("day_of_the_week_desc", "")), (day.get("on_days") or {}).get("start_end_time_desc") or day.get("off_days_desc") or ""])
    return h

def cat_of(n, c2, c3):
    allc = c2 + " " + c3
    if "카페" in allc: return "카페"
    if "돼지국밥" in n or ("국밥" in c3 and "돼지" in n): return "돼지국밥"
    if "밀면" in n or "밀면" in c3: return "밀면"
    if "뷔페" in allc and re.search("초밥|스시|해산물|일식", allc + n): return "스시뷔페"
    if "태국" in allc: return "태국"
    if "베트남" in allc: return "베트남"
    return {"일식": "일식", "중식": "중식", "양식": "서양식", "한식": "한식"}.get(c2) or ("서양식" if re.search("이탈리|프랑스|스테이크", allc) else "기타")

def refresh(r, d, new=False):
    sm = d["summary"]; ss = (d.get("kakaomap_review") or {}).get("score_set") or {}
    v = d.get("visitor") or {}
    w = [x for x in (v.get("weekly_uv_average") or []) if isinstance(x, (int, float))]
    days = {k: sum(x for x in v.get(k + "_uv", []) if isinstance(x, (int, float))) for k in DAY}
    mn = (d.get("menu") or {}).get("menus") or {}
    items = [x for x in mn.get("items", []) if x.get("name")]
    r["rc"] = ss.get("review_count") or r.get("rc") or 0
    r["sc"] = ss.get("average_score") or r.get("sc") or None
    if sum(w): r["vi"] = sum(w); r["vupd"] = (v.get("updated_at") or "")[:10] or r.get("vupd")
    if any(days.values()): r["vbusy"] = DAY[max(days, key=days.get)]
    u = img(d)
    if u: r["im"] = u
    h = hours(d)
    if h: r["h"] = h
    if items:
        r["m"] = [[x["name"], x.get("price")] for x in items[:8]]; r["mu"] = (mn.get("items_updated_at") or "")[:10]
        if r.get("c") != "스시뷔페":
            pr = [x[1] for x in r["m"] if x[1]]
            r["pr"] = [min(pr), max(pr)] if pr else r.get("pr")
    bl = (d.get("blog_review") or {}).get("review_count")
    if bl: r["bl"] = bl
    ip = ((d.get("photos") or {}).get("counts") or {}).get("total")
    if ip: r["ip"] = ip
    r["ck"] = TODAY
    return r

out = []
for p in OLD:
    d = DET.get(p["id"])
    if d and closed(d["summary"]): print("폐업/휴업 제외:", p["n"]); continue
    out.append(refresh(dict(p), d) if d else dict(p))
for i in newids:
    d = DET.get(i)
    if not d or closed(d["summary"]): continue
    sm = d["summary"]; ad = sm.get("address") or {}; disp = ad.get("disp") or ""
    t = disp.split()
    if len(t) < 2 or t[0] != "부산" or t[1] not in GUS: continue
    cat = sm.get("category") or {}
    if cat.get("name1") != "음식점" or CH.search(sm["name"]): continue
    kr = d.get("kakaomap_review") or {}; ss = kr.get("score_set") or {}
    cnt = {x["id"]: x["count"] for x in ss.get("strength_counts", [])}
    sd = kr.get("strength_description") or []
    names = [x["name"] for x in sd][:3]
    r = dict(id=i, n=sm["name"], a=t[1], gu=t[1], c=cat_of(sm["name"], cat.get("name2") or "", cat.get("name3") or ""),
             kc=cat.get("name3") or cat.get("name2") or "",
             addr=f"{ad['road']} ({ad['jibun_part']})" if ad.get("road") and ad.get("jibun_part") else disp,
             tel=((sm.get("phone_numbers") or [{}])[0]).get("tel", ""), st=[[x["name"], cnt.get(x["id"], 0)] for x in sd][:3],
             m=[], mu="", h=[], ip=0, bl=0, pr=None,
             sm=[f"카카오맵 방문자들이 {'·'.join(names)}을(를) 장점으로 많이 꼽은 곳"] if names else [f"카카오맵 분류: {cat.get('name3') or cat.get('name2') or ''}"],
             gr=None, gc=None, nid=None, nv=None, ns=None, nb=None)
    out.append(refresh(r, d, True))

# ---------- 4) 랭킹 재계산 (build.py 방식) ----------
tot = lambda p: (p.get("rc") or 0) + (p.get("nv") or 0) + (p.get("gc") or 0)
for p in out:
    for k in ("dps", "psv", "psr", "gr10"): p.pop(k, None)
    if p.get("sc") == 0: p["sc"] = None
R = [p for p in out if p.get("c") != "카페" and tot(p) >= 10]
def pct(m):
    vals = sorted(p[m] for p in R if p.get(m)); N = len(vals); res = {}
    for p in R:
        if p.get(m):
            res[p["id"]] = (sum(1 for x in vals if x < p[m]) + (vals.count(p[m]) - 1) / 2) / max(N - 1, 1)
    return res
PV, PR, PN, PG = pct("vi"), pct("rc"), pct("nv"), pct("gc")
for p in R:
    rv = [m[p["id"]] for m in (PR, PN, PG) if p["id"] in m]; rs = sum(rv) / len(rv) if rv else None
    s = (0.5 * PV[p["id"]] + 0.5 * rs) if p["id"] in PV and rs is not None else (PV.get(p["id"]) if rs is None else rs) or 0
    p["dps"] = round(100 * s); p["psv"] = round(100 * PV[p["id"]]) if p["id"] in PV else None; p["psr"] = round(100 * rs) if rs is not None else None
    rt = [(x, w) for x, w in ((p.get("sc"), p.get("rc")), (p.get("ns"), p.get("nv")), (p.get("gr"), p.get("gc"))) if x and w]
    p["ar"] = round(sum(x * w for x, w in rt) / sum(w for x, w in rt), 2) if rt else None
for gu in GUS:
    for k, p in enumerate(sorted([p for p in R if p.get("gu") == gu], key=lambda p: (-p["dps"], -tot(p)))):
        p["gr10"] = k + 1

# 스시뷔페 TOP 10
S, oldS = [], {p["id"]: p for p in OLDS}
for i in sushi_c:
    d = DET.get(i)
    if not d:
        if i in oldS: S.append(dict(oldS[i]))
        continue
    sm = d["summary"]
    if closed(sm) or "예정" in sm["name"]: continue
    t = ((sm.get("address") or {}).get("disp") or "").split()
    if len(t) < 2 or t[1] not in GUS: continue
    cat = sm.get("category") or {}
    r = oldS.get(i) and dict(oldS[i]) or dict(id=i, n=sm["name"], a=t[1], gu=t[1], c="스시뷔페", kc=cat.get("name3") or cat.get("name2") or "",
        addr=(sm.get("address") or {}).get("disp"), tel=((sm.get("phone_numbers") or [{}])[0]).get("tel", ""), st=[], m=[], mu="", h=[], ip=0, bl=0, sm=[], pr=None)
    refresh(r, d)
    items = [x for x in (((d.get("menu") or {}).get("menus") or {}).get("items", [])) if x.get("price") and x["price"] >= 15000]
    if items: r["pr"] = [min(x["price"] for x in items), max(x["price"] for x in items)]
    S.append(r)
S = [r for r in S if (r.get("rc") or 0) >= 20 and r.get("sc")]
S.sort(key=lambda r: (-r["sc"], -r["rc"]))
for k, r in enumerate(S): r["sb"] = k + 1
S = S[:15]

# ---------- 5) 안전 검사 ----------
if len(out) < 0.8 * len(OLD) or sum(1 for p in out if p.get("gr10", 99) <= 10) < 120 or len(S) < 8:
    print("결과가 비정상적으로 작아 기존 데이터 유지", len(out), len(S)); sys.exit(0)

# ---------- 6) NEW 표시 ----------
ranked = [p for p in out if p.get("gr10", 99) <= 10] + S[:10]
fresh = []
for p in ranked:
    if p["id"] not in FS:
        FS[p["id"]] = "seed" if SEED else TODAY
        if not SEED: fresh.append(p)
for p in out + S:
    if p["id"] in FS: p["fs"] = FS[p["id"]]
    else: p.pop("fs", None)

newdb = {"updated": DB.get("updated"), "food": out, "sushi": S, "first_seen": FS}
def body(x): return json.dumps({k: v for k, v in x.items() if k != "updated"}, ensure_ascii=False, sort_keys=True)
changed = (not os.path.exists(FJ)) or body(newdb) != body(DB)
if changed:
    newdb["updated"] = TODAY
    json.dump(newdb, open(FJ, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("저장" if changed else "변경 없음", "food", len(out), "sushi", len(S), "new", len(fresh), "seed" if SEED else "")

# ---------- 7) 텔레그램 ----------
tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
if fresh and tok and chat:
    lines = [f"🍽️ 이번 주 새로 랭킹에 든 부산 맛집 ({len(fresh)}곳)", ""]
    for p in fresh[:25]:
        lines.append(f"🆕 {p['n']} · {p.get('gu','')} · {p.get('c','')}" + (f" · ★{p['sc']}" if p.get("sc") else "") + f"\n{APP}#place-{p['id']}")
    lines += ["", f"📱 앱에서 보기: {APP}#food"]
    data = urllib.parse.urlencode({"chat_id": chat, "text": "\n".join(lines), "disable_web_page_preview": "true"}).encode()
    try:
        print("telegram", urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=20).status)
    except Exception as e:
        print("telegram 실패", e)
