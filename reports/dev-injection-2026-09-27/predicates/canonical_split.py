API_VERSION = 1


def evaluate(context):
    modulus = int(context["field_modulus_decimal"])
    config = context["predicate_config"]
    signals = context["wire_signals"]
    low_bits = int(config["low_bits"])
    high_bits = int(config["high_bits"])
    value = int(signals[config["input"]])
    input_ok = 0 <= value < modulus and value < (1 << (low_bits + high_bits))
    result = {
        "input_preconditions": {
            "verdict": "satisfied" if input_ok else "not-satisfied",
            "reason_code": "contract-satisfied" if input_ok else "input-out-of-range",
        }
    }
    if not input_ok:
        result["specified_property_violation"] = {
            "verdict": "unknown",
            "reason_code": "input-precondition-unresolved",
        }
        return result
    small = int(signals[config["small"]])
    big = int(signals[config["big"]])
    holds = small < (1 << low_bits) and big < (1 << high_bits) and small + (big << low_bits) == value
    result["specified_property_violation"] = {
        "verdict": "not-satisfied" if holds else "satisfied",
        "reason_code": "property-holds" if holds else "property-violated",
    }
    if not holds:
        result["specified_property_violation"]["violation_class"] = "non-canonical-limb-split"
    return result
