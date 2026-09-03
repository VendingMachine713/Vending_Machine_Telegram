from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .logging_setup import log_event
from .paths import bot_root, project_root, state_path
from .platform_registry import ServiceDescriptor, describe_services
from .publisher import BotEventPublisher


@dataclass(frozen=True)
class ServiceContext:
    descriptor: ServiceDescriptor
    root: Path
    bot_dir: Path

    @property
    def name(self) -> str:
        return self.descriptor.name

    @property
    def version(self) -> str | None:
        return self.descriptor.version

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(self.descriptor.capabilities)

    @property
    def runtime_required_env(self) -> tuple[str, ...]:
        return tuple(self.descriptor.runtime_required_env)

    def state_path(self, *parts: str) -> Path:
        return state_path(self.descriptor.folder, *parts, root=self.root)

    def bot_path(self, *parts: str) -> Path:
        return self.bot_dir.joinpath(*parts)

    def log(self, event: str, *, level: str = "INFO", data: dict[str, Any] | None = None) -> Path:
        return log_event(event, level=level, service=self.descriptor.name, data=data, root=self.root)

    def publisher(self, *, instance_id: str | None = None) -> BotEventPublisher:
        return BotEventPublisher(self.descriptor.name, self.root, instance_id=instance_id)


def service_context(name: str, root: Path | None = None) -> ServiceContext:
    root = root or project_root()
    normalized = str(name or "").strip().lower()
    if not normalized:
        raise KeyError("service name is required")

    matches = [
        item for item in describe_services(root)
        if item.name.lower() == normalized or item.folder.lower() == normalized
    ]
    if len(matches) != 1:
        raise KeyError(f"service not uniquely found: {name}")

    descriptor = matches[0]
    return ServiceContext(
        descriptor=descriptor,
        root=root,
        bot_dir=bot_root(descriptor.folder, root),
    )
