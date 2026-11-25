"""Write review.html: every state with a bill awaiting a decision, read against what the state already has.

Local only (not published). For each bill it proposes a role (primary / secondary), a reach
(commercial plans or public plans only) and the FIPI points it adds, for the reviewer to confirm.
"""
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load, ROOT
from states import STATES
from update import scope_of
import roles as R

e = html.escape
COLORS = {"enacted": "#2f9e62", "pending": "#f4cf45", "died": "#b98a12"}
ROLE = {"primary": "Primary law", "secondary": "Secondary law",
        "would_establish": "Would establish coverage", "would_expand": "Would expand existing law"}
ORDER = {"enacted": 0, "pending": 1, "died": 2}


def dom(d):
    return (f"coverage {d['coverage']}/1 · modality {d['modality']}/2 · "
            f"prior auth ban {d['prior_auth']}/1 · biopsy {d['biopsy']}/1")


def suggestion(q, items, organ_roles, companions):
    """Point out companions (shown as one entry) and bills adding nothing to an existing law."""
    bid = str(q["bill_id"])
    mates = [x["number"] for x in items if str(x["bill_id"]) in companions.get(bid, [])]
    if mates:
        return (f"Companion of {', '.join(mates)} (other chamber, same session, same title and provisions). "
                f"If approved, they appear together as one entry on the dashboard.")
    if q["decision"] != "pending":
        return ""
    for o in ("breast", "lung"):
        role = organ_roles.get(o, {}).get(bid)
        if not role or role["adds_text"] or role["reach"] == "partial":
            continue
        enacted = [x for x in items if x.get("status") == "enacted" and x is not q
                   and organ_roles[o].get(str(x["bill_id"]))]
        same = next((x for x in enacted if x.get("session") == q.get("session")), None)
        if q.get("status") == "enacted" and role["role"] == "secondary" and same:
            return f"Suggested: reject. Enacted companion of {same['number']} from the same session; adds nothing."
        if q.get("status") != "enacted" and same:
            return f"Suggested: reject. Same-session companion of enacted {same['number']}; redundant."
        if q.get("status") != "enacted" and role["role"] == "would_expand":
            return ("Suggested: reject. The state already has a law and this bill would add no FIPI points "
                    "(keep it only if you want the history of earlier attempts).")
    return ""


def card(q, organ_roles, hint=""):
    c = q["classification"]
    decided = q["decision"] == "approve"
    parts = []
    for o in ("breast", "lung"):
        r = c[o]
        role = organ_roles.get(o, {}).get(str(q["bill_id"]))
        if r["verdict"] == "exclude" and not role:
            continue
        ev = "".join(f"<blockquote>{e(x)}</blockquote>" for x in r["evidence"])
        checks = " · ".join(f"{'✓' if r[k] else '✗'} {label}" for k, label in (
            ("addresses_followup_imaging", "follow-up imaging"), ("mandates_coverage", "mandates coverage"),
            ("prohibits_cost_sharing", "prohibits cost-sharing")))
        rl = ""
        if role:
            adds = ", ".join(role["adds_text"]) or ("no FIPI points (public plans only)" if role["reach"] == "partial" else "nothing new")
            verb = "Adds" if q.get("status") == "enacted" else "Would add"
            rl = (f"<p class='role'><span class='tag {role['role']}'>{ROLE[role['role']]}</span>"
                  f"{'<span class=tag>Partial reach</span>' if role['reach'] == 'partial' else ''}"
                  f" {verb}: <b>{e(adds)}</b> → {o} score {role['score_after']}/5"
                  f"{'; ' + e(role['detail']) if role.get('detail') else ''}</p>")
            if role["modalities"]:
                rl += f"<p class='small'>Modalities read from the bill: {e(', '.join(role['modalities']))}</p>"
        feats = [x for x, on in (("prior authorization prohibited", r["prior_auth_prohibited"]),
                                 ("biopsy covered", r["biopsy_covered"])) if on]
        parts.append(f"<div class='organ'><b>{o.capitalize()}: <span class='v {r['verdict']}'>{r['verdict'].upper()}</span></b>"
                     f"{rl}<div class='checks'>{checks}{' · ' + ' · '.join(feats) if feats else ''}</div>"
                     f"<p>{e(r['reason'])}</p>{ev}</div>")
    links = f"<a href='{e(q['official_url'] or q['legiscan_url'])}' target='_blank'>Official record ↗</a>"
    if q.get("text_url"):
        links += f" · <a href='{e(q['text_url'])}' target='_blank'>Bill text ↗</a>"
    flag = f"<p class='flag'>{e(q['flag'])}</p>" if q.get("flag") else ""
    if hint:
        flag += f"<p class='hint'>{e(hint)}</p>"
    badge = "<span class='done'>✓ approved</span>" if decided else "<span class='todo'>needs decision</span>"
    when = f" on {e(q['status_date'])}" if q.get("status") == "enacted" and q.get("status_date") else ""
    return (f"<article class='{'approved' if decided else ''}'><h3><span class='dot' style='background:{COLORS.get(q.get('status'), '#999')}'></span>"
            f"{e(q['state'])} {e(q['number'])} <code>{q['bill_id']}</code> {badge}</h3>"
            f"<p class='title'>{e(q['title'])}</p>"
            f"<p class='small'>{e(q.get('session', ''))} · <b>{e(q.get('status', ''))}</b>{when}: {e(q.get('stage', ''))} · {links}</p>"
            f"{flag}<p>{e(c.get('summary', ''))}</p>{''.join(parts)}</article>")


def main():
    queue = load("review_queue.json", {})
    base = load("baseline.json", None)
    live = [q for q in queue.values() if q.get("decision") != "reject"]
    by_state = {}
    for q in live:
        by_state.setdefault(q["state"], []).append(q)
    todo_states = sorted((s for s, items in by_state.items() if any(q["decision"] == "pending" for q in items)),
                         key=lambda s: (s == "US", s))
    n_pending = sum(q["decision"] == "pending" for q in live)
    body, changes = "", []
    for ab in todo_states:
        items = sorted(by_state[ab], key=lambda q: (ORDER.get(q.get("status"), 3), q.get("status_date") or "", q["number"]))
        pseudo = [{"id": str(q["bill_id"]), "number": q["number"], "status": q.get("status"),
                   "session": q.get("session", ""), "title": q.get("title", ""),
                   "companion_key": q.get("companion_key"), "modalities_override": q.get("modalities_override"),
                   "organs_override": q.get("organs_override"),
                   "status_date": q.get("status_date") or "", "scope": scope_of(q),
                   "classification": q["classification"]} for q in items]
        organ_roles, head, companions = {}, "", {}
        if ab != "US":
            s = base["states"][ab]
            for o in ("breast", "lung"):
                study = dict(s[o]["domains"]) if s[o]["qualifies"] else dict(R.ZERO)
                entries, lead_of = R.collapse(pseudo)
                res = R.compute(o, study, entries, base["as_of"],
                                [m for m, v in s[o]["modalities"].items() if v] if s[o]["qualifies"] else ())
                organ_roles[o] = {i: res["roles"][lead] for i, lead in lead_of.items() if lead in res["roles"]}
                for en in entries:
                    for m in en["members"]:
                        companions[m] = [x for x in en["members"] if x != m]
                if not res["roles"] and not s[o]["qualifies"]:
                    continue
                now, after = sum(study.values()), sum(res["domains"].values())
                law = "law in force (study)" if s[o]["qualifies"] else "no law in the study"
                head += (f"<p class='small'><b>{o.capitalize()}:</b> {law}; study score {now}/5 ({dom(study)})"
                         f"{f' → <b>{after}/5 if the enacted bills below are approved</b>' if after != now else ''}</p>")
                if after != now or (not s[o]["qualifies"] and any(r["role"] == "primary" for r in res["roles"].values())):
                    changes.append(f"{STATES[ab]} {o}: {now} → {after}")
        name = "Federal" if ab == "US" else STATES.get(ab, ab)
        body += f"<h2>{e(name)}</h2><div class='statehead'>{head}</div>" + "".join(card(q, organ_roles, suggestion(q, items, organ_roles, companions) if ab != "US" else "") for q in items)
    summary = "".join(f"<li>{e(c)}</li>" for c in changes) or "<li>none</li>"
    page = f"""<!doctype html><meta charset=utf-8><title>Review queue</title>
<style>
body{{font:15px/1.5 -apple-system,Segoe UI,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#18202b;background:#f6f7f9}}
article{{background:#fff;border:1px solid #e2e6ec;border-radius:10px;padding:12px 16px;margin:10px 0}}
article.approved{{opacity:.72}}
h2{{margin:38px 0 4px}} h3{{margin:0;font-size:17px}}
.statehead{{background:#eef1f5;border-radius:8px;padding:6px 12px;margin-bottom:8px}}
code{{font-size:12px;color:#6f7a8a;margin-left:8px}} .title{{margin:2px 0;font-weight:600}}
.small{{font-size:13px;color:#4a5565;margin:4px 0}} .checks{{font-size:13px;color:#4a5565}}
.organ{{border-top:1px solid #e2e6ec;margin-top:8px;padding-top:8px}} .role{{margin:6px 0}}
blockquote{{margin:6px 0;padding:4px 10px;border-left:3px solid #d5dae2;color:#4a5565;font-size:13px}}
.dot{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:8px}}
.tag{{font-size:12px;border-radius:5px;padding:2px 7px;background:#e2e6ec;margin-right:6px;font-weight:600}}
.tag.primary{{background:#2f9e62;color:#fff}} .tag.secondary{{background:#cdeeda;color:#14532d}}
.tag.would_establish,.tag.would_expand{{background:#f4cf45}}
.todo{{font-size:12px;background:#fde8e6;color:#b3261e;border-radius:5px;padding:2px 7px;margin-left:8px}}
.done{{font-size:12px;background:#e3f4ea;color:#1d7a48;border-radius:5px;padding:2px 7px;margin-left:8px}}
.hint{{color:#1f5fbf;font-weight:600}} .v.include{{color:#1d7a48}} .v.uncertain{{color:#9a6a00}} .v.exclude{{color:#6f7a8a}} .flag{{color:#b3261e;font-weight:600}}
</style>
<h1>Review queue — {n_pending} bills need a decision</h1>
<p>Bills are grouped by state and read against what the state already has. For each bill, confirm three things:
the <b>role</b> (primary law = the earliest enacted law establishing no-cost-sharing coverage; secondary = any later
one), the <b>reach</b> (commercial plans, or public plans only) and the <b>FIPI points it adds</b>. Faded cards are
already approved and shown for context. The square shows legislative status: green enacted, yellow pending,
dark yellow died. The grey number is the id to use when approving or rejecting.</p>
<div class='statehead'><b>Score or colour changes if every enacted bill here is approved:</b><ul>{summary}</ul></div>
{body}"""
    (ROOT / "review.html").write_text(page)
    print(f"review.html written: {n_pending} need a decision across {len(todo_states)} states/federal")
    print("Would change:", "; ".join(changes) or "nothing")


if __name__ == "__main__":
    main()
