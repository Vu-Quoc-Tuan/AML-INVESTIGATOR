from app.data.provider import get_initialized_data_repository
from app.main import initialize_backend


def test_initialize_backend_warms_configured_repository(generated_data_path):
    repository = initialize_backend(generated_data_path)

    assert repository is get_initialized_data_repository()
    assert repository.data_path == generated_data_path.resolve()
