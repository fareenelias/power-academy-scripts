#!/usr/bin/env python3
"""
build_review_xlsx.py — the STANDING Power Academy review workbook.

"For future review sessions I want this review excel output exactly how you did
today, it was helpful to review quickly."  (Fareen)

So this is a re-runnable build, not a one-off. The properties below are the ones that
made the workbook useful; they are load-bearing and must not drift.

  1. SORT AND FILTER BY ACTION TYPE, NOT SEVERITY. The rank is how much attention the
     item deserves, not how bad it looks.
  2. ONE ROW PER FLAGGED CELL, with source file / ticker / page / issue / proposed fix
     in clearly delineated columns, a live deep-link, and a Done? box that drives the
     Summary counts.
  3. NEVER OVER-ASK. This is the single most important property. The re-scan bucket hit
     189 rows before the classifier was fixed; the honest number was 37. It hit 96 on a
     later batch and settled at 18. A review list that over-asks gets ignored wholesale,
     which is worse than one that under-asks. Concretely:
        - a label-free chart is not OCR damage
        - a defect the publisher printed cannot be scanned away
        - two exhibits disagreeing is a judgement call, not a scan
        - a cell recovered by cross-check is not an empty one
  4. THE DEFAULT BRANCH IS A POLICY, NOT A FALLBACK. Anything unrecognised falls through
     to "Eyeball and confirm", NEVER to "Re-scan page". Only an explicit statement that a
     value is GONE ("are lost", "did not survive", "could not be recovered") may route an
     item into the bucket that costs her a scan.
  5. COLLAPSE SYSTEMATIC REPEATS into one row listing every affected period, so answering
     the layout question once resolves them all.
  6. PRINT THE SUPPRESSED-CATEGORY COUNTS at build time, so any suppression is visible
     rather than silent.

Inputs (all read-only):
    guidance_flagged.json                 flagged guidance cells from today's build
    canon_edits.json                      open_questions_do_not_apply + applied edits
    data/precedents.json                  _merge_meta flags / pending / batch status

Usage:
    python3 scripts/build_review_xlsx.py [--out data/PowerAcademy_review_YYYY-MM-DD.xlsx]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import urllib.parse
from collections import Counter, OrderedDict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# THE ACTION-TYPE RANKING. This ordering IS the deliverable's spine: the Review
# sheet sorts by it and the Summary counts in this order. Do not reorder.
# ---------------------------------------------------------------------------
RESCAN = "Re-scan page"
GOVERNING = "Pick the governing exhibit"
COLUMN_ALIGN = "Confirm column alignment"
INFERRED = "Confirm inferred value"
EYEBALL = "Eyeball and confirm"
CROSSCHECK = "Confirm my cross-check — low priority"
CHART = "Chart or graphic — optional"
NOT_FIXABLE = "Not fixable by re-scanning"

ACTION_ORDER = [
    RESCAN,
    GOVERNING,
    COLUMN_ALIGN,
    INFERRED,
    EYEBALL,
    CROSSCHECK,
    CHART,
    NOT_FIXABLE,
]
ACTION_RANK = {a: i for i, a in enumerate(ACTION_ORDER)}

ACTION_MEANING = {
    RESCAN: "The cell is EMPTY and the source text says the value is gone. Only these buy a number she does not already have.",
    GOVERNING: "Two or more equally-supported values are printed. A judgement call about which one governs — not a scan.",
    COLUMN_ALIGN: "The value is legible but which column/period it belongs to is unclear.",
    INFERRED: "A value was inferred from adjacent text on the same page. Confirm or correct the inference.",
    EYEBALL: "Nothing is provably wrong; a human glance settles it. This is also where every unrecognised item lands, by policy.",
    CROSSCHECK: "Already reconciled against a second source. Confirming is optional housekeeping.",
    CHART: "The number lives in a chart or graphic with no printed label. Optional — a scan will not add a label.",
    NOT_FIXABLE: "Re-scanning cannot fix this: the publisher never printed it, or it is redacted, or the answer lives in a document outside the scanned set.",
}

# ---------------------------------------------------------------------------
# Only these phrases may route an item to Re-scan page. An explicit statement
# that the value is GONE. Nothing else. (Property 3 / 4.)
# ---------------------------------------------------------------------------
VALUE_IS_GONE = (
    "are lost",
    "is lost",
    "was lost",
    "did not survive",
    "could not be recovered",
    "not recoverable",
    "unrecoverable",
    "illegible",
    "ocr garbled",
    "scan is truncated",
    "page did not scan",
)

# Phrases that mean a scan cannot help, whatever else the item says.
PUBLISHER_DEFECT = (
    "confidential",
    "redacted",
    "not disclosed",
    "never printed",
    "no headline",
)

CHART_MARKERS = ("chart", "graphic", "unlabelled", "unlabeled", "label-free", "no printed label")

# ---------------------------------------------------------------------------
# Window inference for capital_plan_years rows
# ---------------------------------------------------------------------------
_WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_RE_RANGE = re.compile(r"(20\d\d)\s*E?\s*[-–—]\s*(20\d\d)\s*E?")
_RE_DUR = re.compile(r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)[- ]years?\b", re.I)
_RE_THROUGH = re.compile(r"\bthrough\s+(20\d\d)\b", re.I)
_RE_START = re.compile(r"\b(?:planned for|budget for|for)\s+(20\d\d)\b", re.I)


def infer_window(text: str):
    """Return (window_string, confidence) or (None, None).

    Only reads cues that are physically on the page. Never guesses a plan length.
    """
    m = _RE_RANGE.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}", "full"
    dur = None
    md = _RE_DUR.search(text)
    if md:
        tok = md.group(1).lower()
        dur = _WORD_NUM.get(tok, int(tok) if tok.isdigit() else None)
    end = _RE_THROUGH.search(text)
    end = int(end.group(1)) if end else None
    start = _RE_START.search(text)
    start = int(start.group(1)) if start else None
    if dur and end:
        return f"{end - dur + 1}-{end}", "full"
    if dur and start:
        return f"{start}-{start + dur - 1}", "full"
    if end:
        return f"ends {end}, start year not printed", "partial"
    if dur:
        return f"{dur}-year plan, end year not printed", "partial"
    return None, None


# ---------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------
def classify_guidance(row: dict) -> tuple:
    """Route one flagged guidance cell. Returns (action, proposed_fix, plain_issue)."""
    issue = row.get("issue", "")
    low = issue.lower()
    candidate = row.get("candidate", "")

    # 1. The ONLY route into Re-scan page.
    if any(p in low for p in VALUE_IS_GONE):
        return (
            RESCAN,
            "Re-scan this page and re-run the extractor; the text the value sat in did not survive.",
            issue,
        )

    # 2. A defect the publisher printed cannot be scanned away.
    if any(p in low for p in PUBLISHER_DEFECT):
        return (
            NOT_FIXABLE,
            "The publisher did not print this. Leave empty or source it from a filing — a scan will not add it.",
            issue,
        )

    # 3. A label-free chart is not OCR damage.
    if any(p in low for p in CHART_MARKERS):
        return (
            CHART,
            "Read the value off the chart if you want it. Optional — re-scanning will not add a label.",
            issue,
        )

    # 4. Competing equally-supported values on the page: a judgement call, not a scan.
    if "equally-supported" in low or "equally supported" in low:
        ranges = re.findall(r"\$[\d.,]+\s*-\s*\$[\d.,]+", issue)
        n = len(ranges)
        fix = (
            "Tell me which of these is the guidance-year range and I will write it: "
            + "; ".join(ranges)
            if ranges
            else "Tell me which printed range is the guidance-year range and I will write it."
        )
        plain = (
            f"The slide prints {n or 'several'} equally-supported ranges side by side and the "
            "column layout does not say which one is the guidance year, so no value was written."
        )
        if row.get("affected_periods"):
            plain += (
                f" The SAME slide layout appears in all {len(row['affected_periods'])} of the "
                "periods listed in 'Also applies to' — answer once and the rule applies to all of them."
            )
        return GOVERNING, fix, plain

    # 5. A total is printed but its plan window is not printed beside it.
    if "does not print the plan window" in low:
        window, conf = infer_window(candidate)
        if window and conf == "full":
            return (
                INFERRED,
                f"Same page reads the window as {window}. Confirm and I will write it.",
                "The plan total is printed but the slide does not print the plan window beside it. "
                f"The window is derivable from the surrounding sentence on the same page ({window}).",
            )
        if window:
            return (
                INFERRED,
                f"Same page gives only a partial window ({window}). Confirm the missing end of it.",
                "The plan total is printed but the slide does not print the full plan window beside it; "
                f"only part of it is derivable from the same page ({window}).",
            )
        return (
            EYEBALL,
            "No window cue anywhere on this page. Glance at the deck and tell me the window, or leave the level uncomparable.",
            "The plan total is printed but neither the slide nor the surrounding text on the page gives the plan window, "
            "so the level cannot be compared across vintages.",
        )

    # 6. DEFAULT BRANCH = POLICY. Unrecognised lands here, never in Re-scan page.
    return (
        EYEBALL,
        "Unrecognised flag shape — a glance at the page settles it. (Routed here by the default policy, not by a rule.)",
        issue,
    )


def classify_open_question(q: dict) -> tuple:
    """Route one canon_edits open question."""
    text = " ".join(str(q.get(k, "")) for k in ("question", "evidence", "why_not_auto_applied")).lower()
    conf = (q.get("confidence") or "").lower()

    # A stored value contradicting another stored value is a judgement call.
    if "contradiction" in text or "which is right" in text:
        return (
            GOVERNING,
            "Two stored values disagree and no document in the repo settles it. Tell me which one governs.",
        )
    # Already corroborated by a second source; confirming is housekeeping.
    if conf == "high":
        return (
            CROSSCHECK,
            "Cross-checked against a second source and it holds. Say yes and I will clear the stale flag.",
        )
    return (
        EYEBALL,
        "A judgement the user has not made yet. Read the evidence column and tell me which way to go.",
    )


def classify_deal_flag(flag: str, resolved: list) -> tuple:
    """Route one precedents.json deal flag. Returns (action_or_None, proposed_fix).

    action None means the item is RESOLVED and belongs on the Resolved sheet, not in
    the review list. 'A cell recovered by cross-check is not an empty one.'
    """
    low = (flag or "").lower()
    has_unresolved = "unresolved" in low

    if not has_unresolved and resolved and (
        low.startswith("resolved")
        or "snip confirms" in low
        or "confirmed" in low
    ):
        return None, "Already reconciled — see the Resolved sheet."

    # An explicit internal contradiction is the actionable part of the flag and outranks
    # everything else on the row — a row can be "confirmed sparse" and still store two
    # values that disagree.
    if has_unresolved:
        return (
            GOVERNING,
            "The row stores one value while its own flag stores another. Tell me which governs.",
        )
    if any(p in low for p in PUBLISHER_DEFECT):
        return (
            NOT_FIXABLE,
            "Terms are not public. Nothing to scan; confirm the remaining factual point if you can.",
        )
    if "still to confirm" in low or "to confirm from the s-4" in low or "confirm from the s-4/proxy" in low:
        return (
            NOT_FIXABLE,
            "The answer is in the S-4 / merger proxy, which is not in the scanned deck set. Needs a filing pull, not a scan.",
        )
    if "cross-ref" in low or "cross-check" in low:
        return (
            CROSSCHECK,
            "Cross-check against the entry named in the flag and confirm they agree.",
        )
    return (
        EYEBALL,
        "A glance at the row settles it. (Default policy branch.)",
    )


# ---------------------------------------------------------------------------
# Row assembly
# ---------------------------------------------------------------------------
def source_file_name(url: str) -> str:
    if not url:
        return ""
    return urllib.parse.unquote(url.rsplit("/", 1)[-1])


def deep_link(url: str, page) -> str:
    if not url:
        return ""
    return f"{url}#page={page}" if page else url


def deal_link(deal: dict) -> str:
    links = deal.get("links") or {}
    for key in ("press_release", "filing", "source_doc", "filing_index", "deck"):
        val = links.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    news = links.get("news")
    if isinstance(news, list) and news and isinstance(news[0], str):
        return news[0]
    return ""


def build_rows(flagged, canon, precedents):
    """Returns (review_rows, resolved_rows, coverage_rows, suppression_log)."""
    review, resolved, coverage = [], [], []
    log = Counter()

    # ---- 1. flagged guidance cells -------------------------------------------------
    collapsed_periods = 0
    for row in flagged:
        action, fix, plain = classify_guidance(row)
        affected = row.get("affected_periods") or []
        if affected:
            collapsed_periods += len(affected) - 1
        review.append(
            {
                "action": action,
                "source_file": source_file_name(row.get("source_url", "")),
                "ticker": row.get("ticker", ""),
                "period": row.get("period", ""),
                "page": row.get("page", ""),
                "field": row.get("field", ""),
                "issue": plain,
                "fix": fix,
                "also_applies_to": "; ".join(affected),
                "periods_covered": len(affected) if affected else 1,
                "link": deep_link(row.get("source_url", ""), row.get("page")),
                "origin": "guidance_flagged.json",
            }
        )
        log["guidance rows in"] += 1
    log["periods folded into a systematic-repeat row"] = collapsed_periods

    # ---- 2. canon_edits open questions ---------------------------------------------
    deals = {d["id"]: d for d in precedents["deals"]}
    # A deal whose own flag is already the subject of an open question must NOT also
    # appear as its own review row. Asking the same question twice is over-asking.
    covered_by_question = {}
    for q in canon.get("open_questions_do_not_apply", []):
        for did in deals:
            if did in (q.get("path") or "") or did in (q.get("question") or ""):
                covered_by_question.setdefault(did, []).append(q.get("id", ""))

    for q in canon.get("open_questions_do_not_apply", []):
        action, fix = classify_open_question(q)
        subjects = sorted({d for d, qs in covered_by_question.items() if q.get("id") in qs})
        review.append(
            {
                "action": action,
                "source_file": q.get("file", "canon_edits.json"),
                "ticker": "",
                "period": "",
                "page": "",
                "field": q.get("path", ""),
                "issue": q.get("question", ""),
                "fix": fix + "  EVIDENCE: " + (q.get("evidence") or "n/a"),
                "also_applies_to": "; ".join(subjects),
                "periods_covered": 1,
                "link": "",
                "origin": f"canon_edits.json :: {q.get('id','')}",
            }
        )
        log["canon open questions in"] += 1

    # ---- 3. precedents deals flagged for a human decision ---------------------------
    for did in precedents["_merge_meta"].get("flagged_for_review", []):
        deal = deals.get(did)
        if deal is None:
            log["flagged deal ids that no longer exist (dropped)"] += 1
            continue
        if did in covered_by_question:
            log["precedent flags folded into an open question (same ask)"] += 1
            continue
        flag = deal.get("_flag", "")
        res = deal.get("_resolved") or []
        action, fix = classify_deal_flag(flag, res)
        if action is None:
            resolved.append(
                {
                    "what": f"{did} — {deal.get('target','')} / {deal.get('acquirer','')}",
                    "how": "; ".join(res) if res else flag,
                    "source": "data/precedents.json deals[]._resolved",
                    "why_not_in_review": "Recovered by snip or cross-check — a recovered cell is not an empty one, so it is not asked about again.",
                }
            )
            log["precedent flags suppressed from Review (already reconciled)"] += 1
            continue
        review.append(
            {
                "action": action,
                "source_file": "data/precedents.json",
                "ticker": deal.get("target_ticker") or deal.get("acquirer_ticker") or "",
                "period": (deal.get("announced") or "")[:7],
                "page": "",
                "field": f"deals[{did}]",
                "issue": flag,
                "fix": fix,
                "also_applies_to": "",
                "periods_covered": 1,
                "link": deal_link(deal),
                "origin": f"precedents.json :: {did}",
            }
        )
        log["precedent flags in"] += 1

    # ---- 4. coverage gaps: things review cannot fix because the data is not there ----
    mm = precedents["_merge_meta"]
    for did in mm.get("advisors_pending", []):
        deal = deals.get(did)
        if not deal:
            continue
        coverage.append(
            {
                "what": did,
                "detail": f"{deal.get('target','')} / {deal.get('acquirer','')} ({deal.get('announced','')}) — no financial adviser named",
                "why": "Advisers are sourced from releases, 8-K exhibits and law-firm PRs. Older and smaller deals under-report. "
                "ABSENCE IS NOT EVIDENCE OF NO ROLE.",
                "source": "precedents.json _merge_meta.advisors_pending",
            }
        )
    for deal in precedents["deals"]:
        raw = deal.get("raw") or {}
        if raw.get("fv_usd_b") is None and raw.get("fv_usd_m") is None:
            coverage.append(
                {
                    "what": deal["id"],
                    "detail": f"{deal.get('target','')} / {deal.get('acquirer','')} ({deal.get('announced','')}) — no enterprise value in the book",
                    "why": "No headline EV was disclosed (fair-market-value process, confidential terms, or minority stake). "
                    "Contributes no EV credit in bank_scorecard.json rather than a guess.",
                    "source": "precedents.json deals[].raw",
                }
            )
    for key, status in (precedents.get("_batch_status") or {}).items():
        if "FLAGGED" in status or "queued" in status:
            coverage.append(
                {
                    "what": key,
                    "detail": status,
                    "why": "Batch not closed out — rows still awaiting confirmation or not yet ingested.",
                    "source": "precedents.json _batch_status",
                }
            )

    # ---- 5. resolved: what closed since the last session -----------------------------
    for edit in canon.get("edits", []):
        resolved.append(
            {
                "what": f"{edit.get('op','edit')} @ {edit.get('path','')}",
                "how": (edit.get("reason") or edit.get("why") or edit.get("op", ""))[:600]
                + f"  [confidence: {edit.get('confidence','n/a')}]",
                "source": "canon_edits.json edits[]",
                "why_not_in_review": "Applied — no decision left to make.",
            }
        )
    for key, status in (precedents.get("_batch_status") or {}).items():
        if status.startswith("RESOLVED") or status.startswith("COMPLETE"):
            resolved.append(
                {
                    "what": key,
                    "how": status[:600],
                    "source": "precedents.json _batch_status",
                    "why_not_in_review": "Batch closed.",
                }
            )
    return review, resolved, coverage, log


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------
FONT = "Arial"
HDR_FILL = PatternFill("solid", fgColor="1F3B57")
HDR_FONT = Font(name=FONT, bold=True, color="FFFFFF", size=10)
BODY = Font(name=FONT, size=10)
BOLD = Font(name=FONT, size=10, bold=True)
TITLE = Font(name=FONT, size=13, bold=True, color="1F3B57")
LINK = Font(name=FONT, size=10, color="0563C1", underline="single")
WRAP = Alignment(wrap_text=True, vertical="top")
TOP = Alignment(vertical="top")
THIN = Side(style="thin", color="D9D9D9")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def style_header(ws, ncols, row=1):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = ws.cell(row=row + 1, column=1)
    ws.auto_filter.ref = f"A{row}:{get_column_letter(ncols)}{ws.max_row}"


def write_review(wb, rows):
    ws = wb.create_sheet("Review")
    headers = [
        "#", "Action type", "Source file", "Ticker", "Period", "Page", "Field",
        "The issue", "The proposed fix", "Also applies to", "Periods covered",
        "Open the page", "Your answer", "Done?", "Where it came from",
    ]
    ws.append(headers)
    rows = sorted(
        rows,
        # within an action type: deck-page rows first (they have a ticker and a link),
        # then the book-level decisions, so the cheap clickable work is at the top
        key=lambda r: (ACTION_RANK[r["action"]], r["ticker"] == "", r["ticker"], r["period"], str(r["page"])),
    )
    for i, r in enumerate(rows, start=1):
        ws.append([
            i, r["action"], r["source_file"], r["ticker"], r["period"], r["page"],
            r["field"], r["issue"], r["fix"], r["also_applies_to"],
            r["periods_covered"], "", "", "", r["origin"],
        ])
        rr = ws.max_row
        if r["link"]:
            c = ws.cell(row=rr, column=12)
            c.value = "Open the page"
            c.hyperlink = r["link"]
            c.font = LINK
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=rr, column=col)
            if cell.font is not LINK:
                cell.font = BODY
            cell.alignment = WRAP if col in (7, 8, 9, 10, 15) else TOP
            cell.border = BOX
    widths = [5, 30, 40, 8, 11, 6, 22, 62, 62, 34, 9, 15, 26, 8, 30]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    style_header(ws, len(headers))
    if ws.max_row > 1:
        dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"N2:N{ws.max_row}")
    return ws, rows


def write_summary(wb, review_rows, log, counts_by_action, meta):
    ws = wb.create_sheet("Summary", 0)
    ws["A1"] = "Power Academy — review workbook"
    ws["A1"].font = TITLE
    ws["A2"] = meta["subtitle"]
    ws["A2"].font = Font(name=FONT, size=10, italic=True)
    n = len(review_rows)

    r = 4
    ws.cell(row=r, column=1, value="Work by Action type — sorted by how much attention the item deserves").font = BOLD
    r += 1
    for j, h in enumerate(["Action type", "Rows", "Done", "Left", "Periods covered", "What it means"], start=1):
        ws.cell(row=r, column=j, value=h)
    style_header(ws, 6, row=r)
    ws.auto_filter.ref = None
    hdr = r
    first = r + 1
    for a in ACTION_ORDER:
        r += 1
        ws.cell(row=r, column=1, value=a)
        ws.cell(row=r, column=2, value=f'=COUNTIF(Review!$B$2:$B${n+1},$A{r})')
        ws.cell(row=r, column=3, value=f'=COUNTIFS(Review!$B$2:$B${n+1},$A{r},Review!$N$2:$N${n+1},"Yes")')
        ws.cell(row=r, column=4, value=f"=B{r}-C{r}")
        ws.cell(row=r, column=5, value=f'=SUMIF(Review!$B$2:$B${n+1},$A{r},Review!$K$2:$K${n+1})')
        ws.cell(row=r, column=6, value=ACTION_MEANING[a])
    last = r
    r += 1
    ws.cell(row=r, column=1, value="TOTAL").font = BOLD
    for col in (2, 3, 4, 5):
        c = ws.cell(row=r, column=col, value=f"=SUM({get_column_letter(col)}{first}:{get_column_letter(col)}{last})")
        c.font = BOLD
    total_row = r

    for rr in range(first, total_row + 1):
        for col in range(1, 7):
            cell = ws.cell(row=rr, column=col)
            if cell.font is not BOLD:
                cell.font = BODY
            cell.alignment = WRAP if col == 6 else TOP
            cell.border = BOX
    ws.cell(row=first + ACTION_RANK[RESCAN], column=1).fill = PatternFill("solid", fgColor="FFF2CC")

    r = total_row + 2
    ws.cell(row=r, column=1, value="Never over-ask — what was NOT put in front of you, and why").font = BOLD
    r += 1
    for j, h in enumerate(["Category", "Count", "Why it is not a re-scan"], start=1):
        ws.cell(row=r, column=j, value=h)
    style_header(ws, 3, row=r)
    ws.auto_filter.ref = None
    for line in meta["suppression_lines"]:
        r += 1
        for j, v in enumerate(line, start=1):
            c = ws.cell(row=r, column=j, value=v)
            c.font = BODY
            c.alignment = WRAP if j == 3 else TOP
            c.border = BOX

    r += 2
    ws.cell(row=r, column=1, value="How to use this sheet").font = BOLD
    for line in meta["howto"]:
        r += 1
        c = ws.cell(row=r, column=1, value=line)
        c.font = BODY
        c.alignment = WRAP
    r += 2
    ws.cell(row=r, column=1, value="Standing caveats").font = BOLD
    for line in meta["caveats"]:
        r += 1
        c = ws.cell(row=r, column=1, value=line)
        c.font = BODY
        c.alignment = WRAP
    for col, w in zip("ABCDEF", [46, 10, 10, 10, 16, 96]):
        ws.column_dimensions[col].width = w
    return ws


def write_simple(wb, title, headers, rows, widths, wrap_cols):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in rows:
        ws.append(row)
        rr = ws.max_row
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=rr, column=col)
            cell.font = BODY
            cell.alignment = WRAP if col in wrap_cols else TOP
            cell.border = BOX
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    style_header(ws, len(headers))
    return ws


def main() -> int:
    ap = argparse.ArgumentParser()
    today = _dt.date.today()
    ap.add_argument(
        "--out",
        default=os.path.join(REPO, "data", f"PowerAcademy_review_{today.isoformat()}.xlsx"),
    )
    ap.add_argument("--flagged", default=os.path.join(REPO, "guidance_flagged.json"))
    ap.add_argument("--canon", default=os.path.join(REPO, "canon_edits.json"))
    ap.add_argument("--precedents", default=os.path.join(REPO, "data", "precedents.json"))
    args = ap.parse_args()

    flagged = json.load(open(args.flagged, encoding="utf-8"))
    canon = json.load(open(args.canon, encoding="utf-8"))
    precedents = json.load(open(args.precedents, encoding="utf-8"))

    review, resolved, coverage, log = build_rows(flagged, canon, precedents)
    counts = Counter(r["action"] for r in review)
    periods = sum(r["periods_covered"] for r in review)

    # ---- suppression report, printed AND written into the workbook ----------------
    supp = []
    if counts.get(RESCAN, 0) == 0:
        supp.append((
            "Re-scan page",
            "0 rows",
            "No flagged item says a value is GONE. Today's set is guidance LAYOUT ambiguity — "
            "a slide printing two or three equally-supported ranges side by side — which a scan cannot resolve. "
            "Only an explicit 'are lost / did not survive / could not be recovered' routes an item here.",
        ))
    if counts.get(COLUMN_ALIGN, 0) == 0:
        supp.append((
            "Confirm column alignment",
            "0 rows",
            "Every column-layout item in this batch also has competing printed ranges, so it is the same "
            "question as 'which range governs' and is filed once, under Pick the governing exhibit, "
            "rather than twice.",
        ))
    if counts.get(CHART, 0) == 0:
        supp.append((
            "Chart or graphic — optional",
            "0 rows",
            "Nothing in this batch is a label-free chart. A label-free chart is not OCR damage and would "
            "never be a re-scan even if present.",
        ))
    supp.append((
        "Systematic repeats collapsed",
        f"{log['periods folded into a systematic-repeat row']} periods folded",
        "Five slide layouts repeat across many decks (EIX x18, POR x9, AEE/EVRG/PPL x4 each). Each is ONE row "
        "listing every affected period in 'Also applies to' — answer once and the rule applies to all of them.",
    ))
    supp.append((
        "Precedent flags folded into an open question",
        f"{log['precedent flags folded into an open question (same ask)']} rows",
        "Two deal rows (h2o_quadvest_2025, h2o_southcentral_2025) carry flags that the canon open questions "
        "already ask, word for word. They appear once, as the open question, with the deal id in 'Also applies to'. "
        "Asking the same question twice is over-asking.",
    ))
    supp.append((
        "Already reconciled precedent flags",
        f"{log['precedent flags suppressed from Review (already reconciled)']} rows",
        "Deal rows whose flag was already closed by a snip or a cross-check were moved to the Resolved sheet. "
        "A cell recovered by cross-check is not an empty one and is not asked about again.",
    ))

    meta = {
        "subtitle": (
            f"Built {today.isoformat()} by scripts/build_review_xlsx.py  ·  "
            f"{len(review)} rows covering {periods} reporting periods  ·  "
            "sorted and filtered by Action type, not severity"
        ),
        "suppression_lines": supp,
        "howto": [
            "Work top down. The Action type order IS the priority order — the top of the list is where your attention buys the most.",
            "Re-scan page is the only bucket that costs you a scan, and only an item whose value is provably gone is allowed in it. If it is empty, nothing needs scanning.",
            "Pick the governing exhibit: the page prints two or three equally-supported ranges. Write which one governs in 'Your answer'.",
            "'Also applies to' lists every other period sharing that exact slide layout. Answering the row once resolves all of them.",
            "Click 'Open the page' to jump straight to the page in the source PDF.",
            "Set Done? to Yes as you go — the Summary counts update from that column.",
        ],
        "caveats": [
            "Advisers and guidance values are sourced from decks, releases and filings and are not exhaustive; older vintages under-report. Absence is NOT evidence of no value.",
            "A defect the publisher printed cannot be scanned away, and two exhibits disagreeing is a judgement call, not a scan.",
            "This list deliberately under-asks rather than over-asks. Anything unrecognised is filed as 'Eyeball and confirm', never as a re-scan.",
        ],
    }

    wb = Workbook()
    wb.remove(wb.active)
    ws_review, sorted_rows = write_review(wb, review)
    write_summary(wb, sorted_rows, log, counts, meta)
    write_simple(
        wb,
        "Coverage gaps",
        ["Item", "What is missing", "Why it is a gap, not a review item", "Source"],
        [[c["what"], c["detail"], c["why"], c["source"]] for c in coverage],
        [34, 66, 72, 38],
        {2, 3, 4},
    )
    write_simple(
        wb,
        "Resolved",
        ["Item", "How it was resolved", "Source", "Why it is not in Review"],
        [[r["what"], r["how"], r["source"], r["why_not_in_review"]] for r in resolved],
        [40, 78, 34, 52],
        {2, 4},
    )
    wb.move_sheet("Summary", offset=-wb.sheetnames.index("Summary"))
    wb.save(args.out)

    # ---- build-time report ---------------------------------------------------------
    print(f"wrote {args.out}")
    print(f"rows={len(review)}  periods covered={periods}")
    print("row count by Action type (in priority order):")
    for a in ACTION_ORDER:
        print(f"  {counts.get(a,0):3d}  {a}")
    print("suppressed / not asked, and why:")
    for name, count, why in supp:
        print(f"  {name}: {count}")
        print(f"       {why}")
    print("inputs:", dict(log))
    if counts.get(RESCAN, 0) > len(review) * 0.4:
        print(
            "WARNING: more than 40% of rows landed in Re-scan page. The classifier is "
            "probably wrong — check the default branch before shipping."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
