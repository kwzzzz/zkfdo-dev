API_VERSION = 1


def evaluate(context):
    modulus = int(context["field_modulus_decimal"])
    signals = context["wire_signals"]
    depth = int(signals["main.depth"])
    leaf_depth = int(signals["main.leaf_depth"])
    input_ok = 0 <= depth < modulus and 0 <= leaf_depth < modulus
    result = {
        "input_preconditions": {
            "verdict": "satisfied" if input_ok else "not-satisfied",
            "reason_code": "contract-satisfied" if input_ok else "input-noncanonical",
        }
    }
    if not input_ok:
        result["specified_property_violation"] = {
            "verdict": "unknown",
            "reason_code": "input-precondition-unresolved",
        }
        return result
    if depth > 255 or leaf_depth > 255:
        result["specified_property_violation"] = {
            "verdict": "satisfied",
            "reason_code": "property-violated",
            "violation_class": "input-outside-required-8-bit-component-domain",
        }
        return result
    expected_root = 1 if depth == 0 else 0
    expected_parent = 1 if depth < leaf_depth - 1 else 0
    holds = (
        depth < leaf_depth
        and int(signals["main.is_root"]) == expected_root
        and int(signals["main.is_parent"]) == expected_parent
    )
    result["specified_property_violation"] = {
        "verdict": "not-satisfied" if holds else "satisfied",
        "reason_code": "property-holds" if holds else "property-violated",
    }
    if not holds:
        result["specified_property_violation"]["violation_class"] = (
            "in-range-order-or-output-relation"
        )
    return result
