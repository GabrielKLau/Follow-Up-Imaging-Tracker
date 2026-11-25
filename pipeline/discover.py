"""Find candidate bills: broad search -> keyword filter -> Claude classification -> review queue.

Usage: python pipeline/discover.py [--year 2] [--state ALL] [--limit N]
  --year  2 = current sessions (default), 1 = all years, or a specific year such as 2025.
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import LegiScan, load, save, load_env, tracker_status, is_enacted, ENACTED_RE
import classify as C

COST = '("cost sharing" OR deductible OR copayment OR coinsurance)'
QUERIES = [
    '"diagnostic breast"',
    '"supplemental breast"',
    '"diagnostic mammography" OR "diagnostic mammogram"',
    f'"breast imaging" AND {COST}',
    f'mammography AND "follow-up" AND {COST}',
    '("breast ultrasound" OR "breast magnetic resonance") AND (insurance OR coverage OR "health benefit plan")',
    '(mammography OR mammogram OR breast) AND "diagnostic imaging"',
    '(mammogram OR mammography) AND "no less favorable"',
    f'"lung cancer" AND screening AND {COST}',
    '"lung cancer" AND "follow-up" AND (coverage OR insurance)',
    '("low-dose computed tomography" OR "low dose computed tomography") AND (coverage OR insurance)',
]


def collect_hits(lg, state, year):
    hits = {}
    for q in QUERIES:
        n = 0
        for h in lg.search(q, state=state, year=year):
            hits.setdefault(h["bill_id"], h)
            n += 1
        print(f"  {n:4d} hits  {q}")
    return hits


def latest_text(bill):
    texts = sorted(bill.get("texts") or [], key=lambda t: (t["date"], t["doc_id"]))
    return texts[-1] if texts else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2")
    ap.add_argument("--state", default="ALL", help="ALL, one state, or a comma-separated list")
    ap.add_argument("--enacted-only", action="store_true",
                    help="historical backfill: only read and classify bills that became law")
    ap.add_argument("--limit", type=int, default=0, help="stop after examining N new or changed bills")
    args = ap.parse_args()
    load_env()
    today = datetime.date.today().isoformat()
    lg = LegiScan()
    seen = load("seen.json", {})
    queue = load("review_queue.json", {})
    excluded = load("excluded.json", {})
    use_ai = C.have_key()
    if not use_ai:
        print("ANTHROPIC_API_KEY not set: running search and keyword filter only.")

    hits = {}
    for st in args.state.split(","):
        print(f"Searching (state={st}, year={args.year})")
        hits.update(collect_hits(lg, st.strip(), args.year))
    todo = [h for bid, h in hits.items()
            if seen.get(str(bid), {}).get("change_hash") != h["change_hash"]
            or seen[str(bid)].get("outcome") == "awaiting_ai" and use_ai
            or seen[str(bid)].get("outcome") == "not_enacted"
            and (not args.enacted_only or ENACTED_RE.search(h.get("last_action", "")))]
    print(f"{len(hits)} distinct bills, {len(todo)} new or changed")
    if args.limit:
        todo = todo[:args.limit]

    counts = {}
    for h in todo:
        bid = str(h["bill_id"])
        prev = seen.get(bid, {})
        bill = lg.bill(h["bill_id"])
        meta = {"state": bill["state"], "number": bill["bill_number"], "title": bill["title"]}
        base = {"bill_id": h["bill_id"], **meta, "session": bill["session"].get("session_name", ""),
                "official_url": bill.get("state_link") or "", "legiscan_url": bill.get("url", ""),
                "checked": today}
        txt = latest_text(bill)
        rec = {"change_hash": bill["change_hash"], "doc_id": txt["doc_id"] if txt else None}

        def exclude(stage, reason, extra=None):
            rec["outcome"] = stage
            excluded[bid] = {**base, "stage": stage, "reason": reason, **(extra or {})}
            queue_item = queue.get(bid)
            if queue_item and queue_item.get("decision") == "pending":
                queue.pop(bid)

        if args.enacted_only and not is_enacted(bill):
            rec["outcome"] = "not_enacted"        # skipped by the backfill; a normal run reads it
        elif txt is None:
            rec["outcome"] = "no_text"            # retried when the bill changes
        elif prev.get("doc_id") == rec["doc_id"] and prev.get("outcome") not in (None, "awaiting_ai", "no_text", "not_enacted"):
            rec["outcome"] = prev["outcome"]      # same text already judged; only the status moved
        else:
            try:
                text = lg.text(txt["doc_id"])
            except Exception as e:
                print(f"  ! could not read text for {meta['state']} {meta['number']}: {e}")
                rec["outcome"] = "no_text"
                text = None
            if text is not None:
                ok, why = C.prefilter(text)
                if not ok:
                    exclude("keyword_filter", why)
                elif not use_ai:
                    rec["outcome"] = "awaiting_ai"
                    print(f"  awaiting AI: {meta['state']} {meta['number']} - {meta['title'][:70]}")
                else:
                    try:
                        out = C.classify(meta, text)
                    except Exception as e:
                        print(f"  ! classification failed for {meta['state']} {meta['number']}: {e}")
                        rec["outcome"] = "awaiting_ai"
                        out = None
                    if out:
                        r = out["result"]
                        verdicts = {o: r[o]["verdict"] for o in ("breast", "lung")}
                        if set(verdicts.values()) == {"exclude"}:
                            reason = "; ".join(f"{o}: {r[o]['reason']}" for o in ("breast", "lung"))
                            exclude("ai_excluded", reason, {"model": out["model"], "summary": r["summary"]})
                            prior = queue.get(bid)
                            if prior and prior.get("decision") == "approve":
                                # Text changed on a tracked bill and it no longer qualifies: ask a human.
                                prior.update(decision="pending", flag="Amended text no longer appears to qualify",
                                             classification=r, text_doc_id=rec["doc_id"])
                                queue[bid] = prior
                                excluded.pop(bid, None)
                                rec["outcome"] = "queued"
                        else:
                            rec["outcome"] = "queued"
                            excluded.pop(bid, None)
                            status, stage = tracker_status(bill, today)
                            prior = queue.get(bid, {})
                            queue[bid] = {
                                **base, "status": status, "stage": stage,
                                "status_date": (bill.get("history") or [{}])[-1].get("date") if status == "enacted"
                                and int(bill.get("status") or 0) != 4 else (bill.get("status_date") or ""),
                                "text_url": txt.get("state_link") or txt.get("url", ""),
                                "text_doc_id": rec["doc_id"], "model": out["model"],
                                "classification": r,
                                "decision": prior.get("decision", "pending"),
                                "found": prior.get("found", today),
                            }
                            if prior.get("decision") == "approve" and prior.get("text_doc_id") != rec["doc_id"]:
                                queue[bid]["note"] = "Text amended; reclassified and still qualifies"
                            print(f"  QUEUED {meta['state']} {meta['number']} {verdicts} - {meta['title'][:60]}")
        counts[rec["outcome"]] = counts.get(rec["outcome"], 0) + 1
        seen[bid] = rec
        if sum(counts.values()) % 20 == 0:
            save("seen.json", seen); save("review_queue.json", queue); save("excluded.json", excluded)

    save("seen.json", seen)
    save("review_queue.json", queue)
    save("excluded.json", excluded)
    print("Outcomes:", counts or "nothing new")
    print(f"LegiScan calls: {lg.calls}; Claude usage: {C.usage_log or 'none'}")
    pending = [q for q in queue.values() if q.get("decision") == "pending"]
    print(f"{len(pending)} bill(s) waiting for review in data/review_queue.json")


if __name__ == "__main__":
    main()
