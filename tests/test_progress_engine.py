from shared.vm_core.progress import ProgressEvent, ProgressLine, format_progress, progress_snapshot, render_bar


def test_progress_percent_is_bounded():
    assert ProgressLine("x", 5, 10).percent == 50
    assert ProgressLine("x", 20, 10).percent == 100
    assert ProgressLine("x", -2, 10).percent == 0
    assert ProgressLine("x", 1, 0).percent == 0


def test_render_bar_contains_percent():
    assert "50%" in render_bar(50, width=10)
    assert render_bar(-1).endswith("  0%")
    assert render_bar(101).endswith("100%")


def test_snapshot_normalises_health_and_keeps_three_tiers():
    snapshot = progress_snapshot(
        headline="SMART AUTO POSTER",
        overall=ProgressLine("Campaign", 50, 100, "RUNNING"),
        group=ProgressLine("Destination batch", 4, 8, "RUNNING"),
        task=ProgressLine("Send album", 1, 1, "DONE"),
        services=[
            {"name": "worker", "runtime_status": "RUNNING"},
            {"name": "admin_bot", "runtime_status": "STALE"},
            {"name": "scheduler", "runtime_status": "FAILED"},
        ],
        events=[ProgressEvent("worker started", source="worker")],
        recovery_messages=["Restart scheduler after diagnostics pass."],
    )
    assert snapshot["overall"]["percent"] == 50
    assert snapshot["group"]["percent"] == 50
    assert snapshot["task"]["percent"] == 100
    assert [row["status"] for row in snapshot["services"]] == ["HEALTHY", "DEGRADED", "FAILED"]
    assert snapshot["events"][0]["message"] == "worker started"


def test_text_formatter_exposes_operator_sections():
    snapshot = progress_snapshot(
        headline="SMART AUTO POSTER PROGRESS",
        overall=ProgressLine("Campaign", 3, 4, "RUNNING"),
        group=ProgressLine("Current group", 1, 2, "RUNNING"),
        task=ProgressLine("Current task", 1, 1, "DONE"),
        services=[{"name": "worker", "runtime_status": "ALIVE"}],
        events=[{"message": "post delivered", "level": "INFO", "source": "worker"}],
        recovery_messages=["No recovery required."],
    )
    text = format_progress(snapshot)
    assert "OVERALL" in text
    assert "CURRENT GROUP" in text
    assert "CURRENT TASK" in text
    assert "HEALTH" in text
    assert "LIVE EVENT FEED" in text
    assert "RECOVERY / NEXT ACTION" in text
