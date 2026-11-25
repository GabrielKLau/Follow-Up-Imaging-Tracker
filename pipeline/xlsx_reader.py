"""Minimal .xlsx reader using only the standard library."""
import re
import zipfile
import xml.etree.ElementTree as ET

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def read_workbook(path):
    """Return {sheet_name: {row_number: {column_letters: text}}}."""
    z = zipfile.ZipFile(path)
    names = z.namelist()
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{{{M}}}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{M}}}t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for s in wb.find(f"{{{M}}}sheets"):
        target = rels[s.get(f"{{{R}}}id")].lstrip("/")
        p = target if target.startswith("xl/") else "xl/" + target
        root = ET.fromstring(z.read(p))
        rows = {}
        for row in root.iter(f"{{{M}}}row"):
            for c in row.findall(f"{{{M}}}c"):
                v = c.find(f"{{{M}}}v")
                t = c.get("t")
                val = ""
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{{{M}}}t"))
                elif v is not None:
                    val = v.text or ""
                if val != "":
                    col, num = re.match(r"([A-Z]+)(\d+)", c.get("r")).groups()
                    rows.setdefault(int(num), {})[col] = val
        out[s.get("name")] = rows
    return out
