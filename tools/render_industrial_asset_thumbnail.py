#!/usr/bin/env python3
"""Render a deterministic, offline thumbnail from an industrial-asset GLB."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image, ImageChops
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
THREE_ROOT = ROOT / "static" / "vendor" / "three" / "0.184.0"
THREE_MODULE = THREE_ROOT / "build" / "three.module.min.js"
GLTF_LOADER = THREE_ROOT / "examples" / "jsm" / "loaders" / "GLTFLoader.js"
THREE_MANIFEST = THREE_ROOT / "VERSIONS.md"
DEFAULT_EDGE = Path(
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)
DEFAULT_WIDTH = 768
DEFAULT_HEIGHT = 576
DEFAULT_BACKGROUND = "#e8edf2"
DEFAULT_CAMERA_DIRECTION = (1.0, 0.72, 1.0)
DEFAULT_FOV_DEGREES = 35.0
DEFAULT_MAX_INPUT_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MIN_DIMENSION = 128
MAX_DIMENSION = 2048
INPUT_ENDPOINT = "/__industrial_thumbnail_input__.glb"
PAGE_ENDPOINT = "/__industrial_thumbnail_renderer__.html"


class ThumbnailRenderError(RuntimeError):
    """Raised when an input cannot produce a trustworthy thumbnail."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def validate_glb_container(
    path: Path,
    *,
    maximum_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ThumbnailRenderError(f"GLB input does not exist: {path}")
    byte_length = resolved.stat().st_size
    if byte_length < 20:
        raise ThumbnailRenderError("GLB input is too short to contain a JSON chunk")
    if byte_length > maximum_input_bytes:
        raise ThumbnailRenderError(
            f"GLB input exceeds the {maximum_input_bytes}-byte limit"
        )

    with resolved.open("rb") as handle:
        header = handle.read(20)
    magic, version, declared_length, json_length, json_type = struct.unpack(
        "<4sIIII", header
    )
    if magic != b"glTF":
        raise ThumbnailRenderError("GLB input has an invalid magic header")
    if version != 2:
        raise ThumbnailRenderError(f"Unsupported GLB version: {version}")
    if declared_length != byte_length:
        raise ThumbnailRenderError(
            "GLB declared length does not match the input byte length"
        )
    if json_type != 0x4E4F534A:
        raise ThumbnailRenderError("GLB first chunk is not JSON")
    if json_length <= 0 or 20 + json_length > byte_length:
        raise ThumbnailRenderError("GLB JSON chunk length is invalid")

    return {
        "path": resolved,
        "byteLength": byte_length,
        "sha256": sha256_file(resolved),
        "version": version,
    }


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    normalized = value.strip().lower()
    if len(normalized) != 7 or not normalized.startswith("#"):
        raise ThumbnailRenderError("Background must use #rrggbb notation")
    try:
        channels = tuple(
            int(normalized[index : index + 2], 16) for index in (1, 3, 5)
        )
    except ValueError as error:
        raise ThumbnailRenderError(
            "Background must use #rrggbb notation"
        ) from error
    return channels  # type: ignore[return-value]


def _normalize_direction(values: tuple[float, float, float]) -> tuple[float, ...]:
    if not all(math.isfinite(value) for value in values):
        raise ThumbnailRenderError("Camera direction must be finite")
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude <= 1e-9:
        raise ThumbnailRenderError("Camera direction cannot be zero")
    return tuple(value / magnitude for value in values)


def _renderer_html(config: dict[str, Any]) -> bytes:
    encoded_config = json.dumps(
        config, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InspectorPro Industrial Asset Thumbnail Renderer</title>
  <link rel="icon" href="data:,">
  <style>
    html, body {{ margin: 0; overflow: hidden; background: {config["background"]}; }}
    canvas {{ display: block; width: {config["width"]}px; height: {config["height"]}px; }}
  </style>
  <script type="importmap">
    {{
      "imports": {{
        "three": "/static/vendor/three/0.184.0/build/three.module.min.js",
        "three/addons/": "/static/vendor/three/0.184.0/examples/jsm/"
      }}
    }}
  </script>
</head>
<body>
  <canvas id="viewport"></canvas>
  <script type="module">
    import * as THREE from "three";
    import {{ GLTFLoader }} from "three/addons/loaders/GLTFLoader.js";

    const config = {encoded_config};
    const output = {{
      state: "running",
      threeRevision: THREE.REVISION,
      meshCount: 0,
      primitiveCount: 0,
      triangleCount: 0,
      renderCalls: 0
    }};
    window.__industrialThumbnailResult = output;

    function finiteVector(vector) {{
      return [vector.x, vector.y, vector.z].every(Number.isFinite);
    }}

    async function render() {{
      const loader = new GLTFLoader();
      const gltf = await loader.loadAsync("{INPUT_ENDPOINT}");
      const root = gltf && gltf.scene;
      if (!root) throw new Error("GLB_SCENE_MISSING");

      root.updateMatrixWorld(true);
      root.traverse((object) => {{
        if (!object.isMesh || !object.geometry) return;
        const position = object.geometry.getAttribute("position");
        if (!position || position.count < 3) return;
        output.meshCount += 1;
        output.primitiveCount += object.geometry.groups.length || 1;
        const elementCount = object.geometry.index
          ? object.geometry.index.count
          : position.count;
        output.triangleCount += Math.floor(elementCount / 3);
      }});
      if (output.meshCount < 1 || output.triangleCount < 1) {{
        throw new Error("GLB_HAS_NO_RENDERABLE_TRIANGLES");
      }}

      const bounds = new THREE.Box3().setFromObject(root, true);
      if (bounds.isEmpty()) throw new Error("GLB_BOUNDS_EMPTY");
      const center = bounds.getCenter(new THREE.Vector3());
      const size = bounds.getSize(new THREE.Vector3());
      const sphere = bounds.getBoundingSphere(new THREE.Sphere());
      if (
        !finiteVector(bounds.min) ||
        !finiteVector(bounds.max) ||
        !finiteVector(center) ||
        !finiteVector(size) ||
        !Number.isFinite(sphere.radius) ||
        sphere.radius <= 1e-9
      ) {{
        throw new Error("GLB_BOUNDS_INVALID");
      }}

      const canvas = document.getElementById("viewport");
      canvas.width = config.width;
      canvas.height = config.height;
      const renderer = new THREE.WebGLRenderer({{
        canvas,
        antialias: true,
        alpha: false,
        preserveDrawingBuffer: true,
        powerPreference: "high-performance"
      }});
      renderer.setPixelRatio(1);
      renderer.setSize(config.width, config.height, false);
      renderer.setClearColor(config.background, 1);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.05;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(config.background);
      scene.add(root);

      const aspect = config.width / config.height;
      const camera = new THREE.PerspectiveCamera(
        config.fovDegrees,
        aspect,
        0.001,
        1000000
      );
      const halfVertical = THREE.MathUtils.degToRad(config.fovDegrees / 2);
      const halfHorizontal = Math.atan(Math.tan(halfVertical) * aspect);
      const limitingHalfAngle = Math.min(halfVertical, halfHorizontal);
      const distance = sphere.radius / Math.sin(limitingHalfAngle) * 1.12;
      const direction = new THREE.Vector3(...config.cameraDirection).normalize();
      camera.position.copy(center).addScaledVector(direction, distance);
      camera.up.set(0, 1, 0);
      camera.near = Math.max(sphere.radius / 1000, distance - sphere.radius * 1.5);
      camera.far = distance + sphere.radius * 3;
      if (camera.near >= camera.far) {{
        camera.near = Math.max(sphere.radius / 1000, 0.0001);
      }}
      camera.lookAt(center);
      camera.updateProjectionMatrix();

      const hemisphere = new THREE.HemisphereLight(0xffffff, 0x66717c, 2.0);
      scene.add(hemisphere);
      const key = new THREE.DirectionalLight(0xffffff, 3.0);
      key.position.copy(center).add(
        new THREE.Vector3(
          sphere.radius * 3,
          sphere.radius * 4,
          sphere.radius * 3
        )
      );
      scene.add(key);
      const fill = new THREE.DirectionalLight(0xb9d9ee, 1.8);
      fill.position.copy(center).add(
        new THREE.Vector3(
          -sphere.radius * 4,
          sphere.radius * 2,
          -sphere.radius * 2
        )
      );
      scene.add(fill);
      const rim = new THREE.DirectionalLight(0xffffff, 1.2);
      rim.position.copy(center).add(
        new THREE.Vector3(
          sphere.radius,
          sphere.radius * 3,
          -sphere.radius * 4
        )
      );
      scene.add(rim);

      if (typeof renderer.compileAsync === "function") {{
        await renderer.compileAsync(scene, camera);
      }}
      renderer.render(scene, camera);
      await new Promise((resolve) => requestAnimationFrame(resolve));
      renderer.render(scene, camera);

      output.bounds = {{
        min: bounds.min.toArray(),
        max: bounds.max.toArray(),
        center: center.toArray(),
        size: size.toArray(),
        radius: sphere.radius
      }};
      output.camera = {{
        position: camera.position.toArray(),
        target: center.toArray(),
        direction: direction.toArray(),
        fovDegrees: config.fovDegrees,
        near: camera.near,
        far: camera.far
      }};
      output.renderCalls = renderer.info.render.calls;
      output.renderedTriangles = renderer.info.render.triangles;
      output.canvas = {{
        width: canvas.width,
        height: canvas.height
      }};
      output.state = "complete";
      document.documentElement.dataset.renderState = "complete";
    }}

    render().catch((error) => {{
      output.state = "error";
      output.error = String(error && error.message ? error.message : error);
      document.documentElement.dataset.renderState = "error";
    }});
  </script>
</body>
</html>
"""
    return document.encode("ascii")


def _make_handler(
    *,
    renderer_page: bytes,
) -> type[SimpleHTTPRequestHandler]:
    class RendererHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def log_message(self, _format: str, *args: object) -> None:
            return

        def _send_bytes(self, payload: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == PAGE_ENDPOINT:
                self._send_bytes(renderer_page, "text/html; charset=ascii")
                return
            super().do_GET()

    return RendererHandler


def _find_browser_executable(
    playwright: Any,
    explicit_path: Path | None,
) -> Path | None:
    if explicit_path is not None:
        resolved = explicit_path.expanduser().resolve()
        if not resolved.is_file():
            raise ThumbnailRenderError(
                f"Browser executable not found: {explicit_path}"
            )
        return resolved

    configured = os.getenv("INSPECTORPRO_BROWSER_PATH", "").strip()
    candidates = [
        Path(configured) if configured else None,
        DEFAULT_EDGE,
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(playwright.chromium.executable_path),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise ThumbnailRenderError(
        "No local Chromium browser is available; install Playwright Chromium "
        "or set INSPECTORPRO_BROWSER_PATH"
    )


def _image_metrics(
    image: Image.Image,
    *,
    background_rgb: tuple[int, int, int],
) -> dict[str, Any]:
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, background_rgb)
    difference = ImageChops.difference(rgb, background)
    red, green, blue = difference.split()
    maximum_difference = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    mask = maximum_difference.point(lambda value: 255 if value > 10 else 0)
    histogram = mask.histogram()
    changed_pixels = histogram[255]
    total_pixels = rgb.width * rgb.height
    changed_fraction = changed_pixels / total_pixels
    extrema = rgb.getextrema()
    channel_span = max(high for _, high in extrema) - min(
        low for low, _ in extrema
    )
    changed_bounds = mask.getbbox()
    return {
        "backgroundRgb": list(background_rgb),
        "changedPixelBounds": list(changed_bounds) if changed_bounds else None,
        "changedPixelCount": changed_pixels,
        "changedPixelFraction": round(changed_fraction, 8),
        "channelSpan": channel_span,
        "nonblank": (
            changed_pixels >= max(256, int(total_pixels * 0.0025))
            and changed_fraction <= 0.92
            and channel_span >= 24
        ),
    }


def _publish_image(
    source_png: Path,
    output_path: Path,
    *,
    maximum_output_bytes: int,
) -> dict[str, Any]:
    suffix = output_path.suffix.lower()
    if suffix not in {".png", ".webp"}:
        raise ThumbnailRenderError("Output path must end in .png or .webp")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with Image.open(source_png) as source:
            source.load()
            image = source.convert("RGB")
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        if suffix == ".png":
            image.save(temporary, format="PNG", optimize=False, compress_level=9)
            media_type = "image/png"
        else:
            image.save(
                temporary,
                format="WEBP",
                lossless=True,
                method=6,
                exact=True,
            )
            media_type = "image/webp"
        byte_length = temporary.stat().st_size
        if byte_length <= 0 or byte_length > maximum_output_bytes:
            raise ThumbnailRenderError(
                f"Thumbnail output violates the {maximum_output_bytes}-byte limit"
            )
        with Image.open(temporary) as verification:
            verification.load()
            if verification.size != image.size:
                raise ThumbnailRenderError(
                    "Thumbnail dimensions changed during encoding"
                )
            if verification.format not in {"PNG", "WEBP"}:
                raise ThumbnailRenderError("Thumbnail encoding is invalid")
        os.replace(temporary, output_path)
        temporary = None
        return {
            "artifactName": output_path.name,
            "byteLength": output_path.stat().st_size,
            "height": image.height,
            "mediaType": media_type,
            "sha256": sha256_file(output_path),
            "width": image.width,
        }
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def render_industrial_asset_thumbnail(
    input_path: Path,
    output_path: Path,
    *,
    evidence_path: Path | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    background: str = DEFAULT_BACKGROUND,
    camera_direction: tuple[float, float, float] = DEFAULT_CAMERA_DIRECTION,
    fov_degrees: float = DEFAULT_FOV_DEGREES,
    maximum_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    maximum_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    browser_path: Path | None = None,
    timeout_ms: int = 120_000,
) -> dict[str, Any]:
    if not MIN_DIMENSION <= width <= MAX_DIMENSION:
        raise ThumbnailRenderError(
            f"Width must be between {MIN_DIMENSION} and {MAX_DIMENSION}"
        )
    if not MIN_DIMENSION <= height <= MAX_DIMENSION:
        raise ThumbnailRenderError(
            f"Height must be between {MIN_DIMENSION} and {MAX_DIMENSION}"
        )
    if not math.isfinite(fov_degrees) or not 15 <= fov_degrees <= 70:
        raise ThumbnailRenderError("Field of view must be between 15 and 70 degrees")
    background_rgb = _parse_hex_color(background)
    normalized_direction = _normalize_direction(camera_direction)
    source = validate_glb_container(
        input_path, maximum_input_bytes=maximum_input_bytes
    )
    resolved_output = output_path.expanduser().resolve()
    if resolved_output == source["path"]:
        raise ThumbnailRenderError("Input and output paths must differ")

    required = (THREE_MODULE, GLTF_LOADER, THREE_MANIFEST)
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise ThumbnailRenderError(
            f"Pinned offline renderer dependencies are missing: {missing}"
        )

    render_config = {
        "background": background.lower(),
        "cameraDirection": list(normalized_direction),
        "fovDegrees": float(fov_degrees),
        "height": height,
        "width": width,
    }
    renderer_page = _renderer_html(render_config)
    handler = _make_handler(renderer_page=renderer_page)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="industrial-thumbnail-renderer",
        daemon=True,
    )
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    url = f"{origin}{PAGE_ENDPOINT}"
    input_url = f"{origin}{INPUT_ENDPOINT}"

    blocked_external: list[str] = []
    failed_responses: list[dict[str, Any]] = []
    failed_requests: list[dict[str, Any]] = []
    page_errors: list[str] = []
    console_errors: list[str] = []
    finished_requests: list[dict[str, str]] = []
    validated_blocked_external: list[str] = []
    validated_failed_responses: list[dict[str, Any]] = []
    validated_failed_requests: list[dict[str, Any]] = []
    validated_page_errors: list[str] = []
    validated_console_errors: list[str] = []
    validated_finished_requests: list[dict[str, str]] = []
    render_result: dict[str, Any] = {}
    browser_version = ""

    try:
        with tempfile.TemporaryDirectory(prefix="ip-thumbnail-") as temp_directory:
            screenshot_path = Path(temp_directory) / "render.png"
            with sync_playwright() as playwright:
                executable = _find_browser_executable(playwright, browser_path)
                browser = playwright.chromium.launch(
                    executable_path=str(executable) if executable else None,
                    headless=True,
                )
                browser_version = browser.version
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                    color_scheme="light",
                    reduced_motion="reduce",
                )

                def route_request(route: Any) -> None:
                    if route.request.url == input_url:
                        route.fulfill(
                            status=200,
                            path=str(source["path"]),
                            content_type="model/gltf-binary",
                            headers={
                                "Cache-Control": "no-store",
                                "X-Content-Type-Options": "nosniff",
                            },
                        )
                    elif route.request.url.startswith(origin):
                        route.continue_()
                    else:
                        blocked_external.append(route.request.url)
                        route.abort()

                context.route("**/*", route_request)
                page = context.new_page()
                page.on(
                    "response",
                    lambda response: (
                        failed_responses.append(
                            {"status": response.status, "url": response.url}
                        )
                        if response.status >= 400
                        else None
                    ),
                )
                page.on(
                    "requestfailed",
                    lambda request: failed_requests.append(
                        {
                            "failure": request.failure or "",
                            "method": request.method,
                            "url": request.url,
                        }
                    ),
                )
                page.on(
                    "requestfinished",
                    lambda request: finished_requests.append(
                        {
                            "method": request.method,
                            "url": request.url,
                        }
                    ),
                )
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        console_errors.append(message.text)
                        if message.type == "error"
                        else None
                    ),
                )
                try:
                    page.goto(url, wait_until="load", timeout=timeout_ms)
                    page.wait_for_function(
                        """() => {
                            const value = window.__industrialThumbnailResult;
                            return value && (
                                value.state === "complete" ||
                                value.state === "error"
                            );
                        }""",
                        timeout=timeout_ms,
                    )
                except PlaywrightTimeoutError as error:
                    raise ThumbnailRenderError(
                        "Timed out while rendering the GLB thumbnail"
                    ) from error
                render_result = page.evaluate(
                    "() => window.__industrialThumbnailResult"
                )
                if render_result.get("state") != "complete":
                    detail = render_result.get("error", "unknown renderer error")
                    raise ThumbnailRenderError(f"GLB rendering failed: {detail}")
                page.wait_for_load_state(
                    "networkidle",
                    timeout=min(timeout_ms, 10_000),
                )
                page.locator("#viewport").screenshot(
                    path=str(screenshot_path),
                    animations="disabled",
                    timeout=timeout_ms,
                )
                validated_blocked_external = list(blocked_external)
                validated_failed_responses = list(failed_responses)
                validated_failed_requests = list(failed_requests)
                validated_page_errors = list(page_errors)
                validated_console_errors = list(console_errors)
                validated_finished_requests = list(finished_requests)
                page.close()
                context.close()
                browser.close()

            if validated_blocked_external:
                raise ThumbnailRenderError(
                    "Renderer attempted to access a non-local resource"
                )
            if validated_failed_responses or validated_failed_requests:
                raise ThumbnailRenderError(
                    "Renderer encountered a failed local resource request: "
                    f"responses={validated_failed_responses!r}, "
                    f"requests={validated_failed_requests!r}"
                )
            if validated_page_errors or validated_console_errors:
                raise ThumbnailRenderError(
                    "Renderer reported a browser or console error"
                )
            if not any(
                request == {"method": "GET", "url": input_url}
                for request in validated_finished_requests
            ):
                raise ThumbnailRenderError(
                    "Validated GLB input transfer did not finish successfully"
                )
            if render_result.get("threeRevision") != "184":
                raise ThumbnailRenderError("Unexpected Three.js renderer revision")
            if render_result.get("canvas") != {
                "width": width,
                "height": height,
            }:
                raise ThumbnailRenderError("Renderer canvas dimensions are invalid")
            if int(render_result.get("meshCount", 0)) < 1:
                raise ThumbnailRenderError("GLB contains no renderable meshes")
            if int(render_result.get("triangleCount", 0)) < 1:
                raise ThumbnailRenderError("GLB contains no renderable triangles")

            with Image.open(screenshot_path) as screenshot:
                screenshot.load()
                if screenshot.size != (width, height):
                    raise ThumbnailRenderError(
                        "Browser screenshot dimensions are invalid"
                    )
                pixels = _image_metrics(
                    screenshot, background_rgb=background_rgb
                )
            if not pixels["nonblank"]:
                raise ThumbnailRenderError(
                    "Rendered thumbnail is blank or improperly framed"
                )
            output = _publish_image(
                screenshot_path,
                resolved_output,
                maximum_output_bytes=maximum_output_bytes,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    runner_hash = sha256_file(Path(__file__).resolve())
    module_hash = sha256_file(THREE_MODULE)
    loader_hash = sha256_file(GLTF_LOADER)
    render_plan = {
        "background": background.lower(),
        "cameraDirection": list(normalized_direction),
        "fovDegrees": float(fov_degrees),
        "height": height,
        "loaderSha256": loader_hash,
        "sourceSha256": source["sha256"],
        "threeModuleSha256": module_hash,
        "width": width,
    }
    checks = {
        "actualBoundsFinite": True,
        "boundedDimensions": MIN_DIMENSION <= width <= MAX_DIMENSION
        and MIN_DIMENSION <= height <= MAX_DIMENSION,
        "boundedOutputBytes": output["byteLength"] <= maximum_output_bytes,
        "geometryRenderable": int(render_result["triangleCount"]) >= 1,
        "inputTransferFinished": any(
            request == {"method": "GET", "url": input_url}
            for request in validated_finished_requests
        ),
        "localAssetsOnly": not validated_blocked_external,
        "nonblankPixels": pixels["nonblank"] is True,
        "pinnedThreeRevision": render_result["threeRevision"] == "184",
        "validGlb2": source["version"] == 2,
    }
    evidence = {
        "schemaVersion": "industrial-asset-thumbnail-evidence-v1",
        "checks": checks,
        "geometry": {
            "bounds": render_result["bounds"],
            "meshCount": render_result["meshCount"],
            "primitiveCount": render_result["primitiveCount"],
            "triangleCount": render_result["triangleCount"],
        },
        "network": {
            "externalRequestCount": len(validated_blocked_external),
            "failedRequestCount": len(validated_failed_requests),
            "failedResponseCount": len(validated_failed_responses),
            "offlineOnly": True,
        },
        "output": {
            **output,
            "pixelValidation": pixels,
        },
        "passed": all(checks.values()),
        "renderer": {
            "background": background.lower(),
            "browser": browser_version,
            "camera": render_result["camera"],
            "deviceScaleFactor": 1,
            "fovDegrees": float(fov_degrees),
            "gltfLoaderSha256": loader_hash,
            "renderCalls": render_result["renderCalls"],
            "renderPlanSha256": hashlib.sha256(
                canonical_json_bytes(render_plan)
            ).hexdigest(),
            "renderedTriangles": render_result["renderedTriangles"],
            "runnerSha256": runner_hash,
            "threeModuleSha256": module_hash,
            "threeRevision": render_result["threeRevision"],
        },
        "source": {
            "artifactName": source["path"].name,
            "byteLength": source["byteLength"],
            "containerVersion": source["version"],
            "sha256": source["sha256"],
        },
    }
    if evidence_path is not None:
        _atomic_write_bytes(
            evidence_path.expanduser().resolve(),
            canonical_json_bytes(evidence),
        )
    return evidence


def _parse_direction(value: str) -> tuple[float, float, float]:
    pieces = [piece.strip() for piece in value.split(",")]
    if len(pieces) != 3:
        raise argparse.ArgumentTypeError("Expected x,y,z")
    try:
        return tuple(float(piece) for piece in pieces)  # type: ignore[return-value]
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected numeric x,y,z") from error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render a bounded, nonblank industrial-asset thumbnail using only "
            "InspectorPro's pinned local Three.js runtime."
        )
    )
    parser.add_argument("input", type=Path, help="Local GLB 2.0 input")
    parser.add_argument("output", type=Path, help="Output .png or .webp")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--background", default=DEFAULT_BACKGROUND)
    parser.add_argument(
        "--camera-direction",
        type=_parse_direction,
        default=DEFAULT_CAMERA_DIRECTION,
        metavar="X,Y,Z",
    )
    parser.add_argument("--fov", type=float, default=DEFAULT_FOV_DEGREES)
    parser.add_argument(
        "--max-input-bytes",
        type=int,
        default=DEFAULT_MAX_INPUT_BYTES,
    )
    parser.add_argument(
        "--max-output-bytes",
        type=int,
        default=DEFAULT_MAX_OUTPUT_BYTES,
    )
    parser.add_argument("--browser-path", type=Path)
    parser.add_argument("--timeout-ms", type=int, default=120_000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        evidence = render_industrial_asset_thumbnail(
            args.input,
            args.output,
            evidence_path=args.evidence,
            width=args.width,
            height=args.height,
            background=args.background,
            camera_direction=args.camera_direction,
            fov_degrees=args.fov,
            maximum_input_bytes=args.max_input_bytes,
            maximum_output_bytes=args.max_output_bytes,
            browser_path=args.browser_path,
            timeout_ms=args.timeout_ms,
        )
    except (OSError, PlaywrightError, ThumbnailRenderError) as error:
        print(f"ERROR\t{error}", file=sys.stderr)
        return 1
    print(f"PASS\tnonblank_pixels={evidence['output']['pixelValidation']['changedPixelCount']}")
    print(f"PASS\ttriangles={evidence['geometry']['triangleCount']}")
    print(f"OUTPUT\t{args.output}")
    if args.evidence is not None:
        print(f"EVIDENCE\t{args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
