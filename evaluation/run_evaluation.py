import json
from pathlib import Path
from src.services.ai_service import AIService, generate_recycling_response

TEST_CASES_PATH = Path(__file__).resolve().parent / "test_cases.json"


def load_test_cases() -> list[dict]:
    """Loads the evaluation dataset (the answer key + metadata for each test case)."""
    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_test_cases(test_cases: list[dict]) -> None:
    """Writes actual_result and status back into test_cases.json, in place."""
    with open(TEST_CASES_PATH, "w", encoding="utf-8") as f:
        json.dump(test_cases, f, indent=2)


def run_case(case: dict, service: AIService) -> None:
    """
    Runs one test case through WasteBuddy and fills in its actual_result + status.

    Grading rules:
    - A failure_case with blank/whitespace-only input is graded automatically
      against the expected friendly validation message (no model call needed --
      this checks the same input-guard the UI relies on).
    - A case with an expected_marker (a short phrase that must appear in the
      full formatted response, case-insensitive) is graded automatically
      against that phrase -- used for cases like the off-topic redirect,
      where the response is a formatted string rather than a structured
      RecyclingResponse.
    - A successful_case or difficult_case that has an expected_category is
      graded automatically: pass if WasteBuddy's real disposal_category
      matches exactly, fail otherwise.
    - Anything else (the genuinely ambiguous/subjective cases) is left as
      'partial' -- it ran without crashing, but needs a human to read
      actual_result and judge whether the behavior is acceptable. Not
      everything can be graded by a script.
    """
    input_text = case["input"]
    expected_category = case.get("expected_category")
    expected_marker = case.get("expected_marker")

    try:
        if case["category"] == "failure_case" and not input_text.strip():
            actual = generate_recycling_response(input_text, service=service)
            case["actual_result"] = actual
            case["status"] = "pass" if "please describe the item" in actual.lower() else "fail"
            return

        if expected_marker is not None:
            actual = generate_recycling_response(input_text, service=service)
            case["actual_result"] = actual
            case["status"] = "pass" if expected_marker.lower() in actual.lower() else "fail"
            return

        response = service.process_recycling_query(input_text)
        case["actual_result"] = (
            f"Item: {response.identified_item} | "
            f"Disposal category: {response.disposal_category} | "
            f"Recycled into: {response.recycled_into}"
        )

        if expected_category is not None:
            case["status"] = "pass" if response.disposal_category == expected_category else "fail"
        else:
            case["status"] = "partial"

    except Exception as err:
        case["actual_result"] = f"[Crashed] {err}"
        case["status"] = "fail"


def run_evaluation() -> None:
    """Runs every test case, prints progress, and writes results back to test_cases.json."""
    test_cases = load_test_cases()
    service = AIService()

    for case in test_cases:
        run_case(case, service)
        print(f"[{case['status'].upper()}] {case['id']} ({case['category']}): {case['input']!r}")
        print(f"    -> {case['actual_result']}\n")

    save_test_cases(test_cases)

    total = len(test_cases)
    passed = sum(1 for c in test_cases if c["status"] == "pass")
    failed = sum(1 for c in test_cases if c["status"] == "fail")
    partial = sum(1 for c in test_cases if c["status"] == "partial")

    print(f"Summary: {passed} passed, {failed} failed, {partial} need manual review, out of {total} total.")
    print(f"Results written back into {TEST_CASES_PATH}")


if __name__ == "__main__":
    run_evaluation()
