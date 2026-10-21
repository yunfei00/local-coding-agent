from src.app import build_demo


def test_demo_title() -> None:
    assert build_demo().title() == "Phase24 Demo 24.1"
