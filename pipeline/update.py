"""Refresh every approved bill from LegiScan and record what changed (no AI).

Each update carries a link to the official source (state legislature site or congress.gov).
"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import LegiScan, load, save, tracker_status, CHAMBER


def organs(item):
    c = item["classification"]
    forced = item.get("organs")           # a reviewer can override, e.g. ["lung"]
    if forced:
        return forced
    return [o for o in ("breast", "lung") if c[o]["verdict"] in ("include", "uncertain")]


def scope_of(item):
    """full = commercial mandate, partial = public plans only, enhancement = strengthens existing law."""
    if item.get("scope"):                 # reviewer's decision wins
        return item["scope"]
    c = item["classification"]
    scopes = {c[o].get("scope") for o in ("breast", "lung") if c[o]["verdict"] != "exclude"}
    if "commercial_mandate" in scopes or not scopes - {None}:
        return "full"
    return "partial" if "public_program_only" in scopes else "enhancement"


def events_for(bill, prev):
    """Build update entries from structured LegiScan data; ids make them idempotent."""
    bid, link = bill["bill_id"], bill.get("state_link") or bill.get("url")
    ev = []
    for i, h in enumerate(bill.get("history") or []):
        ev.append({"id": f"{bid}-h-{h['date']}-{i}", "date": h["date"], "kind": "action",
                   "text": h["action"].strip(), "chamber": CHAMBER.get(h.get("chamber"), ""), "url": link,
                   "major": bool(h.get("importance"))})
    for v in bill.get("votes") or []:
        result = "passed" if v.get("passed") else "failed"
        ev.append({"id": f"{bid}-v-{v['roll_call_id']}", "date": v["date"], "kind": "vote",
                   "text": f"{CHAMBER.get(v.get('chamber'), '')} vote, {v['desc'].strip()}: "
                           f"{v['yea']}-{v['nay']} ({result})".strip(),
                   "chamber": CHAMBER.get(v.get("chamber"), ""), "url": v.get("state_link") or link,
                   "major": True})
    for t in bill.get("texts") or []:
        ev.append({"id": f"{bid}-t-{t['doc_id']}", "date": t["date"], "kind": "text",
                   "text": f"Bill text published: {t['type']} version", "chamber": "",
                   "url": t.get("state_link") or link, "major": False})
    if prev is not None:
        known = {s["people_id"] for s in prev.get("sponsors_raw", [])}
        for s in bill.get("sponsors") or []:
            if s["people_id"] not in known:
                ev.append({"id": f"{bid}-s-{s['people_id']}", "date": datetime.date.today().isoformat(),
                           "kind": "sponsor", "text": f"Sponsor added: {s.get('role', '')}. {s['name']} ({s.get('party', '')})",
                           "chamber": "", "url": link, "major": False})
    return ev


def entry(b, item, prev, today):
    """Build the tracked-bill record from one LegiScan bill result. Returns (record, number of new updates)."""
    status, stage = tracker_status(b, today)
    old = {e["id"]: e for e in (prev or {}).get("events", [])}
    events = {**{e["id"]: e for e in events_for(b, prev)}, **old}
    if prev and prev["status"] != status:
        print(f"  STATUS {b['state']} {b['bill_number']}: {prev['status']} -> {status}")
    c = item["classification"]
    rec = {
        "bill_id": int(b["bill_id"]), "state": b["state"], "number": b["bill_number"], "title": b["title"],
        "description": b.get("description", ""), "session": b["session"].get("session_name", ""),
        "organs": organs(item), "scope": scope_of(item), "status": status, "stage": stage,
        "status_date": item.get("status_date") or b.get("status_date"),
        "official_url": b.get("state_link") or "", "legiscan_url": b.get("url", ""),
        "text_url": item.get("text_url", ""),
        "committee": (b.get("committee") or {}).get("name", "") if isinstance(b.get("committee"), dict) else "",
        "sponsors": [f"{s.get('role', '')}. {s['name']} ({s.get('party', '')})" for s in b.get("sponsors") or []],
        "sponsors_raw": [{"people_id": s["people_id"]} for s in b.get("sponsors") or []],
        "summary": c.get("summary", ""),
        "classification": {o: {k: c[o][k] for k in ("verdict", "evidence", "modalities",
                                                    "prior_auth_prohibited", "biopsy_covered", "reason")}
                           for o in ("breast", "lung")},
        "events": sorted(events.values(), key=lambda e: (e["date"], e["id"])),
        "last_action": (b.get("history") or [{}])[-1].get("action", ""),
        "last_action_date": (b.get("history") or [{}])[-1].get("date", ""),
        "change_hash": b["change_hash"], "refreshed": today,
    }
    return rec, len(events) - len(old)


def main():
    today = datetime.date.today().isoformat()
    lg = LegiScan()
    queue = load("review_queue.json", {})
    bills = load("bills.json", {})
    approved = {bid: q for bid, q in queue.items() if q.get("decision") == "approve"}
    for bid in list(bills):
        if bid not in approved:
            print(f"  removing {bills[bid]['state']} {bills[bid]['number']} (no longer approved)")
            bills.pop(bid)

    new_events = 0
    for bid, item in approved.items():
        prev = bills.get(bid)
        if prev and "--new-only" in sys.argv:
            continue                       # only fetch newly approved bills (saves LegiScan queries)
        if prev and prev["status"] != "pending" and prev.get("refreshed", "") >= today[:8] + "01":
            continue                       # finished bills are re-checked once a month
        b = lg.bill(int(bid))
        bills[bid], added = entry(b, item, prev, today)
        new_events += added
    save("bills.json", bills)
    print(f"{len(bills)} tracked bills, {new_events} new update(s), LegiScan calls: {lg.calls}")


if __name__ == "__main__":
    main()
