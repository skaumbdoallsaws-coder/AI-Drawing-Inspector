"""The property frame: an exact east-north-up tangent plane at a site's origin (SC1)."""
import math

from ai_inspector.facility_layout.geo import (
    box_corners, ecef_to_geodetic, from_property, geodetic_to_ecef, geographic_box, to_property,
)

ORIGIN = (44.9778, -93.2650)


def test_ecef_round_trip():
    for latitude, longitude, height in ((44.9778, -93.265, 256.0), (-33.86, 151.21, 5.0), (0.0, 0.0, 0.0), (71.29, -156.79, 10.0)):
        back = ecef_to_geodetic(*geodetic_to_ecef(latitude, longitude, height))
        assert math.isclose(back[0], latitude, abs_tol=1e-9) and math.isclose(back[1], longitude, abs_tol=1e-9)
        assert math.isclose(back[2], height, abs_tol=1e-4)


def test_a_point_100_m_east_lands_at_x_100():
    latitude, longitude, height = from_property(100.0, 0.0, *ORIGIN)
    # On the tangent plane, 100 m out, the point stands 100^2 / 2R = 0.78 mm above the ground.
    assert math.isclose(height, 100.0 ** 2 / (2 * 6378137.0), rel_tol=0.01)
    x, z, y = to_property(latitude, longitude, *ORIGIN, height=height)
    assert math.isclose(x, 100.0, abs_tol=1e-6) and abs(z) < 1e-6 and abs(y) < 1e-6
    assert latitude == ORIGIN[0] or math.isclose(latitude, ORIGIN[0], abs_tol=1e-8)
    assert longitude > ORIGIN[1]


def test_property_round_trip_over_two_kilometres():
    for x, z in ((0, 0), (1500.0, -800.0), (-2000.0, 2000.0), (12.5, 0.75)):
        x2, z2, y2 = to_property(*from_property(x, z, *ORIGIN)[:2], *ORIGIN)
        # The ground curves below the tangent plane; the plane point itself comes back exactly.
        assert math.isclose(x2, x, abs_tol=0.02) and math.isclose(z2, z, abs_tol=0.02)
        assert y2 <= 0.0 and y2 > -0.7


def test_a_hundredth_of_a_degree_of_latitude_at_45_degrees_is_1111_metres():
    _, north, _ = to_property(45.01, 0.0, 45.0, 0.0)
    assert math.isclose(north, 1111.32, abs_tol=0.05)


def test_geographic_box_holds_the_rectangle_and_its_corners_return():
    bounds = geographic_box(*ORIGIN, 250.0, 150.0)
    assert bounds["south"] < ORIGIN[0] < bounds["north"] and bounds["west"] < ORIGIN[1] < bounds["east"]
    corners = box_corners(bounds, *ORIGIN)
    assert [round(c["x"]) for c in corners] == [-250, 250, 250, -250]
    assert [round(c["z"]) for c in corners] == [-150, -150, 150, 150]
