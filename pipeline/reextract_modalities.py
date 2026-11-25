"""Re-read approved bills from cached text to list every breast or lung modality the bill names
(diagnostic or supplemental). Uses Claude only; makes no LegiScan calls.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load, save, load_env, CACHE
import classify as C

SYSTEM = """You read U.S. legislation and list imaging modalities. Report only what the bill text explicitly names.

breast: every modality the bill names for the breast examinations it covers, whether under diagnostic \
(follow-up) examinations or supplemental examinations. Allowed values: "diagnostic mammography", "ultrasound", \
"MRI", "contrast-enhanced mammography", "molecular breast imaging". Digital breast tomosynthesis is a form of \
mammography, not a separate modality; do not list it. Do not count a modality that appears only inside the \
definition of another (for example "intravenous contrast" within an MRI definition). In a long bill, consider \
only the breast imaging coverage provisions.
lung: modalities named for lung cancer screening follow-up. Allowed values: "CT", "PET". Low-dose CT used only \
for the initial screening does not count unless CT is also named for follow-up or diagnostic imaging.
Use an empty list when none is named."""
SCHEMA = {"type": "object", "properties": {
    "breast": {"type": "array", "items": {"type": "string"}},
    "lung": {"type": "array", "items": {"type": "string"}}},
    "required": ["breast", "lung"], "additionalProperties": False}


def main():
    load_env()
    import anthropic
    client = anthropic.Anthropic()
    queue = load("review_queue.json", {})
    usage, changed, n = {"input": 0, "output": 0}, [], 0
    for bid, q in queue.items():
        if q.get("decision") != "approve":
            continue
        p = CACHE / f"text_{q.get('text_doc_id')}.txt"
        if not p.exists():
            print(f"  no cached text: {q['state']} {q['number']}")
            continue
        text, excerpt = C.relevant_text(p.read_text())
        resp = client.beta.messages.create(
            model=C.CONFIRM_MODEL, max_tokens=1500, system=SYSTEM,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            messages=[{"role": "user", "content": f"State: {q['state']}  Bill: {q['number']}  Title: {q['title']}\n"
                       f"<bill_text>\n{text}\n</bill_text>\n\nList the modalities."}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}})
        usage["input"] += resp.usage.input_tokens
        usage["output"] += resp.usage.output_tokens
        if resp.stop_reason in ("refusal", "max_tokens"):
            print(f"  ! {q['state']} {q['number']}: {resp.stop_reason}")
            continue
        out = json.loads(next(b.text for b in resp.content if b.type == "text"))
        n += 1
        for o in ("breast", "lung"):
            c = q["classification"][o]
            if c["verdict"] == "exclude":
                continue
            old = list(c["modalities"]) + list((q.get("modalities_override") or {}).get(o, []))
            merged = old + [m for m in out[o] if m.lower() not in {x.lower() for x in old}]
            if len(merged) > len(c["modalities"]):
                changed.append(f"{q['state']} {q['number']} {o}: {c['modalities']} -> {merged}")
            c["modalities"] = merged
        if n % 15 == 0:
            save("review_queue.json", queue)
    save("review_queue.json", queue)
    print(f"Re-read {n} bills; Claude usage: {usage}")
    print("\n".join(changed))


if __name__ == "__main__":
    main()
