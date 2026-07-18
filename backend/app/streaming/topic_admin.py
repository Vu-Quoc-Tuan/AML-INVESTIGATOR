from __future__ import annotations

from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

from app.streaming.config import KafkaSettings


def ensure_topics(
    settings: KafkaSettings,
    partitions: int = 1,
    replication_factor: int = 1,
    *,
    admin=None,
) -> set[str]:
    if partitions <= 0 or replication_factor <= 0:
        raise ValueError("partitions and replication_factor must be positive")
    owned_admin = admin is None
    admin = admin or KafkaAdminClient(
        bootstrap_servers=list(settings.bootstrap_servers),
        client_id=f"{settings.client_id}-topic-admin",
    )
    try:
        existing = set(admin.list_topics())
        wanted = (settings.raw_topic, settings.validated_topic, settings.dlq_topic)
        missing = [
            NewTopic(
                name=name,
                num_partitions=partitions,
                replication_factor=replication_factor,
            )
            for name in wanted
            if name not in existing
        ]
        if missing:
            try:
                admin.create_topics(new_topics=missing, validate_only=False)
            except TopicAlreadyExistsError:
                # Another initializer won the race; the desired end state already exists.
                pass
        return {topic.name for topic in missing}
    finally:
        if owned_admin:
            admin.close()
