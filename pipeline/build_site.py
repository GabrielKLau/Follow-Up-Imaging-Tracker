"""Merge the study baseline with approved, tracked bills into docs/data/site.json for the website."""
import datetime
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
from common import load, SITE_DATA
import roles as R

SECONDARY = ("billtrack50.com", "legiscan.com", "justia.com", "fastdemocracy.com", "pluralpolicy.com")
RANK = {"enacted": 5, "partial": 4, "pending": 3, "supplemental": 2, "died": 1, "none": 0}


def link(url, label=None):
    host = urlparse(url).netloc.replace("www.", "")
    return {"url": url, "host": host, "official": not any(host.endswith(s) for s in SECONDARY),
            "label": label or host}


def organ_slot(organ, study, state_bills, as_of, study_mods=()):
    """Status, roles and score provenance for one state and one cancer type."""
    study_domains = dict(study["domains"]) if study["qualifies"] else dict(R.ZERO)
    all_bills = state_bills
    state_bills, lead_of = R.collapse(state_bills)      # companions count once
    res = R.compute(organ, study_domains, state_bills, as_of, study_mods)
    status = "enacted" if study["qualifies"] else "none"
    has_pending = False
    for b in state_bills:
        if b["id"] not in res["roles"]:
            continue
        role = res["roles"][b["id"]]
        if role["reach"] == "partial" and b["status"] != "enacted":
            continue                      # a pending or dead public-plan bill never sets the colour
        if b["status"] == "pending":
            has_pending = True
        if b.get("scope") == "enhancement":
            continue                      # a strengthening bill never sets the colour
        eff = "partial" if role["reach"] == "partial" and b["status"] == "enacted" else b["status"]
        if RANK[eff] > RANK[status]:
            status = eff
    return {"status": status, "has_pending": has_pending, "domains": res["domains"],
            "score": sum(res["domains"].values()), "timeline": res["timeline"],
            "study_gap": res["study_gap"], "beyond_study": res["beyond_study"],
            "has_tracked_primary": res["has_tracked_primary"],
            "bills": sorted((b["id"] for b in state_bills if b["id"] in res["roles"]),
                            key=lambda i: -res["roles"][i]["score_after"]),
            "roles": {b["id"]: res["roles"][lead_of[b["id"]]] for b in all_bills if lead_of[b["id"]] in res["roles"]},
            "companions": {b["id"]: b["members"] for b in state_bills if len(b["members"]) > 1},
            "related": {b["id"]: [{"id": x["id"], "number": x["number"], "status": x["status"],
                                   "score": res["roles"][x["id"]]["score_after"],
                                   "note": R.difference(b, x, organ)}
                                  for x in state_bills if x["group"] == b["group"] and x["id"] != b["id"]
                                  and x["id"] in res["roles"]]
                        for b in state_bills if b["id"] in res["roles"]}}


def main():
    base = load("baseline.json", None)
    bills = load("bills.json", {})
    overrides = load("baseline_links.json", {})
    queue = load("review_queue.json", {})
    # A bill rejected since the last refresh drops off immediately, without a LegiScan call.
    bills = {bid: b for bid, b in bills.items() if queue.get(bid, {}).get("decision", "approve") == "approve"}
    for bid, b in bills.items():
        b["id"] = bid
        for key in ("companion_key", "modalities_override", "organs_override", "note", "scope"):
            if queue.get(bid, {}).get(key):
                b[key] = queue[bid][key]
        if b.get("organs_override"):
            b["organs"] = b["organs_override"]
        if bid in queue:                  # keep the reviewed classification current without a refresh
            b["summary"] = queue[bid]["classification"].get("summary", b.get("summary", ""))
            for o in ("breast", "lung"):
                for key in ("modalities", "evidence"):
                    b["classification"][o][key] = queue[bid]["classification"][o][key]
        if queue.get(bid, {}).get("stage_override"):
            b["stage"] = queue[bid]["stage_override"]
    # Dated corrections layered over the study spreadsheet, which itself is never edited.
    corrections = {(c["state"], c["organ"]): c for c in load("baseline_corrections.json", [])}
    states, updates = {}, []

    for ab, s in base["states"].items():
        st = {"abbr": ab, "name": s["name"], "fipi": s["fipi"]}
        mine = [b for b in bills.values() if b["state"] == ab]
        for organ in ("breast", "lung"):
            o = s[organ]
            fix = corrections.get((ab, organ))
            if fix:
                o = {**o, **fix.get("changes", {})}
            links = [link(u) for u in o["source_urls"]]
            ov = overrides.get(ab, {}).get(organ)
            if ov:
                # An official link has been matched, so third-party links from the sheet are dropped.
                links = [link(ov["url"], ov["label"])] + [l for l in links if l["url"] != ov["url"] and l["official"]]
            links.sort(key=lambda l: not l["official"])
            slot = organ_slot(organ, o, mine, base["as_of"],
                              [m for m, v in o["modalities"].items() if v] if o["qualifies"] else ())
            if slot["timeline"]:
                # A tracked law already links to the official record, so drop third-party links from the sheet.
                links = [l for l in links if l["official"]]
            slot["law"] = {"text": o["law_text"], "links": links, "domains": o["domains"],
                           "modalities": [m for m, v in o["modalities"].items() if v],
                           "notes": o["notes"]} if o["qualifies"] else None
            if fix and fix.get("category") == "supplemental" and RANK[slot["status"]] < RANK["supplemental"]:
                slot["status"] = "supplemental"   # has a supplemental-screening law, but no follow-up mandate
            if fix:
                slot["correction"] = {"label": fix["label"], "reason": fix["reason"], "date": fix["date"],
                                      "links": links, "text": o["law_text"]}
            for lead, members in slot.pop("companions").items():
                bills[lead]["companions"] = members
            for lead, rel in slot.pop("related").items():
                if rel:
                    bills[lead].setdefault("related", {})[organ] = rel
            for bid, role in slot.pop("roles").items():
                bills[bid].setdefault("roles", {})[organ] = role
            st[organ] = slot
        cur = {o: st[o]["score"] for o in ("breast", "lung")}
        st["fipi_current"] = {**cur, "composite": cur["breast"] + cur["lung"]}
        best = max(("breast", "lung"), key=lambda o: RANK[st[o]["status"]])
        st["combined"] = {"status": st[best]["status"],
                          "has_pending": st["breast"]["has_pending"] or st["lung"]["has_pending"]}
        states[ab] = st

    # Federal bills are scored on the same rubric, as the score the bill itself would earn.
    fed_bills = [b for b in bills.values() if b["state"] == "US"]
    federal = []
    for organ in ("breast", "lung"):
        slot = organ_slot(organ, {"qualifies": False, "domains": dict(R.ZERO)}, fed_bills, base["as_of"])
        for lead, members in slot["companions"].items():
            bills[lead]["companions"] = members
        for lead, rel in slot["related"].items():
            if rel:
                bills[lead].setdefault("related", {})[organ] = rel
        for bid, role in slot["roles"].items():
            bills[bid].setdefault("roles", {})[organ] = role
        federal += [i for i in slot["bills"] if i not in federal]
    for bid, b in bills.items():
        for e in b["events"]:
            updates.append({**e, "bill_id": bid, "state": b["state"], "number": b["number"], "organs": b["organs"]})
    updates.sort(key=lambda e: (e["date"], e["id"]), reverse=True)
    public_bills = {bid: {k: v for k, v in b.items() if k not in ("sponsors_raw", "change_hash")}
                    for bid, b in bills.items()}
    counts = {view: {k: sum(1 for s in states.values() if s[view]["status"] == k) for k in RANK}
              for view in ("breast", "lung", "combined")}
    site = {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "baseline_as_of": base["as_of"], "states": states, "bills": public_bills, "federal": federal,
        "updates": updates[:400], "counts": counts,
        "pending_review": sum(1 for q in queue.values() if q.get("decision") == "pending"),
    }
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "site.json").write_text(json.dumps(site, ensure_ascii=False))
    print("site.json written:", counts)
    changed = [(ab, s["fipi"]["composite"], s["fipi_current"]["composite"]) for ab, s in states.items()
               if s["fipi"]["composite"] != s["fipi_current"]["composite"]]
    if changed:
        print("FIPI changed vs study:", ", ".join(f"{ab} {a}->{b}" for ab, a, b in changed))


if __name__ == "__main__":
    main()
