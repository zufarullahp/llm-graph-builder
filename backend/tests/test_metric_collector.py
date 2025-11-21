from src.proactive_controller import _collect_metric


def test_metric_collector_handles_unserializable():
    # Should not raise even when given an unserializable field (set)
    _collect_metric("test_event", field=set([1, 2, 3]))
