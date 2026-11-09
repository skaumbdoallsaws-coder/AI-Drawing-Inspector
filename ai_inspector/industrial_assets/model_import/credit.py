"""Deterministic change descriptions and factual, plain-text credit."""
from .licence import license_class
from .validation import clean_text


def changes_text(recipe):
    actions = []
    if any(recipe["rotate"].values()):
        actions.append("rotated x/y/z by " + "/".join(f"{recipe['rotate'][a]:g}" for a in "xyz") + " degrees")
    if recipe["pivot"] != "base":
        actions.append("aligned the base to selected parts")
    size = recipe["size"]
    if "meters" in size:
        actions.append(f"scaled {size['dimension']} to {size['meters']:g} m")
    elif size["scale"] != 1:
        actions.append(f"scaled by {size['scale']:g}")
    for rule in recipe["parts"]:
        selector = next(iter(rule["select"].items()))
        target = "all parts" if selector[0] == "all" else f"{selector[0]} {selector[1]}"
        details = []
        if rule["drop"]:
            details.append("removed")
        else:
            if "name" in rule:
                details.append("renamed to " + rule["name"])
            patch = rule["material"]
            if "color" in patch:
                details.append("colour " + patch["color"])
            if patch.get("texture") == "drop":
                details.append("plain material instead of texture")
            if patch.get("emissive") == "off":
                details.append("emission off")
            for key in ("alpha", "alphaCutoff", "doubleSided", "roughness", "metalness"):
                if key in patch:
                    details.append(f"{key} {patch[key]}")
            if rule["scale"] != 1:
                details.append(f"scaled by {rule['scale']:g}")
            if rule["turnDegrees"]:
                details.append(f"turned {rule['turnDegrees']:g} degrees")
            if "moveTo" in rule or any(rule.get("move", [])):
                details.append("moved to " + str(rule["moveTo"]) if "moveTo" in rule else "moved by " + str(rule["move"]))
        if details:
            actions.append(target + ": " + ", ".join(details))
    if len(recipe["copies"]) > 1 or recipe["copies"] != [{"x": 0, "z": 0, "scale": 1, "turnDegrees": 0}]:
        actions.append(f"{len(recipe['copies'])} positioned copies")
    if recipe["add"]:
        actions.append("added " + ", ".join(p["name"] for p in recipe["add"]))
    if recipe["surfaces"]:
        actions.append(f"{len(recipe['surfaces'])} authored support rectangles")
    actions.append(f"textures capped at {recipe['textureMaxPx']} px; centred and based at y=0")
    note = recipe["changesNote"]
    allowance = 600 - len(note) - (2 if note else 0)
    text = "; ".join(actions)
    if len(text) > allowance:
        text = clean_text(text, allowance - 3) + "..."
    return clean_text(text + ("; " + note if note else ""), 600)


def attribution(source, recipe, changes):
    result = {key: source.get(key, "") for key in ("title", "author", "authorUrl", "sourceUrl", "license", "licenseUrl")}
    result.update(licenseClass=source.get("class", "unknown"), statedBy="file", changes=changes)
    override = recipe.get("attribution")
    if override:
        result.update(override)
        if "licenseClass" not in override and ("license" in override or "licenseUrl" in override):
            # An override never inherits a more permissive class from the old facts.
            evidence = [license_class(result[k]) for k in ("license", "licenseUrl") if result[k]]
            result["licenseClass"] = evidence[0] if evidence and len(set(evidence)) == 1 else "unknown"
    return result


def credits_text(value):
    labels = (("title", "Title"), ("author", "Author"), ("authorUrl", "Author URL"),
              ("sourceUrl", "Source URL"), ("license", "License"), ("licenseUrl", "License URL"),
              ("licenseClass", "License class"), ("statedBy", "Stated by"), ("changes", "Changes"))
    return "".join(f"{label}: {value[key]}\n" for key, label in labels if value.get(key))
