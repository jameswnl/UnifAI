"""ScheduleStore port ([4.1], issue #23)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from mas.triggers.schedule import Schedule


class ScheduleStore(ABC):

    @abstractmethod
    def save(self, schedule: Schedule) -> None: ...

    @abstractmethod
    def get(self, schedule_id: str) -> Optional[Schedule]: ...

    @abstractmethod
    def list_all(self) -> List[Schedule]: ...

    @abstractmethod
    def delete(self, schedule_id: str) -> bool: ...
