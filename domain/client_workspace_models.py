"""Typed client-centric workspace projection for persistent Dwaar cases."""

from dataclasses import dataclass
from typing import List

from domain.case_models import CaseRecord, Client, TaxRegistration


@dataclass(frozen=True)
class ClientWorkspace:
    """One firm's client master record plus registration and case history."""

    client: Client
    registrations: List[TaxRegistration]
    cases: List[CaseRecord]
