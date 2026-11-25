"""Keyword pre-filter (no AI) and two-stage Claude classification against the study criteria."""
import json
import os
import re

FIRST_PASS_MODEL = "claude-haiku-5-5"
CONFIRM_MODEL = "claude-sonnet-5-5"

IMAGING = re.compile(
    r"mammogra|breast (?:imaging|ultrasound|magnetic|mri|examination|cancer)|diagnostic breast|supplemental breast"
    r"|lung cancer|low[- ]dose (?:computed|ct)|computed tomography|\bLDCT\b", re.I)
INSURANCE = re.compile(
    r"cost[- ]sharing|deductible|co-?pay|co-?insurance|health benefit plan|health insurance|health plan|insurer"
    r"|health maintenance organization|policy of (?:accident|health)|health care coverage|carrier", re.I)
MAX_CHARS = 200_000
WINDOW = 4_000


def prefilter(text):
    """Return (passes, reason). A bill must mention both imaging and insurance terms."""
    if not IMAGING.search(text):
        return False, "No breast or lung imaging terms in the bill text"
    if not INSURANCE.search(text):
        return False, "No insurance coverage or cost-sharing terms in the bill text"
    return True, ""


def relevant_text(text):
    """Whole text for normal bills; for very long omnibus bills, only passages around imaging terms."""
    if len(text) <= MAX_CHARS:
        return text, False
    spans = []
    for m in IMAGING.finditer(text):
        a, b = max(0, m.start() - WINDOW), min(len(text), m.end() + WINDOW)
        if spans and a <= spans[-1][1]:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    out = "\n\n[...]\n\n".join(text[a:b] for a, b in spans)
    return out[:MAX_CHARS * 2], True


SYSTEM = """You screen U.S. legislation for a health policy research tracker. Apply the study's \
eligibility criteria exactly, separately for BREAST and for LUNG.

INCLUDE (verdict "include") only if the bill text explicitly requires health insurance coverage of \
follow-up (diagnostic) imaging after an abnormal or suspicious cancer screening finding, AND explicitly \
prohibits patient cost-sharing (deductible, copayment, coinsurance or similar) for that follow-up imaging.

EXCLUDE (verdict "exclude") if the bill:
- does not address follow-up imaging specifically;
- permits cost-sharing for follow-up imaging, or mandates coverage without prohibiting cost-sharing;
- addresses screening only (including expanding screening eligibility) without extending no-cost \
coverage to follow-up imaging;
- primarily concerns outreach, awareness, research, education, appropriations, resolutions, or \
anything other than an insurance coverage mandate.

Guidance:
- Breast: a "diagnostic breast examination" (imaging used to evaluate an abnormality seen or suspected \
from screening) is follow-up imaging. "Supplemental" breast screening alone (extra screening for dense \
breasts or elevated risk with no abnormality) is not clearly follow-up imaging: use "uncertain" unless \
diagnostic examinations are also covered without cost-sharing.
- Parity language counts: a bill requiring cost-sharing or coverage for diagnostic imaging to be "no \
less favorable than" that for the screening exam is "include"; say in the reason that it is parity language.
- Conditional wording counts: a bill that bans cost-sharing for diagnostic breast examinations "if" or \
"when" a plan provides coverage for them, without a standalone "shall cover" clause, is "include"; say \
in the reason that the wording is conditional.
- Judge what the bill changes. If qualifying language appears only as existing law reprinted in a bill \
whose actual amendment concerns something else (a revisory bill, dental rates, counseling benefits), \
"exclude" with the reason "restates existing law". Supplemental screening provisions that do not expand \
follow-up imaging coverage are also "exclude".
- Lung: coverage without cost-sharing of follow-up diagnostic imaging or follow-up services after a \
lung cancer screening counts, even when no modality is named.
- An exception that lets cost-sharing apply only as needed to keep a high-deductible health plan \
HSA-eligible does not defeat inclusion; note it.
- Scope. Set "scope" for each organ that is not "exclude":
  "commercial_mandate": the mandate reaches state-regulated commercial health plans (the usual case).
  "public_program_only": the bill would otherwise qualify but applies only to Medicaid, another public \
program, or a public-employee plan. Use verdict "include" with this scope (a partial mandate).
  "strengthens_existing_law": the bill does not itself mandate no-cost coverage, but strengthens an \
existing follow-up imaging mandate, for example by prohibiting prior authorization, adding image-guided \
biopsy, or adding modalities. Use verdict "include" with this scope.
  Use "none" for an excluded organ.
- Judge only what the text says. Bill titles and summaries can overstate. If the supplied text is an \
excerpt of a long bill, judge the excerpt.
- If you cannot tell from the text, answer "uncertain" rather than guessing. A missed qualifying bill \
is worse than an extra bill sent to human review.
- Every "include" or "uncertain" verdict needs verbatim quotes from the bill as evidence, each under \
60 words. Include the quote or quotes that name the imaging modalities, and name every listed modality \
in the summary. For "exclude", give the reason in one sentence; evidence may be empty.

FIPI fields (fill for any organ that is not "exclude"; otherwise leave empty/false):
- modalities: every imaging modality the bill explicitly names for the breast examinations it covers \
without cost-sharing, whether listed under diagnostic (follow-up) examinations or under supplemental \
examinations in the same law. Do not count a modality that appears only inside the definition of \
another one (for example "intravenous contrast" in an MRI definition). Breast options: diagnostic \
mammography, ultrasound, MRI, contrast-enhanced mammography, molecular breast imaging. Digital breast \
tomosynthesis (3-D mammography) is a form of mammography, not a separate modality. Lung options: CT, PET.
- prior_auth_prohibited: true only if the text explicitly prohibits prior authorization for the \
follow-up imaging.
- biopsy_covered: true if a diagnostic biopsy (image-guided or not) is explicitly covered without \
cost-sharing. Surgery or treatment of a diagnosed cancer does not count."""

_ORGAN = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["include", "exclude", "uncertain"]},
        "addresses_followup_imaging": {"type": "boolean"},
        "mandates_coverage": {"type": "boolean"},
        "prohibits_cost_sharing": {"type": "boolean"},
        "reason": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "modalities": {"type": "array", "items": {"type": "string"}},
        "prior_auth_prohibited": {"type": "boolean"},
        "biopsy_covered": {"type": "boolean"},
        "scope": {"type": "string", "enum": ["commercial_mandate", "public_program_only",
                                             "strengthens_existing_law", "none"]},
    },
    "required": ["verdict", "addresses_followup_imaging", "mandates_coverage", "prohibits_cost_sharing",
                 "reason", "evidence", "modalities", "prior_auth_prohibited", "biopsy_covered", "scope"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "breast": _ORGAN, "lung": _ORGAN},
    "required": ["summary", "breast", "lung"],
    "additionalProperties": False,
}


def have_key():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


_client = None
usage_log = {}


def _ask(model, meta, text, excerpted):
    global _client
    import anthropic
    if _client is None:
        _client = anthropic.Anthropic()
    note = "NOTE: this is an excerpt of a very long bill (passages around imaging terms).\n" if excerpted else ""
    user = (f"State: {meta['state']}\nBill: {meta['number']}\nTitle: {meta['title']}\n{note}\n"
            f"<bill_text>\n{text}\n</bill_text>\n\nClassify this bill for breast and for lung.")
    kwargs = dict(
        model=model, max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if model == CONFIRM_MODEL:
        # If a safety classifier declines, the API re-runs the request on a fallback model.
        resp = _client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    else:
        resp = _client.messages.create(**kwargs)
    u = usage_log.setdefault(model, {"calls": 0, "input": 0, "output": 0})
    u["calls"] += 1
    u["input"] += resp.usage.input_tokens
    u["output"] += resp.usage.output_tokens
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"{model} stopped with {resp.stop_reason} on {meta['state']} {meta['number']}")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def classify(meta, full_text):
    """Return {'result', 'model', 'first_pass'}: cheap model first, stronger model only on possible matches."""
    text, excerpted = relevant_text(full_text)
    first = _ask(FIRST_PASS_MODEL, meta, text, excerpted)
    if first["breast"]["verdict"] == "exclude" and first["lung"]["verdict"] == "exclude":
        return {"result": first, "model": FIRST_PASS_MODEL, "first_pass": None}
    confirmed = _ask(CONFIRM_MODEL, meta, text, excerpted)
    return {"result": confirmed, "model": CONFIRM_MODEL, "first_pass": first}
