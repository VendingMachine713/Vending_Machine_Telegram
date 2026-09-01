from smart_autoposter.status_view import job_percent, render_job, render_snapshot, summarise_queue


def test_job_percent_known_states():
    assert job_percent("pending") == 0
    assert job_percent("sending") == 70
    assert job_percent("sent") == 100
    assert job_percent("unknown") == 0


def test_summarise_queue_counts_health_and_progress():
    rows = [
        {"status": "sent"},
        {"status": "sent"},
        {"status": "sending"},
        {"status": "deferred"},
    ]
    snapshot = summarise_queue(rows)
    assert snapshot.total == 4
    assert snapshot.complete == 2
    assert snapshot.successful == 2
    assert snapshot.attention == 0
    assert snapshot.active == 1
    assert snapshot.waiting == 1
    assert snapshot.percent == 70
    assert snapshot.healthy is True


def test_summarise_queue_flags_only_review_states():
    rows = [
        {"status": "retry"},
        {"status": "deferred"},
        {"status": "uncertain"},
        {"status": "failed"},
    ]
    snapshot = summarise_queue(rows)
    assert snapshot.attention == 2
    assert snapshot.healthy is False


def test_render_snapshot_is_plain_language():
    snapshot = summarise_queue([
        {"status": "sent"},
        {"status": "sending"},
    ])
    text = render_snapshot(snapshot)
    assert "SMART AUTO POSTER - DELIVERY PROGRESS" in text
    assert "Complete: 1/2" in text
    assert "Currently posting: 1" in text
    assert "OK - no action needed" in text
    assert "%" in text


def test_render_job_exposes_actionable_error_only_when_relevant():
    retry = render_job({
        "status": "retry",
        "group_name": "Test Group",
        "account_key": "primary",
        "last_error": "slow_mode: wait 30 seconds",
    })
    assert "Test Group" in retry
    assert "Waiting to retry automatically" in retry
    assert "slow_mode" in retry

    sent = render_job({
        "status": "sent",
        "group_name": "Test Group",
        "last_error": "old error",
    })
    assert "old error" not in sent
