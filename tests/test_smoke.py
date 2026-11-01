import webhook_platform


def test_package_is_importable() -> None:
    assert webhook_platform.__name__ == "webhook_platform"
