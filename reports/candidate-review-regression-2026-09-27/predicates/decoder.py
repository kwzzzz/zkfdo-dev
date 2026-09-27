API_VERSION = 1


def evaluate(context):
    modulus = int(context["field_modulus_decimal"])
    signals = context["wire_signals"]
    inp = int(signals["main.inp"])
    input_ok = 0 <= inp < modulus
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
    outputs_match = all(
        int(signals[f"main.out[{index}]"]) == int(inp == index)
        for index in range(4)
    )
    success_matches = int(signals["main.success"]) == sum(
        int(signals[f"main.out[{index}]"]) for index in range(4)
    ) % modulus
    holds = outputs_match and success_matches
    result["specified_property_violation"] = {
        "verdict": "not-satisfied" if holds else "satisfied",
        "reason_code": "property-holds" if holds else "property-violated",
    }
    if not holds:
        result["specified_property_violation"]["violation_class"] = (
            "one-hot-output-equivalence" if not outputs_match else "success-sum"
        )
    return result
