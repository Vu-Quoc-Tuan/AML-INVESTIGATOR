from app.streaming.config import KafkaSettings
from app.streaming.topic_admin import ensure_topics


class FakeAdmin:
    def __init__(self, existing):
        self.existing = existing
        self.created = []

    def list_topics(self):
        return self.existing

    def create_topics(self, new_topics, validate_only):
        self.created.extend(new_topics)


def test_ensure_topics_creates_only_missing_topics():
    admin = FakeAdmin(existing={"aml.transactions.raw.v1"})
    created = ensure_topics(KafkaSettings(), admin=admin)
    assert {topic.name for topic in admin.created} == {
        "aml.transactions.validated.v1",
        "aml.transactions.dlq.v1",
    }
    assert created == {
        "aml.transactions.validated.v1",
        "aml.transactions.dlq.v1",
    }


def test_ensure_topics_is_noop_when_all_exist():
    settings = KafkaSettings()
    admin = FakeAdmin(
        existing={settings.raw_topic, settings.validated_topic, settings.dlq_topic}
    )
    assert ensure_topics(settings, admin=admin) == set()
    assert admin.created == []
