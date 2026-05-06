from typing import Any

import pytest
from django.contrib.auth import get_user_model

UserModel = get_user_model()


@pytest.fixture(autouse=True)
def _media_storage(settings: Any, tmpdir: Any) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def user(db: object) -> object:
    return UserModel.objects.create_user(username="testuser", password="testpass")  # noqa: S106
