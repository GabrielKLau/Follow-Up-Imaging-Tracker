"""Re-run classification on every queued bill that has not been rejected (after the rules change).

Keeps each reviewer decision; refreshes status and enactment date from LegiScan.
"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import LegiScan, load, save, load_env, tracker_status
from discover import latest_text
import classify as C


def main():
    load_env()
    today = datetime.date.today().isoformat()
    lg = LegiScan()
    queue = load("review_queue.json", {})
    n = 0
    for bid, q in queue.items():
        if q.get("decision") == "reject":
            continue
        b = lg.bill(int(bid))
        q["status"], q["stage"] = tracker_status(b, today)
        q["status_date"] = b.get("status_date") or ""
        txt = latest_text(b)
        if not txt:
            continue
        try:
            out = C.classify({"state": q["state"], "number": q["number"], "title": q["title"]}, lg.text(txt["doc_id"]))
        except Exception as e:
            print(f"  ! {q['state']} {q['number']}: {e}")
            continue
        r = out["result"]
        if r["breast"]["verdict"] == "exclude" and r["lung"]["verdict"] == "exclude":
            q["flag"] = "Under the updated rules the classifier would exclude this: " + r["breast"]["reason"]
        else:
            q["classification"], q["model"], q["text_doc_id"] = r, out["model"], txt["doc_id"]
            q.pop("flag", None)
        n += 1
        if n % 10 == 0:
            save("review_queue.json", queue)
    save("review_queue.json", queue)
    print(f"Reclassified {n} bills; LegiScan calls: {lg.calls}; Claude usage: {C.usage_log}")


if __name__ == "__main__":
    main()
