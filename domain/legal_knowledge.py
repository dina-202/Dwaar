"""Deterministic fail-closed resolver for Phase 3N legal knowledge."""

from collections import defaultdict
from typing import Dict, Iterable, Tuple
from urllib.parse import urlparse

from domain.legal_knowledge_models import (
    LegalKnowledgeQuery,
    LegalKnowledgeResult,
    LegalRule,
    LegalRuleMatch,
    LegalSourceRef,
    LegalTopic,
    LegalVerificationStatus,
)


APPROVED_OFFICIAL_DOMAINS = frozenset({
    "indiacode.nic.in",
    "www.indiacode.nic.in",
    "cbic-gst.gov.in",
    "www.cbic-gst.gov.in",
})


def _nonempty(value: str) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _source_valid(source: LegalSourceRef) -> bool:
    if not all(
        _nonempty(value)
        for value in (
            source.source_id,
            source.title,
            source.issuer,
            source.official_url,
            source.official_domain,
            source.version_label,
        )
    ):
        return False
    parsed = urlparse(source.official_url)
    if parsed.scheme != "https":
        return False
    if parsed.hostname not in APPROVED_OFFICIAL_DOMAINS:
        return False
    if source.official_domain != parsed.hostname:
        return False
    return True


def _rule_valid(rule: LegalRule) -> bool:
    if not all(
        _nonempty(value)
        for value in (
            rule.rule_id,
            rule.rule_key,
            rule.source_id,
            rule.provision,
            rule.proposition,
            rule.jurisdiction,
        )
    ):
        return False
    if not rule.proceeding_types:
        return False
    if rule.effective_to is not None and rule.effective_to < rule.effective_from:
        return False
    return True


def validate_catalog(
    sources: Iterable[LegalSourceRef],
    rules: Iterable[LegalRule],
) -> bool:
    source_list = tuple(sources)
    rule_list = tuple(rules)

    source_ids = [source.source_id for source in source_list]
    rule_ids = [rule.rule_id for rule in rule_list]

    if len(source_ids) != len(set(source_ids)):
        return False
    if len(rule_ids) != len(set(rule_ids)):
        return False

    if not all(_source_valid(source) for source in source_list):
        return False
    if not all(_rule_valid(rule) for rule in rule_list):
        return False

    source_by_id: Dict[str, LegalSourceRef] = {
        source.source_id: source for source in source_list
    }
    for rule in rule_list:
        source = source_by_id.get(rule.source_id)
        if source is None:
            return False
        if (
            rule.verification_status is LegalVerificationStatus.SOURCE_VERIFIED
            and source.verification_status
            is not LegalVerificationStatus.SOURCE_VERIFIED
        ):
            return False

    verified_by_key = defaultdict(list)
    for rule in rule_list:
        if rule.verification_status is LegalVerificationStatus.SOURCE_VERIFIED:
            verified_by_key[rule.rule_key].append(rule)

    for versions in verified_by_key.values():
        ordered = sorted(versions, key=lambda item: item.effective_from)
        for previous, current in zip(ordered, ordered[1:]):
            if previous.effective_to is None:
                return False
            if current.effective_from <= previous.effective_to:
                return False

    return True


def resolve_legal_knowledge(
    query: LegalKnowledgeQuery,
    *,
    catalog_version: str,
    sources: Iterable[LegalSourceRef],
    rules: Iterable[LegalRule],
) -> LegalKnowledgeResult:
    source_list = tuple(sources)
    rule_list = tuple(rules)

    if not _nonempty(catalog_version):
        return LegalKnowledgeResult(
            matches=(),
            unresolved_topics=tuple(dict.fromkeys(query.topics)),
            catalog_valid=False,
            catalog_version=catalog_version,
        )

    if not validate_catalog(source_list, rule_list):
        return LegalKnowledgeResult(
            matches=(),
            unresolved_topics=tuple(dict.fromkeys(query.topics)),
            catalog_valid=False,
            catalog_version=catalog_version,
        )

    requested_topics = tuple(dict.fromkeys(query.topics))
    source_by_id = {source.source_id: source for source in source_list}
    matches = []

    for rule in rule_list:
        if rule.verification_status is not LegalVerificationStatus.SOURCE_VERIFIED:
            continue
        source = source_by_id[rule.source_id]
        if source.verification_status is not LegalVerificationStatus.SOURCE_VERIFIED:
            continue
        if query.proceeding_type not in rule.proceeding_types:
            continue
        if rule.topic not in requested_topics:
            continue
        if query.as_of_date < rule.effective_from:
            continue
        if rule.effective_to is not None and query.as_of_date > rule.effective_to:
            continue
        matches.append(LegalRuleMatch(rule=rule, source=source))

    matches.sort(
        key=lambda item: (
            requested_topics.index(item.rule.topic),
            item.rule.rule_key,
            item.rule.effective_from,
            item.rule.rule_id,
        )
    )
    resolved_topics = {match.rule.topic for match in matches}
    unresolved = tuple(
        topic for topic in requested_topics if topic not in resolved_topics
    )

    return LegalKnowledgeResult(
        matches=tuple(matches),
        unresolved_topics=unresolved,
        catalog_valid=True,
        catalog_version=catalog_version,
    )
