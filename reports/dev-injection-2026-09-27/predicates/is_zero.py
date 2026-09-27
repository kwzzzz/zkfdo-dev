API_VERSION = 1


def evaluate(context):
    modulus = int(context["field_modulus_decimal"])
    config = context["predicate_config"]
    signals = context["wire_signals"]
    value = int(signals[config["input"]])
    input_ok = 0 <= value < modulus
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
    holds = int(signals[config["output"]]) == int(value == 0)
    result["specified_property_violation"] = {
        "verdict": "not-satisfied" if holds else "satisfied",
        "reason_code": "property-holds" if holds else "property-violated",
    }
    if not holds:
        result["specified_property_violation"]["violation_class"] = "zero-test-output-mismatch"
    return result
