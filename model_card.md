# BugHound Mini Model Card (Reflection)

---

## 1) What is this system?

**Name:** BugHound
**Purpose:** Analyze a Python snippet for reliability and quality issues, propose a minimal fix, evaluate the risk of that fix, and decide whether to apply it automatically or defer to a human reviewer.

**Intended users:** Students learning agentic AI workflows and software reliability concepts. Also useful as a lightweight code review aid in low-stakes projects.

---

## 2) How does it work?

BugHound follows a five-step agentic loop:

1. **PLAN** — The agent logs its intent and sets up the workflow. No analysis occurs here; it is purely a coordination step.
2. **ANALYZE** — If a Gemini client is available, the agent sends the code to the LLM with a structured prompt and expects a JSON array of issues back. If the LLM is unavailable, returns invalid JSON, or returns mostly empty messages, the agent falls back to heuristic rules that check for bare `except:`, `print()` calls, and `TODO` comments.
3. **ACT** — If issues were found, the agent asks the LLM (or heuristic fixer) for a rewritten version of the code that addresses those issues. The heuristic fixer replaces bare `except:` with `except Exception as e:` and swaps `print()` for `logging.info()`.
4. **TEST** — The `assess_risk` function scores the proposed fix from 0–100 and assigns a risk level (low / medium / high) based on issue severity, structural changes, and newly introduced imports.
5. **REFLECT** — If `score >= 80`, the agent marks the fix as safe to auto-apply. Otherwise it recommends human review.

Heuristics are used when: no API key is set, the LLM call raises an exception, the response is not valid JSON, or the JSON contains too many issues with empty `msg` fields.

Gemini is used when: `GEMINI_API_KEY` is present, the response is parseable JSON, and the issues all have non-empty messages.

---

## 3) Inputs and outputs

**Inputs tested:**

- `print_spam.py` — A short function with multiple `print()` calls (heuristic hit).
- `flaky_try_except.py` — A file-reading function with a bare `except:` block (high-severity heuristic hit).
- `mixed_issues.py` — A function combining `TODO`, `print()`, and bare `except:` (all three heuristics triggered).
- `cleanish.py` — A well-written function already using `logging` (no issues expected).
- Empty string — Edge case; no issues, code returned unchanged.

**Outputs observed:**

- *Detected issues:* Code Quality (print), Reliability (bare except), Maintainability (TODO). Gemini also detected division-by-zero risk and missing `with` statement for file I/O — things heuristics missed.
- *Proposed fixes:* Heuristic mode prepended `import logging` and replaced `print(` with `logging.info(`. Gemini mode produced more contextual rewrites that preserved semantics more carefully.
- *Risk reports:* `cleanish.py` scored 95 (auto-fix allowed). `mixed_issues.py` scored 55 due to a high-severity bare-except issue (human review recommended). Fixes that added new imports were penalized an additional 10 pts per import.

---

## 4) Reliability and safety rules

**Rule 1 — High-severity issues reduce score by 40 points**
- *What it checks:* Whether any detected issue is marked `"severity": "High"`.
- *Why it matters:* High-severity issues (e.g., bare `except:` hiding errors) suggest the code is fundamentally fragile. A fix to such code is higher-stakes.
- *False positive:* A `High` severity issue detected by the LLM that is actually a style preference (e.g., "function is too long") would unfairly penalize an otherwise safe fix.
- *False negative:* If the LLM labels a genuinely dangerous issue as `"Medium"`, the rule only deducts 20 points and may still allow auto-fix.

**Rule 2 — Return statements removed reduces score by 30 points**
- *What it checks:* Whether `return` appears in the original but not in the fixed code.
- *Why it matters:* Removing a return statement changes function behavior — callers that rely on a return value would silently receive `None`.
- *False positive:* A function that only had `return None` explicitly, which the fixer removed as redundant, would be flagged even though the behavior is identical.
- *False negative:* If a fix changes `return x` to `return None` (still has "return"), the behavioral regression is not caught.

**Rule 3 — New imports reduce score by 10 points each**
- *What it checks:* Lines starting with `import` or `from` that appear in the fix but not in the original.
- *Why it matters:* Silently introducing new dependencies changes the module's requirements and could fail at import time in constrained environments.
- *False positive:* Adding `import logging` (a stdlib module) is almost always safe, but is still penalized.
- *False negative:* If a fix uses a module already imported elsewhere in the project but not in this snippet, the risk is not captured.

---

## 5) Observed failure modes

**Failure 1 — Over-editing with heuristic fixer on `cleanish.py`**
`cleanish.py` already uses `logging` correctly and has no issues. When forced through the heuristic fixer (by injecting a fake Low-severity issue), the fixer prepended a second `import logging` statement, producing a duplicate import. BugHound reported it as safe to auto-apply. The fix introduced a cosmetic defect in code that needed no changes at all.

**Failure 2 — LLM over-detection on `mixed_issues.py` in Gemini mode**
Gemini returned 7 issues for `mixed_issues.py`, including a warning about "magic number 0 used as default return value" for `return 0` in the except block. This is subjective style feedback, not a reliability issue. The high issue count inflated the risk score calculation and caused the fix to be blocked even though the structural changes were minimal. The LLM did not follow the prompt's guidance to focus only on reliability, maintainability, correctness, and readability in a narrow sense.

---

## 6) Heuristic vs Gemini comparison

| Dimension | Heuristic mode | Gemini mode |
|---|---|---|
| Issue detection | Catches bare `except:`, `print()`, `TODO` — nothing else | Catches all of the above plus division-by-zero, missing `with` for file I/O, and ambiguous exception handling |
| Fix quality | Mechanical: prepend `import logging`, replace `print(` globally | Contextual: rewrites only the affected block, often preserves intent better |
| Consistency | 100% deterministic across runs | Non-deterministic; occasional over-editing or format deviations |
| Risk scorer agreement | Generally aligned — heuristic fixes are narrow so risk stays low | Sometimes misaligned — LLM fixes can introduce new imports, lowering score below expectations |

The risk scorer agreed with intuition most of the time, but had one notable miss: a Gemini fix that rewrote a try/except block to use `with open(...)` (semantically better) was flagged as risky because it removed the explicit `return None` and added new structural lines.

---

## 7) Human-in-the-loop decision

**Scenario:** The user pastes a function that handles money — e.g., `def charge_card(amount, card_id)`. BugHound detects a bare `except:` and proposes replacing it with `except Exception as e: pass`. The risk scorer gives this a score of 55 (medium) due to the high-severity issue, but does not auto-fix.

However, even human review of the diff may miss that the new `except Exception as e: pass` silently swallows payment errors — arguably worse than the original bare `except: return None` which at least surfaced a `None` result to the caller.

**Trigger to add:** If the original code contains specific keywords associated with sensitive operations (`charge`, `payment`, `transfer`, `delete`, `drop`, `password`, `token`, `secret`), the agent should unconditionally block auto-fix regardless of score.

**Where to implement:** In `assess_risk` (risk_assessor.py) as a keyword scan of `original_code`. This keeps it in the reliability layer, separate from the LLM and the UI.

**Message to show:** "BugHound detected potentially sensitive operations in this code. Auto-fix has been disabled. Please review the proposed changes carefully before applying."

---

## 8) Improvement idea

**Better LLM output validation before accepting issues.**

Currently, if the LLM returns valid JSON with all issues having empty `msg` fields, the agent would accept them (and they'd show up as useless blank entries in the UI). The fix added in this activity addresses the majority case (>50% empty), but a more robust version would:

1. Require every accepted issue to have a non-empty `msg` of at least 10 characters.
2. Require `severity` to be exactly one of `"Low"`, `"Medium"`, `"High"` (case-insensitive normalization already exists, but strict validation does not).
3. Cap the maximum number of LLM-returned issues at 8 — if the model returns more, it is likely hallucinating edge cases and the output should be treated with lower trust.

This improves reliability without adding complexity: it is a pure validation filter with no new external dependencies, can be fully tested offline with `MockClient`, and the fallback path already exists and works.
