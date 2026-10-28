"""Paved features on the site's stored photo: find them, trace one, measure it (find-and-build, step F).

The server reads the photo the site already stores (public-domain NAIP or Met Council imagery);
nothing is fetched. Pavement is low-saturation, non-green and not in deep shadow. The road
centerlines (site_roads.py) are cut out so a lot does not run into the street network, gaps left
by parked cars and stripes are closed, and necks narrower than about 8 m (driveways, sidewalks)
are opened. A region becomes an outline in the property frame with its area, perimeter, size and
long-axis bearing. Outlines are accurate to about two photo pixels: existing pavement as seen on
a dated photo, never a property line.
"""
from __future__ import annotations

import base64
from io import BytesIO
import math

from .errors import FacilityLayoutError
from .site_context import building_outline

WORK_METERS_PER_PIXEL = 0.75
MIN_FEATURE_SQUARE_METERS = 600.0
CLOSE_METERS = 2.5   # bridge stripes and the gaps between parked cars
OPEN_METERS = 4.0    # cut necks narrower than about 8 m
STRIPE_METERS = 0.75  # drop marks thinner than about 1.5 m before closing
SEED_WINDOW_METERS = 8.0
SEED_SEARCH_METERS = 15.0
BRIGHTNESS_BAND = 0.14
ROAD_HALF_WIDTHS = {"highway": 9.0, "arterial": 7.0, "ramp": 4.0, "local": 4.5, "service": 3.0, "alley": 2.5,
                    "private": 3.0, "railroad": 3.0}  # parking aisles run inside lots: never cut out
MAX_OUTLINE_POINTS = 48
MAX_CANDIDATES = 8
COMPASS = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")


def _fail(message: str, code: str = "site_trace_failed", status: int = 422):
    raise FacilityLayoutError(code, message, status_code=status)


def _steps(meters: float, photo) -> int:
    return max(1, round(meters / photo.dx))


class _Photo:
    """The site photo at the working resolution, with each pixel placed in the property frame."""

    def __init__(self, image: dict, path):
        import numpy as np
        from PIL import Image
        corners = image["corners"]
        self.min_x = (corners[0]["x"] + corners[3]["x"]) / 2
        self.max_x = (corners[1]["x"] + corners[2]["x"]) / 2
        self.min_z = (corners[0]["z"] + corners[1]["z"]) / 2
        self.max_z = (corners[2]["z"] + corners[3]["z"]) / 2
        self.cols = max(8, round((self.max_x - self.min_x) / WORK_METERS_PER_PIXEL))
        self.rows = max(8, round((self.max_z - self.min_z) / WORK_METERS_PER_PIXEL))
        self.dx = (self.max_x - self.min_x) / self.cols
        self.dz = (self.max_z - self.min_z) / self.rows
        try:
            with Image.open(path) as picture:
                self.picture = picture.convert("RGB")
        except OSError:
            _fail("The site photo could not be read.", "site_photo_missing", 404)
        small = self.picture.resize((self.cols, self.rows), Image.Resampling.BOX)
        self.rgb = np.asarray(small, dtype=np.float32) / 255.0
        self.image = image

    def pixel(self, x: float, z: float) -> tuple[int, int]:
        return int((self.max_z - z) / self.dz), int((x - self.min_x) / self.dx)

    def point(self, row: float, col: float) -> tuple[float, float]:
        return self.min_x + col * self.dx, self.max_z - row * self.dz


def _pavement(photo: _Photo):
    import numpy as np
    rgb = photo.rgb
    top, low = rgb.max(axis=2), rgb.min(axis=2)
    saturation = (top - low) / np.maximum(top, 1e-3)
    green = 2 * rgb[..., 1] - rgb[..., 0] - rgb[..., 2]
    yellow = (rgb[..., 0] + rgb[..., 1]) / 2 - rgb[..., 2]
    # Calibrated on NAIP at Bayport: pavement shows yellow up to 0.06 and no green excess, dry grass 0.11-0.13.
    return (saturation < 0.2) & (top > 0.16) & (green < 0.01) & (yellow < 0.09), top, saturation


def _road_mask(photo: _Photo, site: dict):
    import numpy as np
    from PIL import Image, ImageDraw
    canvas = Image.new("1", (photo.cols, photo.rows), 0)
    draw = ImageDraw.Draw(canvas)
    for road in (site.get("roads") or {}).get("items", []):
        half = ROAD_HALF_WIDTHS.get(road["kind"], 0.0)
        if half <= 0 or len(road["line"]) < 2:
            continue
        points = [((p["x"] - photo.min_x) / photo.dx, (photo.max_z - p["z"]) / photo.dz) for p in road["line"]]
        draw.line(points, fill=1, width=max(1, round(2 * half / photo.dx)), joint="curve")
    return np.asarray(canvas, dtype=bool)


def _clean(mask, photo: _Photo, drop_marks: bool = False):
    """Close stripes and car gaps, fill parked cars, then open away necks narrower than about 8 m.

    The opening uses a square, which leaves the corners of a lot square to the photo untouched.
    """
    from scipy import ndimage
    cross = ndimage.generate_binary_structure(2, 1)
    square = ndimage.generate_binary_structure(2, 2)
    if drop_marks:
        # Painted stripes and single white cars are not a light surface: drop marks thinner than about 1.5 m.
        mask = ndimage.binary_opening(mask, structure=square, iterations=_steps(STRIPE_METERS, photo))
    closed = ndimage.binary_closing(mask, structure=cross, iterations=_steps(CLOSE_METERS, photo))
    closed = ndimage.binary_fill_holes(closed)
    opened = ndimage.binary_opening(closed, structure=square, iterations=_steps(OPEN_METERS, photo))
    return closed, opened


def _regrow(region, closed, photo: _Photo):
    """Win back corners a turned lot lost to the opening; half as far, so a neck regrows at most a few metres."""
    import numpy as np
    from scipy import ndimage
    steps = max(1, _steps(OPEN_METERS, photo) // 2)
    rows, cols = np.nonzero(region)
    top, bottom = max(0, rows.min() - steps), rows.max() + steps + 1
    left, right = max(0, cols.min() - steps), cols.max() + steps + 1
    grown = np.zeros_like(region)
    grown[top:bottom, left:right] = ndimage.binary_dilation(
        region[top:bottom, left:right], iterations=steps, mask=closed[top:bottom, left:right])
    return grown


def _outline(region, photo: _Photo):
    import numpy as np
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    boxes = []
    for row in range(region.shape[0]):
        edges = np.flatnonzero(np.diff(np.concatenate(([0], region[row].astype(np.int8), [0]))))
        for start, end in zip(edges[::2], edges[1::2]):
            x0, z1 = photo.point(row, start)
            x1, z0 = photo.point(row + 1, end)
            boxes.append(box(x0, z0, x1, z1))
    shape = unary_union(boxes)
    if shape.geom_type == "MultiPolygon":
        shape = max(shape.geoms, key=lambda part: part.area)
    shape = Polygon(shape.exterior)  # the outer edge; parked cars and islands are not holes in a lot
    tolerance = max(1.0, photo.dx)
    simple = shape.simplify(tolerance, preserve_topology=True)
    while len(simple.exterior.coords) - 1 > MAX_OUTLINE_POINTS:
        tolerance *= 1.5
        simple = shape.simplify(tolerance, preserve_topology=True)
    if not simple.exterior.is_ccw:
        simple = Polygon(list(simple.exterior.coords)[::-1])
    return simple


def _describe(shape, region, photo: _Photo, layout: dict, site: dict, saturation, brightness) -> dict:
    from shapely.geometry import LineString, Polygon
    rectangle = shape.minimum_rotated_rectangle
    corners = list(rectangle.exterior.coords)[:4]
    sides = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    long_side = max(sides, key=lambda side: math.dist(*side))
    length, width = math.dist(*long_side), min(math.dist(*side) for side in sides)
    bearing = math.degrees(math.atan2(long_side[1][0] - long_side[0][0], long_side[1][1] - long_side[0][1])) % 180
    building = Polygon([(p["x"], p["z"]) for p in building_outline(layout, site)])
    center = shape.centroid
    toward = math.degrees(math.atan2(center.x - building.centroid.x, center.y - building.centroid.y)) % 360
    rows, cols = region.shape
    edge = region[0, :].any() or region[-1, :].any() or region[:, 0].any() or region[:, cols - 1].any()
    nearby = []
    for road in (site.get("roads") or {}).get("items", []):
        line = LineString([(p["x"], p["z"]) for p in road["line"]])
        distance = line.distance(shape)
        if distance <= 15.0 and road["label"] not in [item["name"] for item in nearby]:
            nearest = line.interpolate(line.project(center))
            side = math.degrees(math.atan2(nearest.x - center.x, nearest.y - center.y)) % 360
            nearby.append({"name": road["label"], "kind": road["kind"], "distanceMeters": round(distance, 1),
                           "side": COMPASS[round(side / 45) % 8]})
    return {
        "outline": [{"x": round(x, 2), "z": round(z, 2)} for x, z in list(shape.exterior.coords)[:-1]],
        "areaSquareMeters": round(shape.area, 1), "areaAcres": round(shape.area / 4046.8564224, 2),
        "perimeterMeters": round(shape.length, 1),
        "lengthMeters": round(length, 1), "widthMeters": round(width, 1),
        "longAxisBearingDegrees": round(bearing, 1),
        "rectangularity": round(shape.area / rectangle.area, 2) if rectangle.area else 0,
        "fromBuilding": {"distanceMeters": round(shape.distance(building), 1),
                         "direction": COMPASS[round(toward / 45) % 8]},
        "roadsWithin15Meters": nearby,
        "touchesPhotoEdge": bool(edge),
        "accuracyMeters": round(2 * photo.dx, 1),
    }


def _source(photo: _Photo) -> dict:
    image = photo.image
    return {"imageId": image["imageId"], "source": image["source"], "captured": image.get("captured"),
            "attribution": image.get("attribution")}


def _site_photo(site: dict, photo_path):
    if not site.get("imagery"):
        _fail("Fetch an aerial photo in the Site tab first.", "site_photo_missing", 409)
    image = site["imagery"][0]
    return _Photo(image, photo_path(image))


def trace_feature(layout: dict, site: dict, photo_path, x: float | None = None, z: float | None = None,
                  box: dict | None = None) -> dict:
    """The paved region at a point on the photo, or the largest one inside a box, traced and measured.

    A box keeps the trace to the part that is meant, such as one lot of several joined ones.
    """
    import numpy as np
    from scipy import ndimage
    photo = _site_photo(site, photo_path)
    pavement, brightness, saturation = _pavement(photo)
    pavement &= ~_road_mask(photo, site)
    inside = np.ones_like(pavement)
    if box is not None:
        top, left = photo.pixel(box["minX"], box["maxZ"])
        bottom, right = photo.pixel(box["maxX"], box["minZ"])
        top, left = max(0, top), max(0, left)
        bottom, right = min(photo.rows - 1, bottom), min(photo.cols - 1, right)
        if bottom - top < 4 or right - left < 4:
            _fail("The box is outside the site photo or too small.")
        inside = np.zeros_like(pavement)
        inside[top:bottom + 1, left:right + 1] = True
        pavement &= inside
        if x is None or z is None:
            x, z = (box["minX"] + box["maxX"]) / 2, (box["minZ"] + box["maxZ"]) / 2
    if x is None or z is None:
        _fail("Give a point or a box.")
    row, col = photo.pixel(x, z)
    if not (0 <= row < photo.rows and 0 <= col < photo.cols):
        _fail("That point is outside the site photo.")
    if box is not None and not pavement[max(0, row - 2):row + 3, max(0, col - 2):col + 3].any():
        # The box's middle may be grass: start from the box's biggest paved patch instead.
        labels, count = ndimage.label(pavement)
        if not count:
            _fail("No pavement shows inside the box.")
        biggest = int(np.argmax(ndimage.sum(pavement, labels, index=range(1, count + 1)))) + 1
        rows_at, cols_at = np.nonzero(labels == biggest)
        middle = len(rows_at) // 2
        row, col = int(rows_at[middle]), int(cols_at[middle])
        x, z = photo.point(row + 0.5, col + 0.5)
    reach = max(1, round(SEED_WINDOW_METERS / photo.dx))
    window = (slice(max(0, row - reach), row + reach + 1), slice(max(0, col - reach), col + reach + 1))
    if not pavement[window].any():
        _fail("No pavement shows at that point on the photo.")
    level = float(np.median(brightness[window][pavement[window]]))
    closed, opened = _clean(pavement & (np.abs(brightness - level) < BRIGHTNESS_BAND), photo)
    labels, count = ndimage.label(opened)
    if not count:
        _fail("The pavement at that point is too small or too narrow to trace.")
    label = labels[row, col]
    if not label:
        distance, (rows_at, cols_at) = ndimage.distance_transform_edt(labels == 0, return_indices=True)
        if distance[row, col] * photo.dx > SEED_SEARCH_METERS:
            _fail("No pavement area large enough to trace near that point.")
        label = labels[rows_at[row, col], cols_at[row, col]]
    region = _regrow(labels == label, closed & inside, photo)
    shape = _outline(region, photo)
    if shape.area < MIN_FEATURE_SQUARE_METERS / 4:
        _fail("The pavement at that point is too small to trace.")
    return {**_describe(shape, region, photo, layout, site, saturation, brightness), "photo": _source(photo),
            "seed": {"x": round(x, 2), "z": round(z, 2)}, "box": box, "brightness": round(level, 2)}


def find_features(layout: dict, site: dict, photo_path, min_square_meters: float = MIN_FEATURE_SQUARE_METERS) -> dict:
    """Paved regions on the photo large enough to build on, largest first, lettered A, B, C..."""
    import numpy as np
    from scipy import ndimage
    photo = _site_photo(site, photo_path)
    pavement, brightness, saturation = _pavement(photo)
    pavement &= ~_road_mask(photo, site)
    found = []
    for light, band in ((False, brightness < 0.5), (True, brightness >= 0.5)):  # asphalt; concrete and light roofs
        surface = pavement & band
        closed, opened = _clean(surface, photo, drop_marks=light)
        labels, count = ndimage.label(opened)
        sizes = ndimage.sum(np.ones_like(labels), labels, index=range(1, count + 1)) * photo.dx * photo.dz
        for index, size in enumerate(sizes, start=1):
            if size < min_square_meters:
                continue
            region = _regrow(labels == index, closed, photo)
            # Stall stripes and white cars on asphalt close into a "light" region: keep only regions
            # mostly made of their own surface.
            if surface[region].mean() >= 0.5:
                found.append((region, _outline(region, photo)))
    kept = []
    for region, shape in sorted(found, key=lambda item: -item[1].area):
        if all(shape.intersection(other).area < 0.5 * min(shape.area, other.area) for _, other in kept):
            kept.append((region, shape))
    features = []
    for letter, (region, shape) in zip("ABCDEFGH", kept[:MAX_CANDIDATES]):
        features.append({"featureId": letter,
                         **_describe(shape, region, photo, layout, site, saturation, brightness)})
    return {"photo": _source(photo), "features": features, "photoObject": photo}


def annotated_photo(photo: _Photo, features: list[dict], max_side: int = 1024) -> str:
    """The photo with each feature outlined and lettered, and a 50 m grid labelled in property metres."""
    from PIL import Image, ImageDraw
    picture = photo.picture.copy()
    scale = max_side / max(picture.size)
    if scale < 1:
        picture = picture.resize((round(picture.width * scale), round(picture.height * scale)), Image.Resampling.LANCZOS)
    width, height = picture.size
    draw = ImageDraw.Draw(picture)
    to_pixel = lambda x, z: ((x - photo.min_x) / (photo.max_x - photo.min_x) * width,  # noqa: E731
                             (photo.max_z - z) / (photo.max_z - photo.min_z) * height)
    step = 50
    for x in range(math.ceil(photo.min_x / step) * step, math.floor(photo.max_x) + 1, step):
        px = to_pixel(x, 0)[0]
        draw.line([(px, 0), (px, height)], fill=(255, 255, 255), width=1)
        draw.text((px + 2, 2), f"x {x}", fill=(255, 255, 0))
    for z in range(math.ceil(photo.min_z / step) * step, math.floor(photo.max_z) + 1, step):
        py = to_pixel(0, z)[1]
        draw.line([(0, py), (width, py)], fill=(255, 255, 255), width=1)
        draw.text((2, py + 2), f"z {z}", fill=(255, 255, 0))
    for feature in features:
        points = [to_pixel(p["x"], p["z"]) for p in feature["outline"]]
        draw.line(points + points[:1], fill=(0, 229, 255), width=3)
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        draw.rectangle([cx - 9, cy - 9, cx + 9, cy + 9], fill=(0, 0, 0))
        draw.text((cx - 4, cy - 6), feature["featureId"], fill=(0, 229, 255))
    out = BytesIO()
    picture.save(out, format="JPEG", quality=80)
    return base64.b64encode(out.getvalue()).decode("ascii")
