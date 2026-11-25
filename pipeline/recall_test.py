"""Recall test: can the search + keyword filter re-find laws the study already identified?

Also records each law's official state link in data/baseline_links.json.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import LegiScan, load, save
from discover import QUERIES, latest_text
import classify as C

# Bills identifiable from the study spreadsheet's source links: (state, number, year, organ)
KNOWN = [
    ("AK", "HB285", 2024, "breast"), ("GA", "HB315", 2023, "breast"), ("IA", "HF2489", 2024, "breast"),
    ("MS", "SB2858", 2024, "breast"), ("NH", "HB1296", 2024, "breast"), ("OK", "HB1389", 2025, "breast"),
    ("FL", "SB158", 2025, "breast"), ("IL", "HB4180", 2024, "breast"), ("KY", "HB115", 2024, "breast"),
    ("MA", "H4918", 2024, "breast"), ("OR", "SB1041", 2023, "breast"), ("PA", "SB88", 2025, "breast"),
    ("TX", "SB1065", 2021, "breast"), ("VA", "HB1828", 2025, "breast"),
    ("AR", "HB1316", 2025, "lung"), ("NV", "SB387", 2025, "lung"), ("NY", "A1195", 2025, "lung"),
]


def norm(n):
    m = re.match(r"([A-Za-z]+)0*(\d+)", n.replace(" ", ""))
    return (m.group(1)[0].upper(), m.group(2)) if m else (n, "")


def main():
    lg = LegiScan()
    links = load("baseline_links.json", {})
    report, found = [], 0
    for state, number, year, organ in KNOWN:
        hit, matched_q = None, []
        for q in QUERIES:
            for h in lg.search(q, state=state, year=year):
                if norm(h["bill_number"]) == norm(number):
                    hit = h
                    matched_q.append(q)
                    break
        row = {"state": state, "bill": number, "year": year, "organ": organ, "found_by_search": bool(hit),
               "queries_matched": len(matched_q)}
        if hit:
            b = lg.bill(hit["bill_id"])
            t = latest_text(b)
            ok, why = C.prefilter(lg.text(t["doc_id"])) if t else (False, "no text")
            row.update(passes_keyword_filter=ok, filter_note=why, official_url=b.get("state_link", ""),
                       title=b["title"], bill_id=b["bill_id"])
            if b.get("state_link"):
                links.setdefault(state, {})[organ] = {"url": b["state_link"], "label": f"{b['bill_number']} ({b['session'].get('session_name', year)})"}
            found += ok
        report.append(row)
        print(f"{'OK  ' if hit and row.get('passes_keyword_filter') else 'MISS'} {state} {number} ({year}, {organ}) "
              f"matched {len(matched_q)}/{len(QUERIES)} queries {row.get('filter_note', '')}")
    save("baseline_links.json", links)
    save("recall_report.json", {"found": found, "total": len(KNOWN), "rows": report})
    print(f"Recall: {found}/{len(KNOWN)}; LegiScan calls: {lg.calls}")


if __name__ == "__main__":
    main()
