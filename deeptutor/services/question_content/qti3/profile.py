"""Bounded QTI 3.0 item-bank exchange profile."""

QTI_NS = "http://www.imsglobal.org/xsd/imsqtiasi_v3p0"
PACKAGE_NS = "http://www.imsglobal.org/xsd/qti/qtiv3p0/imscp_v1p1"
ITEM_SCHEMA_NAME = "imsqti_itemv3p0p1_v1p0.xsd"
PACKAGE_SCHEMA_NAME = "imsqtiv3p0_imscpv1p2_v1p0.xsd"
PROFILE_VERSION = "reactutor-qti3-item-bank/1"
MAX_XML_BYTES = 10 * 1024 * 1024
MAX_XML_DEPTH = 128
MAX_XML_ELEMENTS = 200_000

CAPABILITY_MATRIX = {
    "single_choice": {
        "interaction": "qti-choice-interaction",
        "cardinality": "single",
        "score": "exact_choice_if_proven_else_external",
    },
    "multi_choice": {
        "interaction": "qti-choice-interaction",
        "cardinality": "multiple",
        "score": "exact_set_if_proven_else_external",
    },
    "true_false": {
        "interaction": "qti-choice-interaction",
        "cardinality": "single",
        "score": "exact_choice_if_proven_else_external",
    },
    "fill_blank": {
        "interaction": "qti-text-entry-interaction",
        "cardinality": "single_per_blank",
        "score": "external",
    },
    "short_answer": {
        "interaction": "qti-extended-text-interaction",
        "cardinality": "single",
        "score": "external",
    },
    "written": {
        "interaction": "qti-extended-text-interaction",
        "cardinality": "single",
        "score": "external",
    },
}

REASON_CODES = frozenset(
    {
        "XML_UNSAFE_OR_INVALID",
        "XSD_BUNDLE_UNAVAILABLE",
        "XSD_BUNDLE_INVALID",
        "XSD_INVALID",
        "CANONICAL_INVALID",
        "INTERACTION_UNSUPPORTED",
        "CONTENT_PART_UNREPRESENTABLE",
        "PROMPT_ASSET_UNRESOLVED",
        "BODY_FLAT_PROJECTION_BLOCKED",
        "MATERIAL_HIERARCHY_UNREPRESENTABLE",
        "PROMPT_MEDIA_UNSUPPORTED",
        "PROMPT_IMAGE_MIME_UNSUPPORTED",
        "PROMPT_ASSET_PATH_INVALID",
        "IMAGE_DESCRIPTION_UNAVAILABLE",
        "BANK_OPTION_ID_UNSUPPORTED",
        "TRUE_FALSE_OPTION_UNSUPPORTED",
        "SCORING_AUTHORITY_UNPROVEN",
        "FILL_TRIM_NOT_PORTABLE",
        "EXTERNAL_SCORING_REQUIRED",
        "IDENTIFIER_COLLISION",
        "SCORING_PROGRAM_UNSUPPORTED",
        "ANSWERLESS_FILL_REVIEW",
        "ITEM_MAPPING_BLOCKED",
        "SOURCE_GUIDANCE_UNTRUSTED",
        "FILL_MAPPING_CONFLICT",
        "FILL_POLICY_UNPROVEN",
        "FILL_XML_TEXT_UNREPRESENTABLE",
    }
)


def diagnostic(code: str, message: str, *, location: str = "", severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message, "location": location}
