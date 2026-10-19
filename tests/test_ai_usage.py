"""Usage in monthly buckets, and the token and cost budgets that set each call's output cap.
Two processes recording at once lose no increment."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from solidseas.ai.base import Completion
from solidseas.ai.errors import BudgetExceededError, InvalidSettingError
from solidseas.ai.fake import ScriptedProvider
from solidseas.ai.usage import (
    HOLD_SECONDS,
    MIN_OUTPUT_TOKENS,
    Budget,
    Pricing,
    RunBudget,
    UsageLedger,
    check_run,
    data_dir,
    default_path,
    estimate_tokens,
    month_key,
    reserve,
)

OCT = 1_790_000_000.0  # 2026-09-21 in UTC
SRC = Path(__file__).parents[1] / "src"


def ledger(tmp_path, **budget) -> UsageLedger:
    return UsageLedger(str(tmp_path / "usage.json"), budget=Budget(**budget), clock=lambda: OCT)


# --------------------------------------------------------------------------- recording
def test_usage_is_recorded_in_monthly_buckets(tmp_path):
    led = ledger(tmp_path, pricing=Pricing(3.0, 15.0))
    assert led.record("anthropic", 1000, 200)
    assert led.record("openai", 500, 100)
    m = led.month()
    assert (m.month, m.calls, m.input_tokens, m.output_tokens, m.tokens) == ("2026-09", 2, 1500, 300, 1800)
    assert m.cost == pytest.approx((1500 * 3 + 300 * 15) / 1e6)
    data = json.loads((tmp_path / "usage.json").read_text())
    assert data["version"] == 1
    providers = data["months"]["2026-09"]["providers"]
    assert providers["anthropic"]["input_tokens"] == 1000 and providers["openai"]["calls"] == 1
    assert led.month("2026-08").calls == 0


def test_local_calls_are_counted_but_cost_nothing(tmp_path):
    led = ledger(tmp_path, pricing=Pricing(3.0, 15.0))
    led.record("ollama", 1000, 1000, local=True)
    m = led.month()
    assert m.tokens == 2000 and m.cost == 0


def test_months_roll_over_in_utc_and_old_ones_are_dropped(tmp_path):
    t = [OCT]
    led = UsageLedger(str(tmp_path / "usage.json"), clock=lambda: t[0])
    for i in range(30):
        t[0] = OCT + i * 31 * 86400
        led.record("anthropic", 1, 1)
    months = json.loads((tmp_path / "usage.json").read_text())["months"]
    assert len(months) == 24 and min(months) > "2026-09"
    assert month_key(0) == "1970-01"


def test_recording_never_raises(tmp_path, caplog):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x")
    led = UsageLedger(str(blocker / "usage.json"))
    assert led.record("anthropic", 10, 10) is False
    assert "could not be recorded" in caplog.text
    assert led.record("anthropic", "lots", None) is False


def test_a_damaged_file_is_set_aside_and_counting_starts_again(tmp_path):
    path = tmp_path / "usage.json"
    path.write_bytes(b"{not json")
    led = ledger(tmp_path)
    assert led.month().calls == 0
    assert (tmp_path / "usage.damaged.json").read_bytes() == b"{not json"
    led.record("anthropic", 5, 5)
    assert led.month().calls == 1


def test_unknown_and_malformed_entries_are_ignored(tmp_path):
    path = tmp_path / "usage.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "months": {
                    "2026-09": {
                        "calls": 3,
                        "input_tokens": -5,
                        "output_tokens": "x",
                        "cost_micro_usd": 10,
                        "extra": 1,
                        "providers": {"anthropic": {"calls": 3}, "": {}, "x" * 40: {}},
                    },
                    "garbage": {"calls": 99},
                },
            }
        )
    )
    m = ledger(tmp_path).month()
    assert (m.calls, m.input_tokens, m.output_tokens) == (3, 0, 0)


def test_the_default_file_is_in_the_folder_tests_point_elsewhere():
    assert os.environ["SOLIDSEAS_CACHE_DIR"] and data_dir() == os.path.abspath(
        os.environ["SOLIDSEAS_CACHE_DIR"]
    )
    assert default_path() == os.path.join(data_dir(), "usage.json")


def test_two_processes_recording_at_once_lose_no_increment(tmp_path):
    path = tmp_path / "usage.json"
    code = (
        "import sys\n"
        "from solidseas.ai.usage import UsageLedger\n"
        "led = UsageLedger(sys.argv[1])\n"
        "ok = sum(led.record('anthropic', 3, 2) for _ in range(40))\n"
        "sys.exit(0 if ok == 40 else 1)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    procs = [subprocess.Popen([sys.executable, "-c", code, str(path)], env=env) for _ in range(2)]
    assert [p.wait(timeout=120) for p in procs] == [0, 0]
    m = UsageLedger(str(path)).month()
    assert (m.calls, m.input_tokens, m.output_tokens) == (80, 240, 160)


# --------------------------------------------------------------------------- the check before a call
def test_the_output_cap_is_what_the_monthly_budget_leaves(tmp_path):
    led = ledger(tmp_path, monthly_tokens=10_000)
    assert led.allow(input_tokens=1000, output_cap=8192) == 8192
    led.record("anthropic", 3000, 1000)
    assert led.allow(input_tokens=1000, output_cap=8192) == 5000
    led.record("anthropic", 4000, 800)
    with pytest.raises(BudgetExceededError) as info:
        led.allow(input_tokens=1000, output_cap=8192)
    assert "month's token budget" in str(info.value) and info.value.detail == {"limit": 10_000, "usage": 8800}


def test_the_run_budget_caps_every_provider_and_local_skips_the_monthly_one(tmp_path):
    led = ledger(tmp_path, monthly_tokens=1000)
    run = RunBudget(30_000)
    assert led.allow(input_tokens=5000, output_cap=8192, local=True, run=run) == 8192
    run.spend(20_000)
    assert led.allow(input_tokens=5000, output_cap=8192, local=True, run=run) == 5000
    with pytest.raises(BudgetExceededError):
        led.allow(input_tokens=5000, output_cap=8192, run=run)  # the monthly budget is too small
    run.spend(5000 - MIN_OUTPUT_TOKENS + 1)
    with pytest.raises(BudgetExceededError) as info:
        led.allow(input_tokens=5000, output_cap=8192, local=True, run=run)
    assert "run's token budget (30,000)" in str(info.value)
    assert check_run(RunBudget(10_000), 1000, 8192) == 8192


def test_the_cost_budget_caps_the_output_at_the_prices(tmp_path):
    led = ledger(tmp_path, monthly_cost=1.00, pricing=Pricing(3.0, 15.0))
    # $1 left; 10,000 input tokens cost $0.03; $0.97 buys 64,666 output tokens
    assert led.allow(input_tokens=10_000, output_cap=100_000) == 64_666
    led.record("anthropic", 0, 66_000)  # $0.99
    with pytest.raises(BudgetExceededError) as info:
        led.allow(input_tokens=10_000, output_cap=8192)
    assert "cost budget ($1.00)" in str(info.value)


def test_a_cost_budget_without_prices_refuses_cloud_calls(tmp_path):
    led = ledger(tmp_path, monthly_cost=5.0)
    with pytest.raises(BudgetExceededError) as info:
        led.allow(input_tokens=100, output_cap=8192)
    assert "prices are not" in str(info.value)
    assert led.allow(input_tokens=100, output_cap=8192, local=True) == 8192


def test_free_output_with_a_cost_budget(tmp_path):
    led = ledger(tmp_path, monthly_cost=1.0, pricing=Pricing(1.0, 0.0))
    assert led.allow(input_tokens=100, output_cap=8192) == 8192


def test_an_unreadable_usage_file_refuses_rather_than_guessing(tmp_path, monkeypatch):
    led = ledger(tmp_path)

    def fail():
        raise PermissionError(13, "denied")

    monkeypatch.setattr(led, "_load", fail)
    with pytest.raises(BudgetExceededError) as info:
        led.allow(input_tokens=10, output_cap=100)
    assert "could not be read" in str(info.value)


@pytest.mark.parametrize(
    "kw",
    [
        {"monthly_tokens": -1},
        {"monthly_tokens": 1.5},
        {"monthly_tokens": True},
        {"monthly_cost": -1},
        {"monthly_cost": float("nan")},
        {"monthly_cost": "5"},
    ],
)
def test_budget_settings_are_checked(kw):
    with pytest.raises(InvalidSettingError):
        Budget(**kw)


@pytest.mark.parametrize("prices", [(-1, 1), (1, float("inf")), ("3", 1), (1, 20_000)])
def test_prices_are_checked(prices):
    with pytest.raises(InvalidSettingError):
        Pricing(*prices)


def test_run_budgets_are_checked():
    for bad in (-1, 2_000_000, 1.0, True):
        with pytest.raises(InvalidSettingError):
            RunBudget(bad)


def test_the_estimate_is_on_the_high_side():
    assert estimate_tokens("") == 16 and estimate_tokens("x" * 300) == 116


# --------------------------------------------------------------------------- through a provider
# --------------------------------------------------------------------------- holds for calls in flight
DRAFT = '{"language": "python", "code": "pass", "explanation": ""}'


def holds(tmp_path) -> dict:
    return json.loads((tmp_path / "usage.json").read_text())["holds"]


def test_two_windows_cannot_both_spend_the_same_remainder(tmp_path):
    """Each window was told the whole remainder while the other's call was in flight: two
    calls against a 3,000-token budget recorded 5,972. The check now holds what it grants
    in usage.json, under the lock it read the file under."""
    path = str(tmp_path / "usage.json")
    window_a = UsageLedger(path, budget=Budget(monthly_tokens=3000), clock=lambda: OCT)
    window_b = UsageLedger(path, budget=Budget(monthly_tokens=3000), clock=lambda: OCT)
    in_flight, finish = threading.Event(), threading.Event()

    def slow(prompt):
        in_flight.set()
        finish.wait(10)
        return Completion(DRAFT, input_tokens=300, output_tokens=a.output_caps[-1])

    a = ScriptedProvider([slow], ledger=window_a, local=False)
    results = []
    thread = threading.Thread(target=lambda: results.append(a.draft_change(None, "make a cube")))
    thread.start()
    try:
        assert in_flight.wait(10)
        b = ScriptedProvider([DRAFT], ledger=window_b, local=False)
        with pytest.raises(BudgetExceededError) as info:
            b.draft_change(None, "make a cube")
        assert "in progress" in str(info.value) and b.prompts == [], "the second call was never sent"
    finally:
        finish.set()
        thread.join(10)
    assert results and results[0].value.code == "pass"
    assert window_b.month().tokens <= 3000 and holds(tmp_path) == {}


def test_a_hold_is_replaced_by_what_was_used_or_given_back(tmp_path):
    led = ledger(tmp_path, monthly_tokens=9000)
    hold = reserve(led, input_tokens=1000, output_cap=8192)
    assert hold.max_output == 8000 and list(holds(tmp_path).values())[0]["tokens"] == 9000
    with pytest.raises(BudgetExceededError):
        led.allow(input_tokens=1000, output_cap=8192)
    hold.settle("anthropic", 500, 100)
    hold.release()  # a hold ends once
    assert led.month().tokens == 600 and holds(tmp_path) == {}
    assert led.allow(input_tokens=1000, output_cap=8192) == 9000 - 600 - 1000
    other = reserve(led, input_tokens=1000, output_cap=8192)
    assert other.max_output == 9000 - 600 - 1000
    other.release()
    assert holds(tmp_path) == {} and led.month().calls == 1


def test_a_hold_left_by_a_window_that_closed_lapses(tmp_path):
    path = tmp_path / "usage.json"
    code = (
        "import sys\n"
        "from solidseas.ai.usage import Budget, UsageLedger, reserve\n"
        f"led = UsageLedger(sys.argv[1], budget=Budget(monthly_tokens=10_000), clock=lambda: {OCT})\n"
        "reserve(led, input_tokens=1000, output_cap=8192)\n"  # and exit mid-call
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    assert subprocess.run([sys.executable, "-c", code, str(path)], env=env, timeout=120).returncode == 0
    t = [OCT]
    led = UsageLedger(str(path), budget=Budget(monthly_tokens=10_000), clock=lambda: t[0])
    with pytest.raises(BudgetExceededError):
        led.allow(input_tokens=1000, output_cap=8192)
    t[0] = OCT + HOLD_SECONDS + 1
    assert led.allow(input_tokens=1000, output_cap=8192) == 8192


def test_holds_from_a_damaged_or_edited_file_are_read_safely(tmp_path):
    good = {"tokens": 4000, "cost_micro_usd": 0, "until": int(OCT) + 60}
    (tmp_path / "usage.json").write_text(
        json.dumps(
            {
                "version": 1,
                "months": {},
                "holds": {
                    "a1": good,
                    "far": {**good, "until": int(OCT) + 10 * 86400},  # a clock set back: dropped
                    "old": {**good, "until": int(OCT) - 1},
                    "bad/key": good,
                    "neg": {**good, "tokens": -5},
                    "float": {**good, "tokens": 1.5},
                    "list": [1],
                },
            }
        )
    )
    led = ledger(tmp_path, monthly_tokens=10_000)
    assert led.allow(input_tokens=1000, output_cap=8192) == 10_000 - 4000 - 1000
    led.record("anthropic", 1, 1)
    assert set(holds(tmp_path)) == {"a1"}


def test_the_run_budget_holds_for_calls_in_flight(tmp_path):
    run = RunBudget(10_000)
    first = reserve(None, input_tokens=1000, output_cap=8192, run=run)
    assert first.max_output == 8192 and run.held == 9192 and run.remaining == 808
    with pytest.raises(BudgetExceededError):
        reserve(None, input_tokens=1000, output_cap=8192, run=run)
    first.settle("scripted", 1000, 100)
    assert (run.used, run.held) == (1100, 0)
    second = reserve(None, input_tokens=1000, output_cap=8192, run=run)
    assert second.max_output == 7900
    second.release()
    assert (run.used, run.held) == (1100, 0)
    led = ledger(tmp_path, monthly_tokens=5000)
    run = RunBudget(30_000)
    hold = reserve(led, input_tokens=1000, output_cap=8192, run=run)
    assert hold.max_output == 4000 and run.held == 5000, "the month granted less, so the run holds less"
    with pytest.raises(BudgetExceededError):
        reserve(led, input_tokens=1000, output_cap=8192, run=run)
    assert run.held == 5000, "a refused call holds nothing"
    hold.release()
    assert run.held == 0 and holds(tmp_path) == {}


def test_a_provider_asks_for_no_more_than_the_budgets_leave(tmp_path):
    led = ledger(tmp_path, monthly_tokens=20_000)
    reply = '{"language": "python", "code": "pass", "explanation": ""}'
    provider = ScriptedProvider([reply, reply], ledger=led, local=False)
    provider.draft_change(None, "make a cube")
    first_in = estimate_tokens(provider.prompts[0].system) + estimate_tokens(provider.prompts[0].user)
    assert provider.output_caps[0] == 8192
    used = led.month().tokens
    provider.draft_change(None, "make a cube")
    assert provider.output_caps[1] == min(8192, 20_000 - used - first_in)
    with pytest.raises(BudgetExceededError):
        ScriptedProvider([reply], ledger=ledger(tmp_path, monthly_tokens=100), local=False).draft_change(
            None, "cube"
        )
