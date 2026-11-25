"""Convert the study spreadsheet into data/baseline.json (the reviewed starting point)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from xlsx_reader import read_workbook
from states import STATES, abbr_for

ROOT = Path(__file__).resolve().parent.parent
URL_RE = re.compile(r"https?://[^\s<>]+")


def num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def clean_urls(cell):
    urls = []
    for u in URL_RE.findall(cell or ""):
        u = u.split("#:~:text=")[0]
        u = re.sub(r"[?&]utm_source=[^&]*", "", u).rstrip("?&")
        if u not in urls:
            urls.append(u)
    return urls


def main():
    xlsx = next(p for p in ROOT.glob("*.xlsx"))
    wb = read_workbook(xlsx)
    out = {ab: {"abbr": ab, "name": name} for ab, name in STATES.items()}

    for r, c in wb["Combined score sheet"].items():
        if r < 3 or "A" not in c:
            continue
        ab = abbr_for(c["A"])
        out[ab]["fipi"] = {"composite": num(c.get("B")), "breast": num(c.get("C")), "lung": num(c.get("D"))}

    def organ(sheet, key, cols):
        for r, c in wb[sheet].items():
            if r < 2 or "A" not in c:
                continue
            ab = abbr_for(c["A"])
            out[ab][key] = {
                "study_classification": c.get("B", ""),
                "qualifies": num(c.get(cols["coverage"])) == 1,
                "law_text": c.get("C", "").strip(),
                "source_urls": clean_urls(c.get("D", "")),
                "notes": c.get(cols["notes"], "") if cols.get("notes") else "",
                "domains": {
                    "coverage": num(c.get(cols["coverage"])),
                    "modality": num(c.get(cols["modality"])),
                    "prior_auth": num(c.get(cols["pa"])),
                    "biopsy": num(c.get(cols["biopsy"])),
                },
                "modalities": {name: num(c.get(col)) == 1 for name, col in cols["mods"].items()},
            }

    organ("Breast follow up Coverage", "breast", {
        "coverage": "F", "modality": "R", "pa": "M", "biopsy": "N", "notes": "E",
        "mods": {"Diagnostic mammography": "G", "Contrast-enhanced mammography": "H",
                 "Ultrasound": "I", "MRI": "J", "Molecular breast imaging": "K"}})
    organ("Lung Cancer Score", "lung", {
        "coverage": "F", "modality": "L", "pa": "J", "biopsy": "K",
        "mods": {"CT": "G", "PET": "H"}})

    missing = [ab for ab, s in out.items() if not all(k in s for k in ("fipi", "breast", "lung"))]
    if missing:
        raise SystemExit(f"States missing from spreadsheet: {missing}")
    result = {"as_of": "2026-03-01", "source": xlsx.name.strip(), "states": out}
    (ROOT / "data" / "baseline.json").write_text(json.dumps(result, indent=1))
    b = sum(s["breast"]["qualifies"] for s in out.values())
    l = sum(s["lung"]["qualifies"] for s in out.values())
    tot = sum(s["fipi"]["composite"] for s in out.values())
    print(f"breast qualifying: {b}, lung qualifying: {l}, total FIPI points: {tot}, mean {tot/51:.2f}")
    for ab, s in out.items():
        for k in ("breast", "lung"):
            o = s[k]
            said = o["study_classification"].startswith("Mandated")
            if said != o["qualifies"]:
                print(f"  MISMATCH {ab} {k}: classification={o['study_classification']!r} coverage score={o['domains']['coverage']}")
            dsum = sum(o["domains"].values())
            if dsum != s["fipi"][k]:
                print(f"  SCORE MISMATCH {ab} {k}: domains sum {dsum} vs combined sheet {s['fipi'][k]}")


if __name__ == "__main__":
    main()
