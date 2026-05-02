"""
BugHound Evaluation Harness

Runs the agent on a set of predefined inputs and prints a pass/fail summary.
All tests run offline (no API calls) to keep the harness reproducible.

Usage:
    python eval/evaluate.py
"""

import sys
import os

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bughound_agent import BugHoundAgent
from reliability.risk_assessor import assess_risk

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

results = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    label = f"  [{status}] {name}"
    if detail:
        label += f"  ({detail})"
    print(label)
    results.append(condition)


# ---------------------------------------------------------------------------
# Test inputs
# ---------------------------------------------------------------------------
BARE_EXCEPT = """\
def load_data(path):
    try:
        data = open(path).read()
    except:
        return None
    return data
"""

PRINT_SPAM = """\
def greet(name):
    print("Hello", name)
    print("Welcome!")
    return True
"""

MIXED_ISSUES = """\
# TODO: replace with real implementation
def compute(x, y):
    print("computing...")
    try:
        return x / y
    except:
        return 0
"""

CLEAN_CODE = """\
import logging

def add(a, b):
    logging.info("Adding numbers")
    return a + b
"""

EMPTY_INPUT = ""

# ---------------------------------------------------------------------------
# Section 1: Issue detection (heuristic mode)
# ---------------------------------------------------------------------------
print("\n=== 1. Issue Detection (heuristic mode) ===")

agent = BugHoundAgent(client=None)

result = agent.run(BARE_EXCEPT)
check("bare except detected as Reliability/High",
      any(i["type"] == "Reliability" and i["severity"] == "High" for i in result["issues"]))

result = agent.run(PRINT_SPAM)
check("print statement detected as Code Quality",
      any(i["type"] == "Code Quality" for i in result["issues"]))

result = agent.run(MIXED_ISSUES)
issue_types = {i["type"] for i in result["issues"]}
check("mixed: all three heuristics fire (Reliability, Code Quality, Maintainability)",
      {"Reliability", "Code Quality", "Maintainability"} == issue_types,
      f"got {issue_types}")

result = agent.run(CLEAN_CODE)
check("clean code produces no issues",
      len(result["issues"]) == 0,
      f"got {len(result['issues'])} issue(s)")

result = agent.run(EMPTY_INPUT)
check("empty input handled gracefully (no crash)",
      isinstance(result, dict) and "issues" in result)

# ---------------------------------------------------------------------------
# Section 2: Fix proposal (heuristic mode)
# ---------------------------------------------------------------------------
print("\n=== 2. Fix Proposal (heuristic mode) ===")

agent = BugHoundAgent(client=None)

result = agent.run(BARE_EXCEPT)
check("bare except fix replaces except: with except Exception",
      "except Exception" in result["fixed_code"])

result = agent.run(PRINT_SPAM)
check("print fix introduces logging.info",
      "logging.info(" in result["fixed_code"])
check("print fix adds import logging",
      "import logging" in result["fixed_code"])

result = agent.run(CLEAN_CODE)
check("clean code is returned unchanged",
      result["fixed_code"].strip() == CLEAN_CODE.strip())

# ---------------------------------------------------------------------------
# Section 3: Risk assessment
# ---------------------------------------------------------------------------
print("\n=== 3. Risk Assessment ===")

risk = assess_risk(original_code="print('hi')\n", fixed_code="", issues=[])
check("empty fix is always high risk / no autofix",
      risk["level"] == "high" and risk["should_autofix"] is False)

risk = assess_risk(
    original_code=BARE_EXCEPT,
    fixed_code=BARE_EXCEPT.replace("except:", "except Exception as e:"),
    issues=[{"type": "Reliability", "severity": "High", "msg": "bare except"}],
)
check("high-severity issue keeps score <= 60",
      risk["score"] <= 60,
      f"score={risk['score']}")
check("high-severity issue blocks autofix",
      risk["should_autofix"] is False)

original = "def f():\n    print('hi')\n"
fixed_with_import = "import logging\n\ndef f():\n    logging.info('hi')\n"
risk = assess_risk(
    original_code=original,
    fixed_code=fixed_with_import,
    issues=[{"type": "Code Quality", "severity": "Low", "msg": "print"}],
)
check("new import surfaces in risk reasons",
      any("import" in r.lower() for r in risk["reasons"]))
check("score < 90 when new import added",
      risk["score"] < 90,
      f"score={risk['score']}")

risk = assess_risk(
    original_code="import logging\n\ndef f():\n    logging.info('hi')\n",
    fixed_code="import logging\n\ndef f():\n    logging.info('hi')\n",
    issues=[],
)
check("identical fix with no issues scores 100 and allows autofix",
      risk["score"] == 100 and risk["should_autofix"] is True)

# ---------------------------------------------------------------------------
# Section 4: Fallback behaviour with bad LLM output
# ---------------------------------------------------------------------------
print("\n=== 4. LLM Fallback Reliability ===")


class NonJsonClient:
    def complete(self, system_prompt, user_prompt):
        return "Here are some issues I noticed, but not in JSON."


class EmptyMsgClient:
    def complete(self, system_prompt, user_prompt):
        return '[{"type": "Issue", "severity": "Low", "msg": ""}, {"type": "Issue", "severity": "Low", "msg": "  "}]'


class EmptyFixClient:
    def complete(self, system_prompt, user_prompt):
        if "Return ONLY valid JSON" in system_prompt:
            return '[{"type": "Code Quality", "severity": "Low", "msg": "print found"}]'
        return ""  # fixer returns nothing


agent = BugHoundAgent(client=NonJsonClient())
result = agent.run(PRINT_SPAM)
check("non-JSON LLM output triggers heuristic fallback",
      any("Falling back to heuristics" in e["message"] for e in result["logs"]))
check("heuristic fallback still detects issues after non-JSON LLM",
      len(result["issues"]) > 0)

agent = BugHoundAgent(client=EmptyMsgClient())
result = agent.run(PRINT_SPAM)
check("empty-msg LLM output triggers quality fallback",
      any("empty messages" in e["message"] for e in result["logs"]))

agent = BugHoundAgent(client=EmptyFixClient())
result = agent.run(PRINT_SPAM)
check("empty LLM fix falls back to heuristic fixer",
      any("Falling back to heuristic fixer" in e["message"] for e in result["logs"]))
check("heuristic fixer still produces non-empty fix",
      len(result["fixed_code"].strip()) > 0)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
total = len(results)
passed = sum(results)
failed = total - passed
print(f"\n{'='*45}")
print(f"  Results: {passed}/{total} passed  |  {failed} failed")
print(f"{'='*45}\n")

sys.exit(0 if failed == 0 else 1)
