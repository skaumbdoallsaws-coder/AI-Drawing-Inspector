"""Stable public refusals with bounded, typed diagnostics for recipe repair."""

MESSAGES = {
    "model_format_unsupported": "Choose a GLB or a zip containing one glTF or GLB model.",
    "model_too_large": "The model exceeds the 128 MiB upload limit.",
    "zip_unsafe": "The zip contains unsafe, ambiguous, encrypted or unsupported entries.",
    "zip_too_large": "The zip exceeds the entry, expanded size or compression ratio limit.",
    "gltf_invalid": "The model contains invalid geometry, references or transforms.",
    "gltf_external_resource": "Resources must be local files inside the zip, not URLs or data URIs.",
    "gltf_extension_required": "A required glTF extension is unsupported. Export an uncompressed static glTF.",
    "gltf_feature_unsupported": "Skins, morph targets and sparse accessors are not supported yet.",
    "gltf_too_complex": "The model exceeds the geometry, scene graph or material limits.",
    "image_unsafe": "A model image is invalid, animated, unsupported or exceeds the image limits.",
    "model_empty": "The selected scene has no triangle geometry.",
    "model_limits_unavailable": "Model import could not enable its resource limits on this computer.",
    "model_runtime_unavailable": "Model import needs numpy and Pillow in the configured Python runtime.",
    "model_worker_failed": "The model worker stopped or returned an invalid result.",
    "model_timeout": "Model import exceeded its time limit. Try a smaller static model.",
    "model_cancelled": "Model import was cancelled.",
    "model_cache_invalid": "The prepared model cache is incomplete or invalid.",
    "recipe_invalid": "Check the recipe fields, ranges, support rectangles and vessel wall thickness.",
    "recipe_selector_empty": "A part selector matched nothing. Use a listed key or exact source name.",
    "model_output_too_complex": "The result exceeds 250,000 triangles. Drop parts or use fewer copies.",
    "model_output_too_large": "The prepared GLB exceeds 30 MiB. Drop parts or reduce textures.",
    "model_dimensions_invalid": "The result must have positive width, height and depth and finite practical dimensions.",
    "model_destination_exists": "The draft destination already exists; choose a new draft folder.",
}


class ModelImportError(Exception):
    """MI1 translates this independent error into FacilityLayoutError."""

    def __init__(self, code: str, details: dict | None = None):
        if code not in MESSAGES:
            raise ValueError("Unknown model import refusal")
        if details is not None and not valid_details(code, details):
            raise ValueError("Invalid model import diagnostic")
        super().__init__(MESSAGES[code])
        self.code = code
        self.message = MESSAGES[code]
        self.details = details
        self.status_code = (503 if code in {"model_limits_unavailable", "model_runtime_unavailable"}
                            else 413 if code in {"model_too_large", "zip_too_large", "model_output_too_large"} else 422)

    def to_dict(self) -> dict:
        result = {"code": self.code, "message": self.message}
        if self.details is not None:
            result["details"] = self.details
        return result


def valid_details(code, details):
    # Kept dependency-free to avoid the validation -> errors import cycle.
    def text(value, maximum):
        return isinstance(value, str) and len(value) <= maximum and not any(ord(c) < 32 for c in value)
    if not isinstance(details, dict):
        return False
    if code == "recipe_selector_empty":
        return (set(details) == {"selector", "closest"} and text(details["selector"], 100)
                and isinstance(details["closest"], list) and len(details["closest"]) <= 4
                and all(text(v, 80) for v in details["closest"]))
    if code == "model_output_too_complex":
        return (set(details) == {"triangles", "largestParts"} and type(details["triangles"]) is int
                and 250000 < details["triangles"] <= 30_000_000
                and isinstance(details["largestParts"], list) and len(details["largestParts"]) <= 5
                and all(isinstance(v, dict) and set(v) == {"key", "name", "triangles"}
                        and text(v["key"], 80) and text(v["name"], 80) and type(v["triangles"]) is int
                        and 0 <= v["triangles"] <= 30_000_000 for v in details["largestParts"]))
    return False
