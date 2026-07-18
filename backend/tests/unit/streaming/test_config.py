import pytest

from app.streaming.config import KafkaSettings


def test_settings_use_documented_defaults(monkeypatch):
    for name in KafkaSettings.environment_names():
        monkeypatch.delenv(name, raising=False)
    settings = KafkaSettings.from_env()
    assert settings.bootstrap_servers == ("localhost:9092",)
    assert settings.raw_topic == "aml.transactions.raw.v1"
    assert settings.validated_topic == "aml.transactions.validated.v1"
    assert settings.dlq_topic == "aml.transactions.dlq.v1"
    assert settings.enable_auto_commit is False


def test_settings_parse_multiple_bootstrap_servers(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-a:9092, kafka-b:9092")
    assert KafkaSettings.from_env().bootstrap_servers == (
        "kafka-a:9092",
        "kafka-b:9092",
    )


@pytest.mark.parametrize("field,value", [("poll_timeout_ms", 0), ("ack_timeout_seconds", 0)])
def test_settings_reject_non_positive_timeouts(field, value):
    with pytest.raises(ValueError):
        KafkaSettings(**{field: value})
