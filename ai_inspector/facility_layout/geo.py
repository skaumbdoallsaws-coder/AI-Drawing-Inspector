"""WGS84 positions and a facility site's property frame (site context, SC1).

The property frame is the east-north-up tangent plane at the site's origin: +X east,
+Z north, +Y up, in metres, the same axes as layout coordinates. It is computed
exactly through earth-centred (ECEF) coordinates, so no projection library is needed.
A kilometre from the origin the plane stands about 8 cm above the curved ground, far
less than the error of aerial imagery.
"""
from __future__ import annotations

import math

A = 6378137.0
F = 1.0 / 298.257223563
E2 = F * (2.0 - F)


def geodetic_to_ecef(latitude: float, longitude: float, height: float = 0.0) -> tuple[float, float, float]:
    phi, lam = math.radians(latitude), math.radians(longitude)
    sin_phi = math.sin(phi)
    n = A / math.sqrt(1.0 - E2 * sin_phi * sin_phi)
    return ((n + height) * math.cos(phi) * math.cos(lam),
            (n + height) * math.cos(phi) * math.sin(lam),
            (n * (1.0 - E2) + height) * sin_phi)


def ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float, float]:
    longitude = math.atan2(y, x)
    p = math.hypot(x, y)
    latitude = math.atan2(z, p * (1.0 - E2))
    height = 0.0
    for _ in range(8):
        sin_lat = math.sin(latitude)
        n = A / math.sqrt(1.0 - E2 * sin_lat * sin_lat)
        height = p / math.cos(latitude) - n
        latitude = math.atan2(z, p * (1.0 - E2 * n / (n + height)))
    return math.degrees(latitude), math.degrees(longitude), height


def _axes(origin_latitude: float, origin_longitude: float):
    phi, lam = math.radians(origin_latitude), math.radians(origin_longitude)
    sp, cp, sl, cl = math.sin(phi), math.cos(phi), math.sin(lam), math.cos(lam)
    east = (-sl, cl, 0.0)
    north = (-sp * cl, -sp * sl, cp)
    up = (cp * cl, cp * sl, sp)
    return east, north, up


def to_property(latitude: float, longitude: float, origin_latitude: float, origin_longitude: float,
                height: float = 0.0, origin_height: float = 0.0) -> tuple[float, float, float]:
    """A WGS84 position as property-frame (x east, z north, y up) metres."""
    px, py, pz = geodetic_to_ecef(latitude, longitude, height)
    ox, oy, oz = geodetic_to_ecef(origin_latitude, origin_longitude, origin_height)
    d = (px - ox, py - oy, pz - oz)
    east, north, up = _axes(origin_latitude, origin_longitude)
    dot = lambda u: u[0] * d[0] + u[1] * d[1] + u[2] * d[2]  # noqa: E731
    return dot(east), dot(north), dot(up)


def from_property(x: float, z: float, origin_latitude: float, origin_longitude: float,
                  y: float = 0.0, origin_height: float = 0.0) -> tuple[float, float, float]:
    """A property-frame point (x east, z north, y up metres) as WGS84 latitude, longitude, height."""
    ox, oy, oz = geodetic_to_ecef(origin_latitude, origin_longitude, origin_height)
    east, north, up = _axes(origin_latitude, origin_longitude)
    return ecef_to_geodetic(*(o + x * e + z * n + y * u for o, e, n, u in zip((ox, oy, oz), east, north, up)))


def geographic_box(origin_latitude: float, origin_longitude: float,
                   half_width: float, half_depth: float) -> dict[str, float]:
    """The latitude/longitude box that contains a property-frame rectangle centred on the origin."""
    corners = [from_property(sx * half_width, sz * half_depth, origin_latitude, origin_longitude)
               for sx in (-1, 1) for sz in (-1, 1)]
    return {"south": min(c[0] for c in corners), "west": min(c[1] for c in corners),
            "north": max(c[0] for c in corners), "east": max(c[1] for c in corners)}


def box_corners(bounds: dict[str, float], origin_latitude: float, origin_longitude: float) -> list[dict[str, float]]:
    """A latitude/longitude box's corners in the property frame: south-west, south-east, north-east, north-west."""
    points = ((bounds["south"], bounds["west"]), (bounds["south"], bounds["east"]),
              (bounds["north"], bounds["east"]), (bounds["north"], bounds["west"]))
    result = []
    for latitude, longitude in points:
        x, z, _ = to_property(latitude, longitude, origin_latitude, origin_longitude)
        result.append({"x": round(x, 4) + 0.0, "z": round(z, 4) + 0.0})
    return result
