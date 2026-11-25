"""Shared helpers: paths, JSON storage, .env loading and the LegiScan client."""
import base64
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = ROOT / "cache"
SITE_DATA = ROOT / "docs" / "data"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def load(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def save(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True))


class LegiScan:
    def __init__(self):
        load_env()
        self.key = os.environ.get("LEGISCAN_API_KEY")
        if not self.key:
            raise SystemExit("LEGISCAN_API_KEY is not set (add it to .env)")
        self.calls = 0
        # Monthly budget guard: the free tier allows 10,000 queries a month.
        self.limit = int(os.environ.get("LEGISCAN_MONTHLY_LIMIT", "9000"))
        self.month = time.strftime("%Y-%m")
        self.ledger = load("legiscan_usage.json", {})
        import atexit
        atexit.register(self._flush)

    def _flush(self):
        if self.calls:
            ledger = load("legiscan_usage.json", {})
            ledger[self.month] = ledger.get(self.month, 0) + self.calls - getattr(self, "_flushed", 0)
            self._flushed = self.calls
            save("legiscan_usage.json", ledger)

    def call(self, op, **params):
        used = self.ledger.get(self.month, 0) + self.calls
        if used >= self.limit:
            raise SystemExit(f"LegiScan monthly budget reached ({used}/{self.limit}); stopping until next month.")
        qs = urllib.parse.urlencode({"key": self.key, "op": op, **params})
        for attempt in range(4):
            try:
                req = urllib.request.Request("https://api.legiscan.com/?" + qs,
                                             headers={"User-Agent": "curl/8.7.1", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read())
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        self.calls += 1
        if data.get("status") != "OK":
            raise RuntimeError(f"LegiScan {op} failed: {data.get('alert', data)}")
        return data

    def search(self, query, state="ALL", year=2):
        """Yield every hit for a full-text query, following pagination."""
        page = 1
        while True:
            sr = self.call("getSearch", state=state, query=query, year=year, page=page)["searchresult"]
            for k, v in sr.items():
                if k != "summary":
                    yield v
            if page >= int(sr["summary"].get("page_total", 1) or 1):
                return
            page += 1

    def bill(self, bill_id):
        return self.call("getBill", id=bill_id)["bill"]

    def text(self, doc_id):
        """Return plain text of a bill document, cached on disk by doc_id."""
        CACHE.mkdir(exist_ok=True)
        p = CACHE / f"text_{doc_id}.txt"
        if p.exists():
            return p.read_text()
        t = self.call("getBillText", id=doc_id)["text"]
        text = extract_text(base64.b64decode(t["doc"]), t.get("mime", ""))
        p.write_text(text)
        return text


class _Strip(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("p", "br", "div", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, d):
        if not self.skip:
            self.parts.append(d)


def extract_text(raw, mime):
    if "pdf" in mime or raw[:4] == b"%PDF":
        import logging
        from pypdf import PdfReader
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
    else:
        s = raw.decode("utf-8", errors="replace")
        if "<" in s[:2000]:
            h = _Strip()
            h.feed(s)
            s = "".join(h.parts)
        text = s
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


PROGRESS = {1: "Introduced", 2: "Passed one chamber", 3: "Passed both chambers", 4: "Signed into law",
            5: "Vetoed", 6: "Failed", 7: "Veto overridden", 8: "Chaptered", 9: "Referred to committee",
            10: "Reported favorably from committee", 11: "Reported unfavorably from committee", 12: "Draft"}
CHAMBER = {"H": "House", "S": "Senate", "A": "Assembly", "J": "Joint", "L": "Legislature", "C": "Council"}


# Some states never set LegiScan's "passed" status (for example a bill that becomes law without the
# governor's signature), so the last recorded action is checked as well.
ENACTED_RE = re.compile(
    r"law without (?:the governor's )?signature|became law|chaptered|signed by (?:the )?gov|approved by (?:the )?gov"
    r"|public act|public chapter|act no\.? ?\d|assigned (?:act|chapter)|effective without", re.I)


def is_enacted(bill):
    if int(bill.get("status") or 0) == 4:
        return True
    if any(p.get("event") == 8 for p in bill.get("progress") or []):
        return True
    hist = bill.get("history") or []
    return int(bill.get("status") or 0) in (2, 3) and bool(hist) and bool(ENACTED_RE.search(hist[-1].get("action", "")))


def tracker_status(bill, today):
    """Map a LegiScan bill to enacted / pending / died plus a human-readable stage."""
    st = int(bill.get("status") or 0)
    ended = bool(bill.get("session", {}).get("sine_die"))
    prog = bill.get("progress") or []
    stage = PROGRESS.get(prog[-1]["event"], "Introduced") if prog else "Introduced"
    if is_enacted(bill):
        last = (bill.get("history") or [{}])[-1].get("action", "")
        return "enacted", "Signed into law" if st == 4 else f"Became law ({last.strip().rstrip('.').lower()})"
    if st == 5:
        return "died", "Vetoed"
    if st == 6:
        return "died", "Failed"
    if ended:
        # An enrolled bill can still be awaiting signature after adjournment.
        if st == 3 and (bill.get("status_date") or "") >= _days_ago(today, 60):
            return "pending", "Passed both chambers, awaiting governor"
        return "died", f"Session ended without passage (last stage: {stage.lower()})"
    return "pending", stage


def _days_ago(today, n):
    import datetime
    return (datetime.date.fromisoformat(today) - datetime.timedelta(days=n)).isoformat()
