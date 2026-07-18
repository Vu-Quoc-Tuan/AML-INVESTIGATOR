# Realtime Kafka ingestion

Phần này chỉ triển khai biên nhận giao dịch realtime:

```text
upstream/mock -> aml.transactions.raw.v1
             -> validation relay
             -> aml.transactions.validated.v1 (hợp lệ)
             -> aml.transactions.dlq.v1       (không hợp lệ, đã che payload)
```

Chưa có ML, rulebase, ticket hay multi-agent trong luồng này.

## Điểm Kafka nhận dữ liệu

- Service chạy trực tiếp trên máy: bootstrap `localhost:9092`, topic `aml.transactions.raw.v1`.
- Service ở cùng Docker network với broker: bootstrap `kafka:29092`, cùng topic raw.
- Kafka message `key` nên là `event_id`; `value` là JSON đúng schema `TransactionEventV1` trong `app/streaming/schemas.py`.

Relay chỉ commit offset raw sau khi Kafka xác nhận bản ghi ở validated topic hoặc DLQ. Vì vậy delivery là at-least-once: khi process chết trước commit, record có thể được đọc lại nhưng không bị bỏ mất.

## Chạy demo thật

Từ thư mục gốc repo:

```bash
docker compose -f docker-compose.kafka.yml up -d
cd backend
.venv/bin/python scripts/create_kafka_topics.py
```

Mở terminal thứ hai để chạy relay:

```bash
cd backend
.venv/bin/python scripts/run_kafka_ingestion.py
```

Mở terminal thứ ba để phát 10 giao dịch realtime, mỗi giây một giao dịch:

```bash
cd backend
.venv/bin/python scripts/run_mock_transaction_service.py --interval 1 --limit 10 --seed 42
```

Kiểm tra dữ liệu validated trực tiếp bằng Kafka CLI:

```bash
docker exec aml-kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic aml.transactions.validated.v1 \
  --from-beginning \
  --max-messages 10
```

## Dữ liệu được lưu ở đâu

Kafka lưu log segment trong Compose named volume logic `aml-kafka-data` (Docker thường hiển thị là `aml-investigator_aml-kafka-data`), mount vào `/var/lib/kafka/data` trong container. Restart container không làm mất dữ liệu. Cấu hình local giữ log tối đa 168 giờ (7 ngày). Lệnh `docker compose down` giữ volume; `docker compose down -v` sẽ xóa cả dữ liệu Kafka.

## Biến môi trường

Các giá trị mặc định nằm trong `.env.example`. Client chạy trong Docker network cần đặt:

```bash
KAFKA_BOOTSTRAP_SERVERS=kafka:29092
```

Broker local này dùng PLAINTEXT và replication factor 1 để demo/phát triển, không phải cấu hình production. Production cần cluster nhiều broker, TLS/SASL, ACL, monitoring và chính sách retention riêng.

## Dừng

Nhấn `Ctrl+C` ở relay/mock publisher, sau đó từ thư mục gốc:

```bash
docker compose -f docker-compose.kafka.yml down
```

Nếu `localhost:9092` đang bị service khác dùng, dừng service đó trước khi start Compose. Nếu topic initializer báo không kết nối được, kiểm tra `docker compose -f docker-compose.kafka.yml ps` và chờ health status chuyển sang `healthy`.
