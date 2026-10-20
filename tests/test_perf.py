"""Unit tests for perf.py performance profiler and polynomial regression."""

import unittest.mock as mock
from pathlib import Path
from pystdoc.perf import (
    PerfProfileManager,
    evaluate_polynomial,
    fit_polynomial_regression,
    solve_linear_system,
)


def test_solve_linear_system_basic():
    matrix = [[2.0, 1.0], [1.0, 3.0]]
    vector = [5.0, 5.0]
    sol = solve_linear_system(matrix, vector)
    assert round(sol[0], 2) == 2.0
    assert round(sol[1], 2) == 1.0


def test_solve_linear_system_zero_pivot():
    matrix = [[0.0, 0.0], [0.0, 0.0]]
    vector = [0.0, 0.0]
    sol = solve_linear_system(matrix, vector)
    assert sol == [0.0, 0.0]


def test_fit_polynomial_regression_empty():
    coeffs = fit_polynomial_regression([])
    assert len(coeffs) == 4
    assert coeffs[0] == 0.8
    assert coeffs[1] == 0.02


def test_fit_polynomial_regression_single():
    coeffs = fit_polynomial_regression([(10.0, 2.5)])
    assert len(coeffs) == 4
    assert coeffs[0] == 2.5
    assert coeffs[1] == 0.0


def test_fit_polynomial_regression_multi():
    samples = [
        (10.0, 1.0),
        (20.0, 2.0),
        (30.0, 3.0),
        (40.0, 4.0),
        (50.0, 5.0),
    ]
    coeffs = fit_polynomial_regression(samples, degree=3)
    assert len(coeffs) == 4
    val = evaluate_polynomial(coeffs, 25.0)
    assert 2.0 <= val <= 3.0


def test_evaluate_polynomial_lower_bound():
    coeffs = [-100.0, -10.0, 0.0, 0.0]
    val = evaluate_polynomial(coeffs, 5.0)
    assert val == 0.05


def test_perf_profile_manager(tmp_path: Path):
    metrics_file = tmp_path / "perf_metrics.json"
    mgr = PerfProfileManager(metrics_file=metrics_file)

    # Initial predict fallback
    dur = mgr.predict_duration(
        "http://localhost:11434", "test-model", "bottom_symbol", "function", 50
    )
    assert dur > 0.0

    # Record measurements
    mgr.record_measurement(
        host="http://localhost:11434",
        model="test-model",
        gen_type="bottom_symbol",
        symbol_kind="function",
        line_count=50,
        elapsed_seconds=1.5,
    )

    dur2 = mgr.predict_duration(
        "http://localhost:11434", "test-model", "bottom_symbol", "function", 50
    )
    assert dur2 > 0.0

    # Test file corrupted recovery
    metrics_file.write_text("invalid json", encoding="utf-8")
    mgr.load()
    assert mgr.data == {}

    # Test file is not dict
    metrics_file.write_text("[1, 2, 3]", encoding="utf-8")
    mgr.load()
    assert mgr.data == {}

    # Save and reload
    mgr.record_measurement(
        host=None,
        model=None,
        gen_type="top_down",
        symbol_kind=None,
        line_count=20,
        elapsed_seconds=0.8,
    )
    assert metrics_file.exists()

    # Save failure handling
    with mock.patch.object(
        Path, "mkdir", side_effect=PermissionError("denied")
    ):
        mgr.save()

    # Predict with category fallback
    dur3 = mgr.predict_duration(None, None, "top_down", "other_kind", 30)
    assert dur3 > 0.0

    # Exceed 100 samples
    for i in range(105):
        mgr.record_measurement(
            host="http://localhost:11434",
            model="test-model",
            gen_type="bottom_symbol",
            symbol_kind="function",
            line_count=i + 1,
            elapsed_seconds=(i + 1) * 0.1,
        )

    # Singleton instance test
    singleton = PerfProfileManager.get_instance(metrics_file=metrics_file)
    assert singleton is not None


def test_record_server_timing_and_adaptive_timeout(tmp_path: Path):
    metrics_file = tmp_path / "perf_metrics.json"
    mgr = PerfProfileManager(metrics_file=metrics_file)

    host = "http://192.168.11.6:11434"
    model = "gemma4-26b-a4b"

    # Default when no profile exists
    t_def = mgr.get_adaptive_timeout(host, model, input_chars=1000)
    assert t_def == 120

    # Record first cold start request
    mgr.record_server_timing(
        host=host,
        model=model,
        input_chars=500,
        output_chars=200,
        elapsed_seconds=54.2,
        is_first_in_session=True,
    )

    prof = mgr.get_server_profile(host, model)
    assert prof.get("cold_start_duration") == 54.2
    assert prof.get("max_cold_start_seen") == 54.2

    # Adaptive timeout for first request should now account for cold start
    t_first = mgr.get_adaptive_timeout(
        host, model, input_chars=500, is_first_in_session=True
    )
    assert t_first >= 114  # 54.2 + 60

    # Record normal warm request
    mgr.record_server_timing(
        host=host,
        model=model,
        input_chars=1000,
        output_chars=300,
        elapsed_seconds=8.5,
        is_first_in_session=False,
        idle_seconds_before=5.0,
    )

    prof2 = mgr.get_server_profile(host, model)
    assert len(prof2.get("request_timings", [])) == 2
    assert "avg_total_chars_per_sec" in prof2
