from .version_info import DEMO_APP_VERSION


class DemoApplication:
    def title(self) -> str:
        return f"Phase24 Demo {DEMO_APP_VERSION}"


def build_demo() -> DemoApplication:
    return DemoApplication()
