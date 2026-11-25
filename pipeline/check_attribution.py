"""Fail if any page in docs/ is missing the LegiScan CC BY 4.0 footer.

LegiScan data is licensed under CC BY 4.0, so every published page must credit it.
Run: python pipeline/check_attribution.py
"""
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
FOOTER = re.compile(r'<footer class="site-foot">.*?</footer>', re.S)
LINKS = ("https://legiscan.com/legiscan", "https://creativecommons.org/licenses/by/4.0/")


def problems(page: Path) -> list[str]:
    html = page.read_text(encoding="utf-8")
    footer = FOOTER.search(html)
    if not footer:
        return ['missing <footer class="site-foot">']
    block = footer.group(0)
    out = [f"footer missing link {u}" for u in LINKS if f'href="{u}"' not in block]
    if "LegiScan LLC" not in block:
        out.append('footer missing "LegiScan LLC"')
    return out


def main() -> int:
    pages = sorted(DOCS.rglob("*.html"))
    if not pages:
        print(f"No HTML pages found in {DOCS}")
        return 1
    failed = False
    for page in pages:
        for p in problems(page):
            failed = True
            print(f"{page.relative_to(DOCS.parent)}: {p}")
    if failed:
        print("\nEvery page needs the LegiScan attribution footer. Copy it from docs/index.html.")
        return 1
    print(f"LegiScan attribution present on all {len(pages)} pages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
