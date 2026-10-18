#!/usr/bin/env python3
"""텔레그램 알림 시각 구분 헬퍼 (HTML parse_mode).

Telegram은 글자색을 지원하지 않으므로 색상 이모지 헤더 바 + 굵은 제목 +
구분선 + 해시태그 푸터로 종류를 구분합니다. 토큰은 절대 출력하지 않습니다.
"""
from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request

LIMIT = 3900  # 텔레그램 4096자 여유
SEP = "━━━━━━━━━━"
THIN = "────────"

# key -> (header_bar, default_title, hashtag)
STYLES = {
    "digest":       ("🟦🟦🟦", "🎉 부산 행사 다이제스트", "#부산행사"),
    "weekly":       ("🟦🟦🟦", "📅 이번 주 부산 행사", "#부산행사주간"),
    "new_event":    ("🟦🟦🟦", "🆕 부산 새 행사", "#부산새행사"),
    "breaking":     ("🟥🟥🟥", "🚨 속보", "#부산속보"),
    "food":         ("🟩🟩🟩", "🍜 신규 맛집", "#부산맛집"),
    "flight_deal":  ("🟨🟨🟨", "✈️ 항공 특가", "#항공특가"),
    "flight_new":   ("🟪🟪🟪", "🆕 신규 직항", "#신규직항"),
    "gu_new":       ("🟧🟧🟧", "🏛 구청 새 행사", "#구청행사"),
    "date_confirm": ("🟧🟧🟧", "📅 날짜 확정", "#날짜확정"),
}


def esc(x) -> str:
    return html.escape(str(x or ""), quote=False)


def _parts(style_key: str, title: str | None = None, subtitle: str = "",
           footer_extra: str = "", sample: bool = False):
    bar, default_title, tag = STYLES[style_key]
    tit = title or default_title
    prefix = "[샘플] " if sample else ""
    head = f"{bar}\n{prefix}<b>{esc(tit)}</b>"
    if subtitle:
        head += f"\n{esc(subtitle)}"
    foot = SEP + "\n" + tag
    if footer_extra:
        foot = footer_extra.rstrip() + "\n" + foot
    return head, foot


def frame(style_key: str, body: str, title: str | None = None, subtitle: str = "",
          footer_extra: str = "", sample: bool = False) -> str:
    """스타일 키로 헤더·본문·푸터를 감싼 HTML 텍스트."""
    head, foot = _parts(style_key, title=title, subtitle=subtitle,
                        footer_extra=footer_extra, sample=sample)
    body = (body or "").strip()
    if body:
        return f"{head}\n{SEP}\n{body}\n{foot}"
    return f"{head}\n{SEP}\n{foot}"


def join_items(items, sep: str = "\n" + THIN + "\n") -> str:
    return sep.join(x.strip() for x in items if x and str(x).strip())


def chunks(text_or_shell: str, item_blocks: list[str] | None = None,
           style_key: str | None = None, title: str | None = None,
           subtitle: str = "", footer_extra: str = "", sample: bool = False) -> list[str]:
    """메시지 분할.

    - chunks(frame(...)) : 길이만 보고 줄 단위로 자름
    - chunks('', items, style_key='digest', subtitle=...) : 아이템 단위로 패킹
    """
    if item_blocks is not None:
        if not style_key:
            raise ValueError("style_key required when packing item_blocks")
        head, foot = _parts(style_key, title=title, subtitle=subtitle,
                            footer_extra=footer_extra, sample=sample)
        out, cur = [], []

        def pack(items, cont=False):
            h = head + (" (계속)" if cont else "")
            body = join_items(items)
            return f"{h}\n{SEP}\n{body}\n{foot}" if body else f"{h}\n{SEP}\n{foot}"

        for it in item_blocks:
            trial = cur + [it]
            if len(pack(trial, cont=bool(out))) > LIMIT and cur:
                out.append(pack(cur, cont=bool(out)))
                cur = [it]
            else:
                cur = trial
        out.append(pack(cur, cont=bool(out)))
        return out

    text = text_or_shell or ""
    if len(text) <= LIMIT:
        return [text]
    out, cur = [], ""
    for line in text.split("\n"):
        add = line if not cur else cur + "\n" + line
        if len(add) > LIMIT and cur:
            out.append(cur)
            cur = line
        else:
            cur = add
    if cur:
        out.append(cur)
    return out or [text[:LIMIT]]


def send(text: str, token: str | None = None, chat: str | None = None, dry: bool = False) -> bool:
    token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = chat if chat is not None else os.environ.get("TELEGRAM_CHAT_ID", "")
    if dry:
        print("----- (dry-run) -----\n" + text)
        return True
    if not token or not chat:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 없음 → 건너뜀")
        return False
    ok_all = True
    for part in chunks(text):
        data = urllib.parse.urlencode({
            "chat_id": chat,
            "text": part,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read().decode())
        except urllib.error.HTTPError as ex:
            j = {
                "ok": False,
                "error_code": ex.code,
                "description": ex.read().decode(errors="replace")[:200],
            }
        except Exception as ex:  # noqa: BLE001
            j = {"ok": False, "description": type(ex).__name__}
        print(
            "telegram:",
            "ok" if j.get("ok") else f"실패 {j.get('error_code')} {j.get('description')}",
            ("message_id=" + str(j["result"]["message_id"])) if j.get("ok") else "",
        )
        ok_all = ok_all and bool(j.get("ok"))
    return ok_all
