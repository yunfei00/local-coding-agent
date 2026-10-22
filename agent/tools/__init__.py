"""Local workspace tool system."""

__all__ = ["ToolRegistry"]


def __getattr__(name):
    if name == 'ToolRegistry':
        from agent.tools.registry import ToolRegistry
        return ToolRegistry
    raise AttributeError(name)
