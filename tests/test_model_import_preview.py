"""Pixel-level preview contracts, worker publication and full-sheet timing gates."""
from io import BytesIO
import json
import os
import time

import numpy as np
from PIL import Image, ImageDraw
import pytest

from tests.model_import_test_support import image_bytes, module, textured_box

preview = module("preview")
raster = module("preview_raster")
geometry = module("preview_geometry")
model_types = module("model")
materials = module("materials")


def quad(*, color=(1, 1, 1, 1), texture=None, alpha="OPAQUE", emission=(0, 0, 0), unlit=True, z=0):
    material = materials.default_material()
    material.update(name="quad", baseColor=list(color), alphaMode=alpha, emissive=list(emission), unlit=unlit)
    images = []
    if texture is not None:
        with Image.open(BytesIO(texture)) as image:
            size = image.size
        images = [model_types.ModelImage(texture, "image/png", *size, *size)]
        material["texture"] = {"image": 0, "wrapS": 33071, "wrapT": 33071,
                               "offset": [0, 0], "scale": [1, 1], "rotation": 0}
    part = model_types.Part("p0", "quad", "quad", "quad", 0,
        np.array([[-.5, 0, z], [.5, 0, z], [.5, 1, z], [-.5, 1, z]], dtype=np.float32),
        np.tile(np.array([[0, 0, 1]], dtype=np.float32), (4, 1)),
        np.array([[0, 1], [1, 1], [1, 0], [0, 0]], dtype=np.float32),
        np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32))
    return model_types.Model("quad", "glb", 1, "0" * 64, "test", [part], [material], images,
                             module("licence").parse_licence([], {}))


def quadrant_texture(mask=False):
    pixels = np.zeros((16, 16, 4), dtype=np.uint8)
    pixels[:8, :8] = [255, 0, 0, 0 if mask else 255]
    pixels[:8, 8:] = [0, 255, 0, 255]
    pixels[8:, :8] = [0, 0, 255, 255]
    pixels[8:, 8:] = [255, 255, 0, 255]
    with Image.fromarray(pixels) as image, BytesIO() as stream:
        image.save(stream, format="PNG")
        return stream.getvalue()


def test_contact_sheet_thumbnail_format_size_and_nonempty():
    result = preview.render_previews(quad(texture=quadrant_texture()))
    assert len(result.preview) <= preview.PREVIEW_BYTES
    assert len(result.thumbnail) <= preview.THUMBNAIL_BYTES
    for payload, size, format in ((result.preview, (768, 768), "PNG"), (result.thumbnail, (256, 256), "WEBP")):
        with Image.open(BytesIO(payload)) as image:
            assert image.size == size and image.format == format
            assert np.array(image.convert("RGB")).std() > 10
    module("pictures").validate_picture(result.preview, "preview")
    module("pictures").validate_picture(result.thumbnail, "thumbnail")
    assert result.triangles_shown == result.triangles_total == 2


def test_barycentric_texture_quadrants_are_in_expected_places():
    pixels = preview.render_view(quad(texture=quadrant_texture()), size=128, grid=False)
    for y, x, color in ((41, 41, [255, 0, 0]), (41, 87, [0, 255, 0]),
                        (87, 41, [0, 0, 255]), (87, 87, [255, 255, 0])):
        np.testing.assert_allclose(pixels[y, x], color, atol=1)


def test_texture_srgb_is_linear_before_shading_and_reencoded():
    model = quad(texture=image_bytes(mode="RGB", color=(128, 128, 128)), unlit=False)
    pixels = preview.render_view(model, size=128, grid=False)
    light = raster.AMBIENT + raster.DIFFUSE * raster.LIGHT[2]
    expected = raster.to_srgb(raster.LINEAR[128] * np.ones(3) * light)
    np.testing.assert_allclose(pixels[48, 48], expected, atol=1)


def test_mask_holes_reveal_background_and_opaque_ignores_alpha():
    texture = quadrant_texture(mask=True)
    pixels = preview.render_view(quad(texture=texture, alpha="MASK"), size=128, grid=False)
    np.testing.assert_array_equal(pixels[41, 41], raster.BACKGROUND)
    np.testing.assert_array_equal(pixels[41, 87], [0, 255, 0])
    opaque = preview.render_view(quad(texture=texture), size=128, grid=False)
    np.testing.assert_array_equal(opaque[41, 41], [255, 0, 0])


def test_mask_cutoff_and_factor_alpha_are_honored():
    model = quad(color=(1, 0, 0, .4), alpha="MASK")
    hidden = preview.render_view(model, size=128, grid=False)
    np.testing.assert_array_equal(hidden[48, 48], raster.BACKGROUND)
    model.materials[0]["alphaCutoff"] = .3
    shown = preview.render_view(model, size=128, grid=False)
    np.testing.assert_array_equal(shown[48, 48], [255, 0, 0])


def test_emissive_brightens_and_back_faces_are_drawn():
    model = quad(color=(.1, .1, .1, 1), unlit=False)
    dark = preview.render_view(model, size=128, grid=False)
    model.materials[0]["emissive"] = [.3, .3, .3]
    bright = preview.render_view(model, size=128, grid=False)
    assert np.all(bright[48, 48] > dark[48, 48])
    model.parts[0].indices = model.parts[0].indices[:, ::-1].copy()
    back = preview.render_view(model, size=128, grid=False)
    np.testing.assert_array_equal(back, bright)  # No culling, even with doubleSided=False.


def test_blend_uses_linear_alpha_and_shared_edge_is_not_drawn_twice():
    model = quad(color=(1, 0, 0, .5), alpha="BLEND")
    pixels = preview.render_view(model, size=128, grid=False)
    expected = raster.to_srgb(.5 * np.array([1, 0, 0]) + .5 * raster.LINEAR[np.array(raster.BACKGROUND)])
    # One point is exactly on the two triangles' common diagonal.
    for y, x in ((64, 63), (48, 48), (64, 64)):
        np.testing.assert_allclose(pixels[y, x], expected, atol=1)


def layered():
    far = quad(color=(1, 0, 0, .5), alpha="BLEND", z=0)
    near = quad(color=(0, 0, 1, .5), alpha="BLEND", z=.1)
    near.parts[0].material = 1
    near.parts[0].key = "p1"
    far.parts += near.parts
    far.materials += near.materials
    return far


def test_transparent_layers_are_far_to_near_after_opaque():
    model = layered()
    result = preview.render_view(model, size=128, grid=False)
    background = raster.LINEAR[np.array(raster.BACKGROUND)]
    expected = raster.to_srgb(np.array([0, 0, 1]) * .5 + (.5 * np.array([1, 0, 0]) + background * .5) * .5)
    np.testing.assert_allclose(result[48, 48], expected, atol=1)
    model.parts.reverse()
    np.testing.assert_array_equal(preview.render_view(model, size=128, grid=False), result)
    opaque = quad(color=(0, 1, 0, 1), z=.2)
    opaque.parts[0].material = 2
    model.parts += opaque.parts
    model.materials += opaque.materials
    np.testing.assert_array_equal(preview.render_view(model, size=128, grid=False)[48, 48], [0, 255, 0])


def test_vectorized_splats_depth_mask_and_blend():
    points = np.array([[10.2, 10.2, 2], [10.2, 10.2, 1], [11.2, 10.2, 0]], dtype=np.float32)
    colors = np.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]], dtype=np.float32)
    rgb = np.ones((16, 16, 3), dtype=np.float32)
    nearest = np.full((16, 16), np.inf, dtype=np.float32)
    raster._splat(np.arange(3), points, colors, np.array([1, 1, 0]), rgb, nearest, False)
    np.testing.assert_array_equal(rgb[10, 10], [0, 0, 1])
    np.testing.assert_array_equal(rgb[10, 11], [1, 1, 1])  # Mask discarded before depth selection.
    rgb[:] = 1
    nearest[:] = np.inf
    raster._splat(np.array([0, 1]), points, colors, np.array([.5, .5, 0]), rgb, nearest, True)
    np.testing.assert_allclose(rgb[10, 10], [.5, .25, .75], atol=1e-7)


def test_texture_wrap_modes_and_uv_transform_not_applied_again():
    model = quad(texture=quadrant_texture())
    cache = raster.TextureCache(model.images)
    texture = model.materials[0]["texture"]
    # UV transforms are already baked by the reader, so this metadata is not reapplied.
    texture["offset"], texture["scale"] = [.4, .4], [2, 2]
    for mode, coordinate, color in ((10497, [1.25, .25], [1, 0, 0]),
                                     (33648, [1.25, .25], [0, 1, 0]),
                                     (33071, [-.25, .25], [1, 0, 0])):
        texture["wrapS"] = mode
        sampled, _ = raster.sample_texture(cache, texture, np.array([coordinate], dtype=np.float32))
        np.testing.assert_allclose(sampled[0], color, atol=1e-7)


@pytest.mark.parametrize("size", [.01, 30])
def test_grid_and_dimension_labels_at_small_and_large_scales(size, monkeypatch):
    model = quad()
    model.parts[0].positions *= size
    labels, original = [], ImageDraw.ImageDraw.text
    def capture(self, xy, text, *args, **kwargs):
        labels.append(text)
        return original(self, xy, text, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    result = preview.render_previews(model, source=True)
    assert len(result.preview) <= preview.PREVIEW_BYTES
    assert any("preview (approximate)" in label for label in labels)
    assert any(f"W {size:.4g} m" in label for label in labels)
    assert all(any(name == label for label in labels) for name, _ in preview.VIEWS)


def test_largest_area_source_selection_and_limit_label(monkeypatch):
    model = quad()
    base = model.parts[0]
    # Three disjoint triangles of increasing area.
    base.positions = np.array([[0, 0, 0], [.1, 0, 0], [0, .1, 0],
                               [0, 0, 0], [.5, 0, 0], [0, .5, 0],
                               [0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    base.indices = np.arange(9, dtype=np.uint32).reshape(-1, 3)
    base.normals = None
    base.uv0 = None
    built = geometry.build_geometry(model, maximum=2)
    assert built.total == 3 and built.shown == 2
    areas = np.linalg.norm(np.cross(built.corners[:, 1] - built.corners[:, 0],
                                   built.corners[:, 2] - built.corners[:, 0]), axis=1)
    np.testing.assert_allclose(areas, [.25, 1])
    monkeypatch.setattr(preview, "build_geometry", lambda value: geometry.build_geometry(value, maximum=2))
    labels, original = [], ImageDraw.ImageDraw.text
    def capture(self, xy, text, *args, **kwargs):
        labels.append(text)
        return original(self, xy, text, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    rendered = preview.render_previews(model, source=True)
    assert rendered.triangles_shown == 2
    assert any("largest 250k triangles shown" in label for label in labels)


def grid_model(columns, rows):
    model = quad(color=(.15, .5, .25, 1), unlit=False)
    xx, yy = np.meshgrid(np.linspace(-.5, .5, columns + 1), np.linspace(0, 1, rows + 1))
    model.parts[0].positions = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(xx.size))).astype(np.float32)
    a = (np.arange(rows)[:, None] * (columns + 1) + np.arange(columns)[None, :]).ravel()
    b, c, d = a + 1, a + columns + 2, a + columns + 1
    model.parts[0].indices = np.stack((np.column_stack((a, b, c)), np.column_stack((a, c, d))),
                                     axis=1).reshape(-1, 3).astype(np.uint32)
    model.parts[0].normals = None
    model.parts[0].uv0 = None
    return model


@pytest.mark.skipif(os.environ.get("MODEL_IMPORT_SKIP_TIMING") == "1", reason="timing explicitly disabled")
@pytest.mark.parametrize("columns,rows,seconds", [(50, 50, 2), (500, 250, 20)])
def test_full_contact_sheet_timing(columns, rows, seconds):
    model = grid_model(columns, rows)
    started = time.perf_counter()
    rendered = preview.render_previews(model)
    elapsed = time.perf_counter() - started
    assert rendered.triangles_shown == columns * rows * 2
    assert elapsed <= seconds, f"{rendered.triangles_shown} triangles took {elapsed:.3f}s, limit {seconds}s"


def test_full_source_cap_and_stable_area_ties():
    model = grid_model(501, 250)  # 250,500 triangles
    first = geometry.build_geometry(model)
    second = geometry.build_geometry(model)
    assert first.total == 250500 and first.shown == 250000
    np.testing.assert_array_equal(first.corners, second.corners)


def test_worker_tasks_publish_and_validate_picture_files(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "source.bin").write_bytes(textured_box().bytes())
    module("worker_task").execute_inspect(job)
    manifest = json.loads((job / "result.json").read_bytes())
    assert manifest["schemaVersion"] == 2 and "preview.png" in manifest["files"]
    module("runner")._result(job, require_preview=True)
    (job / "recipe.json").write_bytes(module("validation").json_bytes(
        {"importId": "mi-" + "0" * 24, "name": "Box", "category": "decor"}))
    module("prepare").execute_prepare(job)
    module("prepare_protocol").read_draft_output(job / "output")
    assert (job / "output" / "preview.png").is_file() and (job / "output" / "thumbnail.webp").is_file()


def test_legacy_cache_still_prepares_but_cannot_be_new_inspect_result(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "source.bin").write_bytes(textured_box().bytes())
    module("worker_task").execute_inspect(job)
    manifest = json.loads((job / "result.json").read_bytes())
    manifest["schemaVersion"] = 1
    manifest["files"].pop("preview.png")
    (job / "preview.png").unlink()
    (job / "result.json").write_bytes(module("validation").json_bytes(manifest))
    module("cache").load_cache(job)
    with pytest.raises(module("errors").ModelImportError):
        module("runner")._result(job, require_preview=True)
    (job / "recipe.json").write_bytes(module("validation").json_bytes(
        {"importId": "mi-" + "0" * 24, "name": "Box", "category": "decor"}))
    module("prepare").execute_prepare(job)
    module("prepare_protocol").read_draft_output(job / "output")


def test_preview_corruption_is_rejected_even_with_updated_manifest_hash(tmp_path):
    from hashlib import sha256
    job = tmp_path / "job"
    job.mkdir()
    (job / "source.bin").write_bytes(textured_box().bytes())
    module("worker_task").execute_inspect(job)
    (job / "preview.png").write_bytes(b"not a PNG")
    manifest = json.loads((job / "result.json").read_bytes())
    manifest["files"]["preview.png"] = {"bytes": 9, "sha256": sha256(b"not a PNG").hexdigest()}
    (job / "result.json").write_bytes(module("validation").json_bytes(manifest))
    with pytest.raises(module("errors").ModelImportError) as caught:
        module("runner")._result(job)
    assert caught.value.code == "model_worker_failed"


def test_picture_header_validators_reject_wrong_sizes_and_truncation():
    rendered = preview.render_previews(quad())
    pictures = module("pictures")
    for payload, kind in ((rendered.preview[:-8], "preview"), (rendered.thumbnail[:-1], "thumbnail")):
        with pytest.raises(module("errors").ModelImportError):
            pictures.validate_picture(payload, kind)


def test_picture_byte_caps_on_high_entropy_images():
    random = np.random.default_rng(7)
    with Image.fromarray(random.integers(0, 256, (768, 768, 3), dtype=np.uint8)) as noise:
        png = preview._png(noise)
        webp = preview._thumbnail(noise)
    assert len(png) <= preview.PREVIEW_BYTES and len(webp) <= preview.THUMBNAIL_BYTES
    module("pictures").validate_picture(png, "preview")
    module("pictures").validate_picture(webp, "thumbnail")


def test_segmented_blend_matches_sequential_compositing_for_many_pixels():
    random = np.random.default_rng(11)
    count = 500
    x = random.integers(0, 16, count)
    y = random.integers(0, 16, count)
    points = np.column_stack((x + .1, y + .1, np.arange(count, 0, -1))).astype(np.float32)
    colors = random.random((count, 3), dtype=np.float32)
    alpha = random.random(count, dtype=np.float32)
    alpha[::7] = 1
    expected = np.ones((16, 16, 3), dtype=np.float32)
    for i in range(count):
        expected[y[i], x[i]] = colors[i] * alpha[i] + expected[y[i], x[i]] * (1 - alpha[i])
    actual = np.ones_like(expected)
    raster._splat(np.arange(count), points, colors, alpha, actual, np.full((16, 16), np.inf), True)
    np.testing.assert_allclose(actual, expected, atol=2e-6)


def test_texture_alpha_is_composited_per_pixel():
    model = quad(texture=quadrant_texture(mask=True), color=(1, 1, 1, .5), alpha="BLEND")
    pixels = preview.render_view(model, size=128, grid=False)
    np.testing.assert_array_equal(pixels[41, 41], raster.BACKGROUND)
    expected = raster.to_srgb(.5 * np.array([0, 1, 0]) + .5 * raster.LINEAR[np.array(raster.BACKGROUND)])
    np.testing.assert_allclose(pixels[41, 87], expected, atol=1)


def test_small_triangle_centroid_samples_texture_mask_and_emissive():
    model = quad(texture=quadrant_texture(mask=True), alpha="MASK", emission=(.1, 0, 0))
    scene = geometry.build_geometry(model)
    colors, alpha = raster._splat_colors(np.array([0, 1]), scene, np.ones(2), raster.TextureCache(model.images))
    # The two quad centroids fall in bottom-right (yellow) and top-left (transparent red).
    np.testing.assert_allclose(colors, [[1, 1, 0], [1, 0, 0]], atol=1e-7)
    np.testing.assert_array_equal(alpha, [1, 0])


def test_picture_header_dimensions_cannot_be_forged():
    import struct
    import zlib
    rendered = preview.render_previews(quad())
    png = bytearray(rendered.preview)
    struct.pack_into(">I", png, 16, 1024)
    struct.pack_into(">I", png, 29, zlib.crc32(png[12:29]) & 0xffffffff)
    webp = bytearray(rendered.thumbnail)
    struct.pack_into("<H", webp, 26, 1024)
    for data, kind in ((png, "preview"), (webp, "thumbnail")):
        with pytest.raises(module("errors").ModelImportError):
            module("pictures").validate_picture(bytes(data), kind)
