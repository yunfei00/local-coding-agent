from src.app import greeting


def test_greeting() -> None:
    assert greeting() == "baseline"
