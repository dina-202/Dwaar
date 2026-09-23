"""Live encrypted-storage audit contracts for Dwaar Phase 3P.6."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeStorageAuditReport:
    storage_table_count: int
    referenced_object_count: int
    object_file_count: int
    missing_object_count: int
    orphan_object_count: int
    invalid_reference_count: int
    invalid_object_entry_count: int
    authentication_failure_count: int

    @property
    def consistent(self) -> bool:
        return all(
            value == 0
            for value in (
                self.missing_object_count,
                self.orphan_object_count,
                self.invalid_reference_count,
                self.invalid_object_entry_count,
                self.authentication_failure_count,
            )
        )
