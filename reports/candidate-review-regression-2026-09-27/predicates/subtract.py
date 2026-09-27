API_VERSION = 1


def evaluate(context):
    modulus = int(context["field_modulus_decimal"])
    signals = context["wire_signals"]
    a = int(signals["main.a"])
    b = int(signals["main.b"])
    c = int(signals["main.c"])
    input_ok = 0 <= a < modulus and 0 <= b < modulus
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
    elif c != (a - b) % modulus:
        result["specified_property_violation"] = {
            "verdict": "satisfied",
            "reason_code": "property-violated",
            "violation_class": "subtraction-output-mismatch",
        }
    else:
        result["specified_property_violation"] = {
            "verdict": "not-satisfied",
            "reason_code": "property-holds",
        }
    return result
