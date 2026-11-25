"""Primary / secondary roles and FIPI score provenance for one state and one cancer type.

Primary   = the earliest enacted law that establishes no-cost-sharing coverage of follow-up imaging.
Secondary = any later enacted law; it never changes the map colour, only the score, and we record
            which FIPI domains it adds. Pending or dead bills get "would establish" / "would expand".
Reach     = full (commercial plans) or partial (Medicaid / public plans only; earns no FIPI points).
"""
ZERO = {"coverage": 0, "modality": 0, "prior_auth": 0, "biopsy": 0}
DOMAIN_LABEL = {"coverage": "no-cost-sharing coverage", "modality": "modality breadth",
                "prior_auth": "prior authorization ban", "biopsy": "biopsy coverage"}
BREAST_MODS = {"Diagnostic mammography": ("diagnostic mammo",), "Ultrasound": ("ultraso",),
               "MRI": ("mri", "magnetic resonance"), "Contrast-enhanced mammography": ("contrast",),
               "Molecular breast imaging": ("molecular",)}
# Digital breast tomosynthesis (3-D mammography) is a form of mammography, not a separate modality.
LUNG_MODS = {"CT": ("ct", "computed tomography"), "PET": ("pet", "positron")}


def fipi_from_bill(b, organ):
    """Draft FIPI domain scores for a bill from the classifier's extraction, using the study rubric."""
    c = b["classification"][organ]
    # A reviewer can correct the modalities the classifier read from the bill.
    listed = (b.get("modalities_override") or {}).get(organ) or c.get("modalities") or []
    named = " | ".join(listed).lower()
    padded = f" {named.replace('|', ' ').replace(',', ' ').replace('(', ' ').replace(')', ' ')} "
    table = BREAST_MODS if organ == "breast" else LUNG_MODS
    mods = [m for m, keys in table.items()
            if any((f" {k} " in padded) if len(k) <= 3 else (k in named) for k in keys)]
    if organ == "breast":
        modality = 0 if not mods else (2 if len(mods) >= 4 else 1)
    else:
        modality = 2 if len(mods) == 2 else (1 if "CT" in mods else 0)
    d = {"coverage": 1, "modality": modality, "prior_auth": int(bool(c.get("prior_auth_prohibited"))),
         "biopsy": int(bool(c.get("biopsy_covered")))}
    if b.get("scope") == "enhancement":
        d["coverage"] = 0                 # strengthens an existing law; does not itself establish coverage
    return d, mods


def modality_score(organ, mods):
    if organ == "breast":
        return 0 if not mods else (2 if len(mods) >= 4 else 1)
    return 2 if {"CT", "PET"} <= set(mods) else (1 if "CT" in mods else 0)


def describe(adds):
    return [f"+{n} {DOMAIN_LABEL[k]}" for k, n in adds.items()]


def _mod_note(new):
    return f"expands the named modalities to include {', '.join(new)}" if new else ""


def compute(organ, study_domains, bills, as_of="2026-03-01", study_mods=()):
    """bills: dicts with id, number, status, status_date, scope, classification. Returns roles + provenance."""
    study_ok = bool(study_domains["coverage"])
    mine = [b for b in bills if (b["classification"][organ]["verdict"] != "exclude" or b.get("scope") == "enhancement")
            and organ in (b.get("organs_override") or b.get("organs") or (organ,))]
    enacted = sorted((b for b in mine if b["status"] == "enacted"), key=lambda b: (b.get("status_date") or "9999", b["id"]))
    running, roles, timeline = dict(ZERO), {}, []
    has_primary = has_partial = False
    # Default rule: the earliest enacted qualifying bill we can find is the primary law. If the study
    # found a law but no enacted commercial-plan bill is tracked, the establishing bill is unmatched.
    matched = any(b.get("scope", "full") == "full" for b in enacted)
    study_primary = study_ok and not matched
    seen_mods = set()
    if study_primary:
        running, has_primary = dict(study_domains), True
        seen_mods = set(study_mods)
    for b in enacted:
        d, mods = fipi_from_bill(b, organ)
        scope = b.get("scope", "full")
        if scope == "partial":
            role = "secondary" if (has_primary or has_partial or study_ok) else "primary"
            has_partial = True
            adds = {}
        elif scope == "enhancement" or has_primary:
            role = "secondary"
            if not (running["coverage"] or study_ok):
                d = dict(ZERO)            # nothing to strengthen yet
            else:
                # Modality breadth reflects everything the state's laws name together, not one bill alone.
                d["modality"] = max(d["modality"], modality_score(organ, seen_mods | set(mods)))
            adds = {k: d[k] - running[k] for k in d if d[k] > running[k]}
        else:
            role, has_primary = "primary", True
            adds = {k: d[k] - running[k] for k in d if d[k] > running[k]}
        running = {k: max(running[k], running[k] + adds.get(k, 0)) for k in running}
        # A later law can widen the named modalities without crossing a scoring threshold; say so.
        new_mods = [m for m in mods if m not in seen_mods] if role == "secondary" and scope != "partial" else []
        if scope != "partial":
            seen_mods |= set(mods)
        roles[b["id"]] = {"role": role, "reach": "partial" if scope == "partial" else "full", "adds": adds,
                          "adds_text": describe(adds), "score_after": sum(running.values()), "modalities": mods,
                          "detail": _mod_note(new_mods)}
        timeline.append({"id": b["id"], "number": b["number"], "date": b.get("status_date") or "", "role": role,
                         "reach": roles[b["id"]]["reach"], "adds_text": describe(adds),
                         "score_after": sum(running.values()), "detail": _mod_note(new_mods)})
    # Points the study's hand review found that no tracked bill accounts for (older statutes, or extraction gaps).
    gap = {k: study_domains[k] - running[k] for k in running if study_domains[k] > running[k]}
    # Points tracked bills earn beyond the study's hand score: shown so a reviewer can confirm them.
    beyond = {k: running[k] - study_domains[k] for k in running if running[k] > study_domains[k]} if study_ok else {}
    final = {k: max(running[k], study_domains[k]) for k in running}
    for b in mine:
        if b["status"] == "enacted":
            continue
        d, mods = fipi_from_bill(b, organ)
        scope = b.get("scope", "full")
        adds = {} if scope == "partial" else {k: d[k] - final[k] for k in d if d[k] > final[k]}
        established = bool(final["coverage"])
        known = seen_mods | set(study_mods)
        new_mods = [m for m in mods if m not in known] if established and scope != "partial" else []
        roles[b["id"]] = {"role": "would_expand" if established or scope == "enhancement" else "would_establish",
                          "reach": "partial" if scope == "partial" else "full", "adds": adds,
                          "adds_text": describe(adds), "score_after": sum(final.values()) + sum(adds.values()),
                          "modalities": mods, "detail": _mod_note(new_mods)}
    return {"roles": roles, "timeline": timeline, "domains": final, "study_gap": describe(gap),
            "beyond_study": describe(beyond), "has_tracked_primary": has_primary and not study_primary,
            "has_partial": has_partial}


STATUS_RANK = {"enacted": 3, "pending": 2, "died": 1}


def _strength(b):
    return max((sum(fipi_from_bill(b, o)[0].values()) for o in ("breast", "lung")
                if b["classification"][o]["verdict"] != "exclude"), default=0)


def chamber(number):
    c = (number or " ").strip()[0].upper()
    return "S" if c == "S" else ("H" if c in "HA" else "")


def _vector(b):
    return tuple(tuple(sorted(fipi_from_bill(b, o)[0].items())) if b["classification"][o]["verdict"] != "exclude" else None
                 for o in ("breast", "lung"))


def collapse(bills):
    """Pair true companion bills so that neither chamber's bill is dropped.

    Companions = one House bill and one Senate bill from the same session with the same title and the
    same FIPI provisions; they become one entry. Other same-titled bills in that session (same chamber,
    or different provisions) stay separate entries and are linked as "related" through a shared group.
    Returns (entries, lead_of); each entry has "members" (ids) and "group" (shared by related entries).
    """
    groups, forced = {}, {}
    for b in bills:
        if b.get("companion_key"):        # a reviewer declared these companions
            forced.setdefault(b["companion_key"], []).append(b)
            continue
        key = (b.get("session", ""), " ".join((b.get("title") or b["id"]).lower().split()), b.get("scope", "full"))
        groups.setdefault(key, []).append(b)
    entries, lead_of = [], {}
    for fi, members in enumerate(forced.values()):
        members.sort(key=lambda b: (-STATUS_RANK.get(b["status"], 0), -_strength(b), b["id"]))
        lead = dict(members[0])
        lead["members"] = [x["id"] for x in members]
        lead["number"] = " / ".join(x["number"] for x in members)
        lead["group"] = f"forced{fi}"
        dates = [x.get("status_date") for x in members if x["status"] == "enacted" and x.get("status_date")]
        if dates:
            lead["status_date"] = min(dates)
        entries.append(lead)
        for x in members:
            lead_of[x["id"]] = lead["id"]
    for gi, members in enumerate(groups.values()):
        members.sort(key=lambda b: (-STATUS_RANK.get(b["status"], 0), -_strength(b), b["id"]))
        used = set()
        for m in members:
            if m["id"] in used:
                continue
            used.add(m["id"])
            pair = [m]
            mate = next((x for x in members if x["id"] not in used and chamber(x["number"]) and chamber(m["number"])
                         and chamber(x["number"]) != chamber(m["number"]) and _vector(x) == _vector(m)), None)
            if mate:
                used.add(mate["id"])
                pair.append(mate)
            lead = dict(m)
            lead["members"] = [x["id"] for x in pair]
            lead["number"] = " / ".join(x["number"] for x in pair)
            lead["group"] = gi
            dates = [x.get("status_date") for x in pair if x["status"] == "enacted" and x.get("status_date")]
            if dates:
                lead["status_date"] = min(dates)
            entries.append(lead)
            for x in pair:
                lead_of[x["id"]] = lead["id"]
    return entries, lead_of


def difference(a, b, organ):
    """One line on how related bill b differs from bill a for this cancer type."""
    da, db = fipi_from_bill(a, organ)[0], fipi_from_bill(b, organ)[0]
    diffs = [f"{DOMAIN_LABEL[k]} {db[k]} vs {da[k]} here" for k in da if da[k] != db[k]]
    if diffs:
        return "differs in " + ", ".join(diffs)
    same_chamber = chamber(a["number"]) == chamber(b["number"])
    return "same provisions" + (", introduced in the same chamber" if same_chamber else "")
