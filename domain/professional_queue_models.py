"""Professional queue overlay contracts for Dwaar Phase 3O.5."""

from dataclasses import dataclass
from typing import Tuple

from domain.case_operations_models import CaseWorkItem
from domain.professional_workbench_models import (
    CaseAttentionCode,
    CaseWorkspace,
)


@dataclass(frozen=True)
class ProfessionalQueueItem:
    work_item: CaseWorkItem
    attention_codes: Tuple[CaseAttentionCode, ...]
    attention_workspaces: Tuple[CaseWorkspace, ...]

    @property
    def attention_count(self) -> int:
        return len(self.attention_codes)
