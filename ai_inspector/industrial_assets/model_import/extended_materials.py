"""Opt-in builder metadata. The legacy import projection never calls this module."""
import re

from .validation import mapping, number, require


def _text(value):
    require(isinstance(value, str) and 0 < len(value) <= 120 and all(ord(c) >= 32 for c in value))
    return value


def read_extras(raw):
    extras = mapping(raw.get("extras", {}))
    result = {}
    if "facilityArtwork" in extras:
        require(type(extras["facilityArtwork"]) is bool)
        result["artwork"] = extras["facilityArtwork"]
    if "facilityFinishGroup" in extras:
        result["finishGroup"] = _text(extras["facilityFinishGroup"])
    if "facilityDefaultFinish" in extras:
        finish = {"appearanceId": _text(extras["facilityDefaultFinish"])}
        adjustments = mapping(extras.get("facilityDefaultFinishAdjustments", {}))
        require(set(adjustments) <= {"color", "roughness", "metalness"})
        for key, value in adjustments.items():
            if key == "color":
                require(isinstance(value, str) and re.fullmatch("#[0-9a-fA-F]{6}", value) is not None)
                finish[key] = value.lower()
            else:
                finish[key] = number(value, 0, 1)
        result["defaultFinish"] = finish
    else:
        require("facilityDefaultFinishAdjustments" not in extras)
    return result


def write_extras(material):
    result = {}
    if "defaultFinish" in material:
        finish = mapping(material["defaultFinish"])
        require(set(finish) <= {"appearanceId", "color", "roughness", "metalness"} and "appearanceId" in finish)
        result["facilityDefaultFinish"] = finish["appearanceId"]
        adjustments = {k: v for k, v in finish.items() if k != "appearanceId"}
        if adjustments:
            result["facilityDefaultFinishAdjustments"] = adjustments
    for source, target in (("artwork", "facilityArtwork"), ("finishGroup", "facilityFinishGroup")):
        if source in material:
            result[target] = material[source]
    read_extras({"extras": result})
    return result
