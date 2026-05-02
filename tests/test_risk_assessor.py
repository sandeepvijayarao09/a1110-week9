from reliability.risk_assessor import assess_risk


def test_no_fix_is_high_risk():
    risk = assess_risk(
        original_code="print('hi')\n",
        fixed_code="",
        issues=[{"type": "Code Quality", "severity": "Low", "msg": "print"}],
    )
    assert risk["level"] == "high"
    assert risk["should_autofix"] is False
    assert risk["score"] == 0


def test_low_risk_when_minimal_change_and_low_severity():
    original = "import logging\n\ndef add(a, b):\n    return a + b\n"
    fixed = "import logging\n\ndef add(a, b):\n    return a + b\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[{"type": "Code Quality", "severity": "Low", "msg": "minor"}],
    )
    assert risk["level"] in ("low", "medium")  # depends on scoring rules
    assert 0 <= risk["score"] <= 100


def test_high_severity_issue_drives_score_down():
    original = "def f():\n    try:\n        return 1\n    except:\n        return 0\n"
    fixed = "def f():\n    try:\n        return 1\n    except Exception as e:\n        return 0\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[{"type": "Reliability", "severity": "High", "msg": "bare except"}],
    )
    assert risk["score"] <= 60
    assert risk["level"] in ("medium", "high")


def test_missing_return_is_penalized():
    original = "def f(x):\n    return x + 1\n"
    fixed = "def f(x):\n    x + 1\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[],
    )
    assert risk["score"] < 100
    assert any("Return" in r or "return" in r for r in risk["reasons"])


def test_new_import_penalizes_score_and_surfaces_reason():
    # Fix adds 'import logging' that was not in the original.
    # Score: 100 - 5 (low severity) - 10 (1 new import) = 85.
    # The import penalty reduces the score and must appear in reasons.
    original = "def f():\n    print('hi')\n"
    fixed = "import logging\n\ndef f():\n    logging.info('hi')\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[{"type": "Code Quality", "severity": "Low", "msg": "print statement"}],
    )
    assert risk["score"] == 85
    assert any("import" in r.lower() for r in risk["reasons"])


def test_multiple_new_imports_is_high_risk():
    original = "def f():\n    print('hi')\n"
    fixed = "import logging\nimport sys\nimport os\n\ndef f():\n    logging.info('hi')\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[{"type": "Code Quality", "severity": "Low", "msg": "print statement"}],
    )
    # 3 new imports x 10 pts each = 30 pts deducted, plus low severity 5 pts = score 65
    assert risk["score"] <= 65
    assert risk["should_autofix"] is False


def test_autofix_blocked_when_score_between_75_and_80():
    # Score of 75-79 is "low" level but should NOT auto-fix under the stricter policy.
    # one medium (−20) + one new import (−10) = score 70 → blocked.
    original = "def f():\n    print('hi')\n"
    fixed = "import logging\n\ndef f():\n    logging.info('hi')\n"
    risk = assess_risk(
        original_code=original,
        fixed_code=fixed,
        issues=[{"type": "Style", "severity": "Medium", "msg": "use logging"}],
    )
    # score = 100 - 20 (medium) - 10 (1 new import) = 70 → should_autofix False
    assert risk["score"] == 70
    assert risk["should_autofix"] is False


def test_lax_llm_issues_trigger_heuristic_fallback():
    # If all LLM-returned issues have empty msg fields, agent should fall back.
    from bughound_agent import BugHoundAgent

    class EmptyMsgClient:
        def complete(self, system_prompt, user_prompt):
            # Returns JSON with issues that all have blank msg — low quality output.
            return '[{"type": "Issue", "severity": "Low", "msg": "  "}, {"type": "Issue", "severity": "Low", "msg": ""}]'

    agent = BugHoundAgent(client=EmptyMsgClient())
    code = "def f():\n    print('hi')\n"
    result = agent.run(code)

    # Agent must fall back to heuristics and log the quality failure.
    assert any("empty messages" in entry.get("message", "") for entry in result["logs"])
    # Heuristic fallback should still detect the print issue.
    assert any(issue.get("type") == "Code Quality" for issue in result["issues"])
