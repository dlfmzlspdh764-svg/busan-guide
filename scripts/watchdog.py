"""워치독: 주요 워크플로가 오래 성공 못하면 재실행, 그래도 실패면 텔레그램 ⚠️."""
import json, os, subprocess, datetime, urllib.request, urllib.parse
# workflow: 허용 최대 경과 시간(시간) = 주기의 2배
WF = {"tbd-radar.yml": 1.5, "gu-watch.yml": 3, "update-events.yml": 50, "food-weekly.yml": 8 * 24}
STATE = "data/watchdog.json"
now = datetime.datetime.now(datetime.timezone.utc)
st = json.load(open(STATE)) if os.path.exists(STATE) else {}
def gh(*a):
    return subprocess.run(["gh", *a], capture_output=True, text=True).stdout
alerts = []
for wf, hrs in WF.items():
    try:
        runs = json.loads(gh("run", "list", "-w", wf, "-L", "10", "--json", "conclusion,status,createdAt") or "[]")
    except Exception:
        continue
    if any(r["status"] != "completed" for r in runs):
        continue
    ok = [r for r in runs if r["conclusion"] == "success"]
    last = datetime.datetime.fromisoformat(ok[0]["createdAt"].replace("Z", "+00:00")) if ok else None
    age = (now - last).total_seconds() / 3600 if last else 1e9
    if age <= hrs:
        st.pop(wf, None); continue
    tries = st.get(wf, 0)
    print(wf, "stale", round(age, 1), "h → dispatch", tries)
    gh("workflow", "run", wf, "--ref", "main")
    st[wf] = tries + 1
    if tries >= 2 and tries % 6 == 2:  # 재시도 2회 후에도 실패 → 알림 (이후 3시간마다)
        alerts.append(f"• {wf}: 마지막 성공 {round(age,1)}시간 전, 재실행 {tries+1}회")
json.dump(st, open(STATE, "w"), indent=1)
tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
if alerts and tok and chat:
    msg = "⚠️ <b>부산앱 자동작업 점검</b>\n━━━━━━━━━━\n" + "\n".join(alerts) + "\n#부산앱점검"
    urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok,
        urllib.parse.urlencode({"chat_id": chat, "text": msg, "parse_mode": "HTML"}).encode(), timeout=20)
