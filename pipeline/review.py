"""Review bills waiting for approval.

  python pipeline/review.py                 list bills waiting for review, with the quoted evidence
  python pipeline/review.py approve 2121893 [more ids] [--scope partial|enhancement]
      partial = applies to Medicaid / public plans only; enhancement = strengthens an existing law
  python pipeline/review.py reject 2121893 [more ids]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load, save


def main():
    queue = load("review_queue.json", {})
    args = sys.argv[1:]
    scope = None
    pair = "--companions" in args          # declare the listed bills companions of each other
    if pair:
        args.remove("--companions")
    if "--scope" in args:
        i = args.index("--scope")
        scope = args[i + 1]
        del args[i:i + 2]
    if args and args[0] in ("approve", "reject"):
        for bid in args[1:]:
            if bid not in queue:
                print(f"{bid}: not in the queue")
                continue
            queue[bid]["decision"] = args[0]
            if scope and args[0] == "approve":
                queue[bid]["scope"] = scope
            if pair and args[0] == "approve":
                queue[bid]["companion_key"] = "-".join(sorted(args[1:]))
            queue[bid].pop("flag", None)
            print(f"{args[0]}: {queue[bid]['state']} {queue[bid]['number']}")
        save("review_queue.json", queue)
        print("Now run: python pipeline/update.py && python pipeline/build_site.py")
        return
    pending = [q for q in queue.values() if q.get("decision") == "pending"]
    print(f"{len(pending)} bill(s) waiting for review\n")
    for q in sorted(pending, key=lambda q: (q["state"], q["number"])):
        c = q["classification"]
        print(f"[{q['bill_id']}] {q['state']} {q['number']} - {q['title']}")
        print(f"  status: {q.get('status')} ({q.get('stage')})   official: {q['official_url']}")
        if q.get("flag"):
            print(f"  FLAG: {q['flag']}")
        print(f"  summary: {c.get('summary', '')}")
        for o in ("breast", "lung"):
            if c[o]["verdict"] != "exclude":
                print(f"  {o}: {c[o]['verdict'].upper()} - {c[o]['reason']}")
                for e in c[o]["evidence"]:
                    print(f"     \"{e}\"")
        print()


if __name__ == "__main__":
    main()
