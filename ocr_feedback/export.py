"""A dataset snapshot: one record per line, every stage beside the truth.

Read-only on its inputs. A snapshot folder is never overwritten.
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone

from . import __version__
from .align import best_match, contains_match


def _texts(outputs) -> list:
    return [line for output in outputs for line in output.lines]


def _chain(profile, stages: dict, anchor: str | None):
    """Walk the non-drop stages from last to first, each matched to the one
    after it. Returns ({stage: text | [text|None] | None}, flags, score)."""
    values, flags, score = {}, {}, None
    for stage in reversed(profile.capture_stages()):
        outputs = stages.get(stage.name) or []
        if anchor is None or not outputs:
            values[stage.name] = None
            continue
        if stage.kind == "reads":
            # The score is how well the *last* captured stage matches the
            # anchor: for a reads-only profile, the best reading.
            last = stage is profile.capture_stages()[-1]
            picked = []
            for output in outputs:
                line, r = best_match(anchor, output.lines, profile)
                if line is None:
                    line, r = contains_match(anchor, output.lines, profile)
                picked.append(line.text if line else None)
                if last:
                    score = r if score is None else max(score, r)
            values[stage.name] = picked
            continue
        candidates = _texts(outputs)
        line, r = best_match(anchor, candidates, profile)
        if line is None:
            line, r2 = contains_match(anchor, candidates, profile)
            if line is not None:
                r = r2
        if score is None:
            score = r
        values[stage.name] = line.text if line else None
        if line is not None:
            if line.meta:
                flags[stage.name] = line.meta
            anchor = line.text
    for stage in profile.drop_stages():
        values.setdefault(stage.name, None)
    ordered = {s.name: values.get(s.name) for s in profile.stages}
    return ordered, flags, score


def _last_select(profile):
    """The stage a pre-capture source text belongs to, or None."""
    if not profile.capture_stages():
        return None
    selects = [s for s in profile.capture_stages() if s.kind == "select"]
    return selects[-1].name if selects else profile.capture_stages()[-1].name


def build_records(profile, truth, reader):
    lines, pages = [], []
    for page in truth.pages():
        stages = reader.latest_stages(page.page_id)
        events = reader.events(page.page_id)
        section = page.meta.get(profile.section_field)
        captured = bool(stages)
        drop_lines = {s.name: _texts(stages.get(s.name) or []) for s in profile.drop_stages()}
        used_drop: set = set()
        first_tag = {}
        edited_refs = set()
        verdict = {}
        for e in events:
            if e.action in ("confirm", "flag", "edit"):
                verdict[e.line_ref] = e.action  # the last of them stands
            if e.action == "retag":
                first_tag.setdefault(e.line_ref, e.before_tag)
            if e.action == "edit":
                edited_refs.add(e.line_ref)

        def base(line_ref, final, outcome, label, tag_final, tag_from):
            return {"line_id": f"{page.page_id}/{line_ref}", "line_ref": line_ref,
                    "page_id": page.page_id, "image": page.image_ref, "section": section,
                    "final": final, "outcome": outcome, "label": label,
                    "tag_first": first_tag.get(line_ref, tag_from), "tag_final": tag_final}

        for final in truth.final_lines(page.page_id):
            added = bool(final.meta.get("added"))
            if added:
                values = {s.name: None for s in profile.stages}
                flags, score = {}, None
                hit = None
                for name, candidates in drop_lines.items():
                    line, _ = best_match(final.text, candidates, profile)
                    if line is not None and id(line) not in used_drop:
                        used_drop.add(id(line))
                        values[name] = line.text
                        hit = line
                        break
                record = base(final.line_ref, final.text, "added", final.status,
                              final.tag, final.tag)
                record.update(stages=values, flags=flags, align_score=score,
                              wrongly_dropped=hit is not None)
                lines.append(record)
                continue
            anchor = final.source_text if final.source_text is not None else final.text
            if captured:
                values, flags, score = _chain(profile, stages, anchor)
            else:
                values = {s.name: None for s in profile.stages}
                flags, score = {}, None
                if final.source_text is not None:
                    target = _last_select(profile)
                    if target is not None:
                        kind = next(s.kind for s in profile.stages if s.name == target)
                        values[target] = ([final.source_text] if kind == "reads"
                                          else final.source_text)
                        score = 1.0
            changed = (final.source_text is not None and final.text != final.source_text) \
                or final.line_ref in edited_refs
            label = final.status
            last = verdict.get(final.line_ref)
            if last == "flag":
                label = "none"
            # an edit after a verdict clears it: the status (edited) stands
            elif last == "confirm" and final.status in ("accepted", "none"):
                label = "confirmed"
            record = base(final.line_ref, final.text, "edited" if changed else "kept",
                          label, final.tag, final.tag)
            record.update(stages=values, flags=flags,
                          align_score=None if score is None else round(score, 4))
            if not captured:
                record["pre_capture"] = True
            lines.append(record)

        first_text = {}
        for e in events:
            first_text.setdefault(e.line_ref, e.before_text)
        for e in events:
            if e.action != "delete":
                continue
            original = first_text[e.line_ref]
            if original is None:
                original = e.before_text
            values, flags, score = (_chain(profile, stages, original) if captured
                                    else ({s.name: None for s in profile.stages}, {}, None))
            record = base(e.line_ref, None, "deleted", "edited", None, e.before_tag)
            record.update(stages=values, flags=flags,
                          align_score=None if score is None else round(score, 4))
            lines.append(record)

        for name, candidates in drop_lines.items():
            for i, line in enumerate(candidates):
                if id(line) in used_drop:
                    continue
                values = {s.name: None for s in profile.stages}
                values[name] = line.text
                record = base(f"{name}-{i}", None, "dropped", "none", None, None)
                record.update(stages=values, flags={name: line.meta} if line.meta else {},
                              align_score=None)
                lines.append(record)

        pages.append({"page_id": page.page_id, "image": page.image_ref, "meta": page.meta,
                      "captured_stages": sorted(stages)})
    return lines, pages


def export_snapshot(profile, truth, reader, out_root: str, label: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    name = f"{profile.system}-{label or now.strftime('%Y-%m-%d')}"
    folder = os.path.join(out_root, name)
    if os.path.exists(folder):
        folder = f"{folder}-{now.strftime('%H%M%S%f')}"
    os.makedirs(folder)
    lines, pages = build_records(profile, truth, reader)
    for filename, rows in (("lines.jsonl", lines), ("pages.jsonl", pages)):
        with open(os.path.join(folder, filename), "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "package_version": __version__, "system": profile.system,
        "profile_hash": profile.source_hash, "exported_at": now.isoformat(timespec="seconds"),
        "counts": {"lines": len(lines), "pages": len(pages),
                   "pages_captured": sum(1 for p in pages if p["captured_stages"]),
                   "by_outcome": dict(Counter(r["outcome"] for r in lines)),
                   "by_label": dict(Counter(r["label"] for r in lines))},
    }
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return folder
