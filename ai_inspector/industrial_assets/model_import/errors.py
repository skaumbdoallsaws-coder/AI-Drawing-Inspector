"""Stable public refusals; parser exceptions and source paths never reach chat."""

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
}


class ModelImportError(Exception):
    """MI1 translates this independent error into FacilityLayoutError."""

    def __init__(self, code: str):
        if code not in MESSAGES:
            raise ValueError("Unknown model import refusal")
        super().__init__(MESSAGES[code])
        self.code = code
        self.message = MESSAGES[code]
        self.status_code = (503 if code in {"model_limits_unavailable", "model_runtime_unavailable"}
                            else 413 if code in {"model_too_large", "zip_too_large"} else 422)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}
