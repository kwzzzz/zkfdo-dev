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
    boolean = all(
        int(signals[f"{config['output']}[{index}]"]) in (0, 1)
        for index in range(int(config["bits"]))
    )
    result["specified_property_violation"] = {
        "verdict": "not-satisfied" if boolean else "satisfied",
        "reason_code": "property-holds" if boolean else "property-violated",
    }
    if not boolean:
        result["specified_property_violation"]["violation_class"] = "non-boolean-output-bit"
    return result
