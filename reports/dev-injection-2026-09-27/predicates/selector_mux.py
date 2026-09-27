API_VERSION = 1


def evaluate(context):
    modulus = int(context["field_modulus_decimal"])
    config = context["predicate_config"]
    signals = context["wire_signals"]
    selector = int(signals[config["selector"]])
    choices = [int(signals[name]) for name in config["choices"]]
    input_ok = selector in (0, 1) and all(0 <= value < modulus for value in choices)
    result = {
        "input_preconditions": {
            "verdict": "satisfied" if input_ok else "not-satisfied",
            "reason_code": "contract-satisfied" if input_ok else "selector-not-boolean",
        }
    }
    if not input_ok:
        result["specified_property_violation"] = {
            "verdict": "unknown",
            "reason_code": "input-precondition-unresolved",
        }
        return result
    expected = (choices[0] * selector + choices[1] * (1 - selector)) % modulus
    holds = int(signals[config["output"]]) == expected
    result["specified_property_violation"] = {
        "verdict": "not-satisfied" if holds else "satisfied",
        "reason_code": "property-holds" if holds else "property-violated",
    }
    if not holds:
        result["specified_property_violation"]["violation_class"] = "selected-output-mismatch"
    return result
