# Project notes for Claude

- Every HTML page in `docs/` must include the LegiScan attribution footer
  (`<footer class="site-foot">…</footer>`, copied from `docs/index.html`). LegiScan data is
  licensed under CC BY 4.0. After adding or editing a page, run
  `python pipeline/check_attribution.py`; GitHub runs the same check on every push to `docs/`.
