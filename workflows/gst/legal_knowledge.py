"""Curated GST legal-knowledge pack for Phase 3N v1.

The pack is intentionally small. Each SOURCE_VERIFIED proposition is tied to
an official source and an explicit effective period. This module performs no
network access and no legal inference.
"""

from datetime import date

from domain.legal_knowledge_models import (
    LegalAuthorityType,
    LegalRule,
    LegalSourceRef,
    LegalTopic,
    LegalVerificationStatus,
)
from domain.models import ProceedingType


GST_LEGAL_CATALOG_VERSION = "gst-legal.v4.2026-09-23"

CGST_ACT_INDIA_CODE = LegalSourceRef(
    source_id="src.cgst_act.indiacode.2026-09-23",
    authority_type=LegalAuthorityType.ACT,
    title="The Central Goods and Services Tax Act, 2017",
    issuer="Parliament of India",
    official_url=(
        "https://www.indiacode.nic.in/indiacode/handle/123456789/15689"
    ),
    official_domain="www.indiacode.nic.in",
    version_label="India Code consolidated source accessed 2026-09-23",
    publication_date=date(2017, 4, 12),
    retrieved_at=date(2026, 9, 23),
    verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
)

CIRCULAR_183_CBIC = LegalSourceRef(
    source_id="src.cbic.circular.183.2022",
    authority_type=LegalAuthorityType.CIRCULAR,
    title="Circular No. 183/15/2022-GST",
    issuer="Central Board of Indirect Taxes and Customs",
    official_url="https://cbic-gst.gov.in/pdf/circular-183.pdf",
    official_domain="cbic-gst.gov.in",
    version_label="Circular dated 2022-12-27",
    publication_date=date(2022, 12, 27),
    retrieved_at=date(2026, 9, 23),
    verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
)

CIRCULAR_193_GST_COUNCIL = LegalSourceRef(
    source_id="src.gstcouncil.circular.193.2023",
    authority_type=LegalAuthorityType.CIRCULAR,
    title="Circular No. 193/05/2023-GST",
    issuer="Central Board of Indirect Taxes and Customs",
    official_url="https://gstcouncil.gov.in/node/4914",
    official_domain="gstcouncil.gov.in",
    version_label="GST Council circular page dated 2023-07-17",
    publication_date=date(2023, 7, 17),
    retrieved_at=date(2026, 9, 23),
    verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
)

GST_LEGAL_SOURCES = (
    CGST_ACT_INDIA_CODE,
    CIRCULAR_183_CBIC,
    CIRCULAR_193_GST_COUNCIL,
)

GST_LEGAL_RULES = (
    LegalRule(
        rule_id="cbic.itc_mismatch_verification.fy2017_2018.v1",
        rule_key="cbic.itc_mismatch_verification",
        source_id=CIRCULAR_183_CBIC.source_id,
        provision="Circular No. 183/15/2022-GST",
        proposition=(
            "For FY 2017-18 and 2018-19, Circular 183 provides a "
            "case-specific verification procedure for specified differences "
            "between ITC availed in FORM GSTR-3B and ITC appearing in FORM "
            "GSTR-2A; the procedure requires verification of relevant "
            "Section 16 conditions and prescribed supplier tax-payment "
            "evidence, subject to the circular's stated scope and conditions."
        ),
        effective_from=date(2017, 4, 1),
        effective_to=date(2019, 3, 31),
        jurisdiction="India",
        topic=LegalTopic.ITC_MISMATCH_VERIFICATION,
        proceeding_types=(ProceedingType.GST_SEC73_ITC,),
        verified_at=date(2026, 9, 23),
        verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
    ),
    LegalRule(
        rule_id="cbic.itc_mismatch_verification.2019_2021.v2",
        rule_key="cbic.itc_mismatch_verification",
        source_id=CIRCULAR_193_GST_COUNCIL.source_id,
        provision="Circular No. 193/05/2023-GST",
        proposition=(
            "For 1 April 2019 through 31 December 2021, Circular 193 "
            "provides period-specific verification guidance for differences "
            "between ITC availed in FORM GSTR-3B and ITC appearing in FORM "
            "GSTR-2A, including the Rule 36(4) limits applicable during "
            "the sub-periods identified in that circular."
        ),
        effective_from=date(2019, 4, 1),
        effective_to=date(2021, 12, 31),
        jurisdiction="India",
        topic=LegalTopic.ITC_MISMATCH_VERIFICATION,
        proceeding_types=(ProceedingType.GST_SEC73_ITC,),
        verified_at=date(2026, 9, 23),
        verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
    ),
    LegalRule(
        rule_id="cbic.itc_mismatch_verification.post2022.v3",
        rule_key="cbic.itc_mismatch_verification",
        source_id=CIRCULAR_193_GST_COUNCIL.source_id,
        provision="Circular No. 193/05/2023-GST, paragraph 5",
        proposition=(
            "For periods beginning 1 January 2022, Circular 193 records "
            "that, after insertion of section 16(2)(aa) and amendment of "
            "rule 36(4), ITC in respect of a supply is not to be allowed "
            "unless the supplier reports it in FORM GSTR-1 or IFF and it "
            "is communicated to the recipient in FORM GSTR-2B."
        ),
        effective_from=date(2022, 1, 1),
        effective_to=None,
        jurisdiction="India",
        topic=LegalTopic.ITC_MISMATCH_VERIFICATION,
        proceeding_types=(ProceedingType.GST_SEC73_ITC,),
        verified_at=date(2026, 9, 23),
        verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
    ),
    LegalRule(
        rule_id="cgst.s75.4.hearing.v1",
        rule_key="cgst.s75.4.hearing",
        source_id=CGST_ACT_INDIA_CODE.source_id,
        provision="CGST Act, section 75(4)",
        proposition=(
            "An opportunity of hearing is to be granted where a written "
            "request is received from the person chargeable with tax or "
            "penalty, or where an adverse decision is contemplated."
        ),
        effective_from=date(2017, 7, 1),
        effective_to=None,
        jurisdiction="India",
        topic=LegalTopic.HEARING_RIGHT,
        proceeding_types=(
            ProceedingType.GST_SEC73_GENERAL,
            ProceedingType.GST_SEC73_ITC,
            ProceedingType.GST_SEC73_RCM,
            ProceedingType.GST_SEC74_FRAUD,
        ),
        verified_at=date(2026, 9, 23),
        verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
    ),
    LegalRule(
        rule_id="cgst.s75.7.demand_scope.v1",
        rule_key="cgst.s75.7.demand_scope",
        source_id=CGST_ACT_INDIA_CODE.source_id,
        provision="CGST Act, section 75(7)",
        proposition=(
            "The amount of tax, interest and penalty demanded in the order "
            "must not exceed the amount specified in the notice, and no "
            "demand may be confirmed on grounds other than those specified "
            "in the notice."
        ),
        effective_from=date(2017, 7, 1),
        effective_to=None,
        jurisdiction="India",
        topic=LegalTopic.DEMAND_SCOPE,
        proceeding_types=(
            ProceedingType.GST_SEC73_GENERAL,
            ProceedingType.GST_SEC73_ITC,
            ProceedingType.GST_SEC73_RCM,
            ProceedingType.GST_SEC74_FRAUD,
        ),
        verified_at=date(2026, 9, 23),
        verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
    ),
    LegalRule(
        rule_id="cgst.s74.fraud_scope.fy2017_2023.v1",
        rule_key="cgst.s74.fraud_scope",
        source_id=CGST_ACT_INDIA_CODE.source_id,
        provision="CGST Act, sections 74 and 74A",
        proposition=(
            "Section 74 is the demand route for tax not paid or short paid, "
            "erroneous refund, or input tax credit wrongly availed or "
            "utilised by reason of fraud, wilful misstatement or suppression "
            "of facts for periods up to Financial Year 2023-24; section 74A "
            "applies to Financial Year 2024-25 onward."
        ),
        effective_from=date(2017, 7, 1),
        effective_to=date(2024, 3, 31),
        jurisdiction="India",
        topic=LegalTopic.FRAUD_SUPPRESSION_SCOPE,
        proceeding_types=(ProceedingType.GST_SEC74_FRAUD,),
        verified_at=date(2026, 9, 23),
        verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
    ),
    LegalRule(
        rule_id="cgst.s129.3.timeline.2022.v1",
        rule_key="cgst.s129.3.timeline",
        source_id=CGST_ACT_INDIA_CODE.source_id,
        provision="CGST Act, section 129(3)",
        proposition=(
            "For the version effective from 1 January 2022, the proper "
            "officer is to issue the penalty notice within seven days of "
            "detention or seizure and pass the order within seven days "
            "from service of that notice."
        ),
        effective_from=date(2022, 1, 1),
        effective_to=None,
        jurisdiction="India",
        topic=LegalTopic.SECTION_129_TIMELINE,
        proceeding_types=(ProceedingType.GST_SEC129_ENFORCE,),
        verified_at=date(2026, 9, 23),
        verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
    ),
    LegalRule(
        rule_id="cgst.s129.4.hearing.2022.v1",
        rule_key="cgst.s129.4.hearing",
        source_id=CGST_ACT_INDIA_CODE.source_id,
        provision="CGST Act, section 129(4)",
        proposition=(
            "No penalty under section 129(3) is to be determined without "
            "giving the person concerned an opportunity of being heard."
        ),
        effective_from=date(2022, 1, 1),
        effective_to=None,
        jurisdiction="India",
        topic=LegalTopic.SECTION_129_HEARING,
        proceeding_types=(ProceedingType.GST_SEC129_ENFORCE,),
        verified_at=date(2026, 9, 23),
        verification_status=LegalVerificationStatus.SOURCE_VERIFIED,
    ),
)
