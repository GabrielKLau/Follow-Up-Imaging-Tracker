"""Add one specific bill by number, using three LegiScan queries (search, bill record, bill text).

Usage: python pipeline/add_bill.py STATE NUMBER YEAR      e.g.  add_bill.py UT HB314 2025
The bill is classified, approved and placed on the dashboard in one step (rebuild the site afterwards).
"""
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import LegiScan, load, save, load_env, tracker_status
from discover import latest_text
from update import entry
import classify as C


def norm(n):
    m = re.match(r"([A-Za-z]+)0*(\d+)", n.replace(" ", ""))
    return (m.group(1).upper(), m.group(2)) if m else (n, "")


def main():
    state, number, year = sys.argv[1].upper(), sys.argv[2], sys.argv[3]
    load_env()
    today = datetime.date.today().isoformat()
    lg = LegiScan()
    query = sys.argv[4] if len(sys.argv) > 4 else '"diagnostic breast" OR "lung cancer screening"'
    hit = next((h for h in lg.search(query, state=state, year=year) if norm(h["bill_number"]) == norm(number)), None)
    if not hit:
        raise SystemExit(f"{state} {number} ({year}) not found by the search; LegiScan calls: {lg.calls}")
    bill = lg.bill(hit["bill_id"])
    txt = latest_text(bill)
    text = lg.text(txt["doc_id"])
    meta = {"state": bill["state"], "number": bill["bill_number"], "title": bill["title"]}
    out = C.classify(meta, text)
    r = out["result"]
    status, stage = tracker_status(bill, today)
    bid = str(bill["bill_id"])
    print(f"{state} {bill['bill_number']}: {status} ({stage}); breast {r['breast']['verdict']}, lung {r['lung']['verdict']}")
    print("  ", r["summary"])
    seen, queue, bills = load("seen.json", {}), load("review_queue.json", {}), load("bills.json", {})
    seen[bid] = {"change_hash": bill["change_hash"], "doc_id": txt["doc_id"], "outcome": "queued"}
    if r["breast"]["verdict"] == "exclude" and r["lung"]["verdict"] == "exclude":
        seen[bid]["outcome"] = "ai_excluded"
        save("seen.json", seen)
        raise SystemExit(f"Classifier excluded it: {r['breast']['reason']} | {r['lung']['reason']}. LegiScan calls: {lg.calls}")
    last = (bill.get("history") or [{}])[-1]
    queue[bid] = {
        "bill_id": bill["bill_id"], **meta, "session": bill["session"].get("session_name", ""),
        "official_url": bill.get("state_link") or "", "legiscan_url": bill.get("url", ""), "checked": today,
        "status": status, "stage": stage,
        "status_date": last.get("date") if status != "pending" else (bill.get("status_date") or ""),
        "text_url": txt.get("state_link") or txt.get("url", ""), "text_doc_id": txt["doc_id"],
        "model": out["model"], "classification": r, "decision": "approve", "found": today,
        "note_internal": "Added by number at the reviewer's request",
    }
    bills[bid], _ = entry(bill, queue[bid], None, today)
    save("seen.json", seen); save("review_queue.json", queue); save("bills.json", bills)
    print(f"Added and approved. LegiScan calls: {lg.calls}; Claude usage: {C.usage_log}")


if __name__ == "__main__":
    main()
