#!/usr/bin/env python3
"""구·군청·문화회관 게시판 실시간 추적 (1시간 간격, 표준 라이브러리만).

update_events.py의 GU_SOURCES/스크래퍼를 그대로 재사용해 게시판 1쪽만 빠르게 읽고,
events.json에 없던 행사성 글을 바로 추가(기존 데이터는 유지)하고 텔레그램 🚨 속보를 보냅니다.
상태: data/gu_watch.json (첫 실행은 조용히 기준만 저장). 1회 최대 5건 전송.
사용: python3 scripts/gu_watch.py [--dry-run] [--seed]
"""
import json, os, sys, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_events as U  # noqa: E402
from notify_telegram import send  # noqa: E402
from breaking import fmt_event  # noqa: E402

STATE = os.path.join(U.ROOT, "data", "gu_watch.json")
NOTIFIED = os.path.join(U.ROOT, "data", "notified.json")
MAX_SEND = 5
U.GU_VIEW_MAX = 8      # 새 글 위주로 빠르게
U.GU_BUDGET = 45


def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    data = load(U.OUT, None)
    if not data or len(data.get("events", [])) < 20:
        print("events.json 없음/비정상 → 중단"); return 0
    events = data["events"]
    state = load(STATE, {})
    seed = a.seed or not state.get("seeded")
    status = {}
    found = U.run_gu_sources(events, status)
    ids = {e["id"] for e in events}
    seen = set(state.get("seen", []))
    added = []
    for v in found:
        if v["id"] in ids or any(U.same(v, e) for e in events + added):
            continue
        added.append(dict(v))
    if added:
        U.finalize_schema(added)
        events += added
        events.sort(key=lambda e: ((e.get("s") or "9999") + ("-99" if len(e.get("s") or "") == 7 else ""), e["n"]))
    data.setdefault("status", {}).update(status)
    data["gu_watch"] = {"checked": U.NOW.strftime("%Y-%m-%d %H:%M"),
                        "reachable": sorted(k for k, v in status.items() if v.get("ok") or v.get("kept_previous") and "error" not in v),
                        "unreachable": sorted(k for k, v in status.items() if "error" in v)}
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    sent = []
    if not seed:
        for e in [x for x in added if x["id"] not in seen][:MAX_SEND]:
            if not a.dry_run and not (token and chat):
                print("텔레그램 설정 없음 → 전송 생략"); break
            if send(fmt_event(e).replace("[속보] 새 행사 등록", "[속보] 구·군청 새 행사"), token, chat, a.dry_run):
                sent.append(e["id"])
            time.sleep(1)
    if a.dry_run:
        print(f"(dry-run) 새 행사 {len(added)}건 seed={seed}", [e["n"] for e in added]); return 0
    unsent = {e["id"] for e in added} - set(sent) if not seed else set()
    allids = (seen | {e["id"] for e in events if (e.get("origin") or "").startswith("gu:")}) - unsent
    json.dump({"seeded": True, "seen": sorted(allids)},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    # events.json: 새 행사가 있거나 상태만 바뀌어도 저장(상태 변경만으로는 커밋하지 않도록 워크플로에서 events 비교)
    if added:
        data["updated"] = U.NOW.strftime("%Y-%m-%d %H:%M")
        tmp = U.OUT + ".tmp"
        json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        json.load(open(tmp, encoding="utf-8"))
        os.replace(tmp, U.OUT)
    if sent:
        n = load(NOTIFIED, {})
        n["known_ids"] = sorted(set(n.get("known_ids", [])) | set(sent))
        json.dump(n, open(NOTIFIED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"seed={seed} 새 행사 {len(added)} · 전송 {len(sent)} · 접속 실패 {data['gu_watch']['unreachable']} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
