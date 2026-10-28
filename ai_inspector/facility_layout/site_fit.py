"""Bounded, deterministic conceptual site-fit search. No network or mutations."""
import math
from copy import deepcopy
from shapely.geometry import LineString, Polygon
from .site_context import KEY, _number, normalize_site_context, building_outline, analyze_site_context, REFERENCE_AREA_KINDS


def analyze_site_fit(layout, request):
    fields = {'widthMeters', 'depthMeters', 'bearingsDegrees', 'dockWallEdge', 'truckCourtDepthMeters',
              'parkingCount', 'stallWidthMeters', 'stallDepthMeters', 'driveAisleWidthMeters'}
    if not isinstance(request, dict) or set(request) - fields:
        raise ValueError('Unsupported site-fit arguments')
    width = _number(request.get('widthMeters'), 'widthMeters', 1, 1000)
    depth = _number(request.get('depthMeters'), 'depthMeters', 1, 1000)
    bearings = request.get('bearingsDegrees', [0, 90, 180, 270])
    if not isinstance(bearings, list) or not 1 <= len(bearings) <= 8:
        raise ValueError('Choose one to eight bearings')
    bearings = sorted({_number(b, 'bearing', -360, 360) % 360 for b in bearings})
    dock = request.get('dockWallEdge')
    if dock is not None and (type(dock) is not int or not 0 <= dock <= 3):
        raise ValueError('dockWallEdge must be a building edge index, 0 to 3')
    if dock is None and 'truckCourtDepthMeters' in request:
        raise ValueError('A truck court needs dockWallEdge')
    court_depth = _number(request.get('truckCourtDepthMeters', 35), 'truckCourtDepthMeters', 5, 150)
    count = request.get('parkingCount', 0)
    if type(count) is not int or not 0 <= count <= 200:
        raise ValueError('parkingCount must be an integer from 0 to 200')
    stall_w = _number(request.get('stallWidthMeters', 2.6), 'stallWidthMeters', 1.5, 6)
    stall_d = _number(request.get('stallDepthMeters', 5.5), 'stallDepthMeters', 3, 12)
    aisle = _number(request.get('driveAisleWidthMeters', 6), 'driveAisleWidthMeters', 3, 15)
    result = {'candidates': [], 'evaluatedPoses': 0, 'searchComplete': False, 'exhaustive': False,
              'method': 'bounded 9x9 center grid per bearing, plus current center and lot centroid',
              'assumptions': {'requestedBuildingMeters': {'width': width, 'depth': depth},
                  'parkingCount': count, 'stallWidthMeters': stall_w, 'stallDepthMeters': stall_d,
                  'driveAisleWidthMeters': aisle, 'buildingToParkingGapMeters': 2,
                  'courtReservationSeparationMeters': 0.001 if dock is not None else None,
                  'truckCourtDepthMeters': court_depth if dock is not None else None},
              'unverified': ['Legal boundary, regulations and setbacks require user verification.',
                  'Parking is a reserved envelope including an aisle, not authored or counted stalls.',
                  'Entrance connections, dock doors, turning paths, pedestrian access and interior fit are not evaluated.'],
              'readOnly': True}
    raw = (layout.get('extensions') or {}).get(KEY)
    if raw is None or not raw.get('property'):
        return dict(result, reason='A user-supplied site boundary is required.')
    site = normalize_site_context(raw, layout)
    if len(site.get('areas',[])) + bool(count) + (dock is not None) > 64:
        return dict(result,reason='The requested reservations exceed the outdoor-area count limit.')
    existing = analyze_site_context(layout)
    if any(f['code'] in {'site_area_overlap','site_area_outside_property','site_area_setback_violation'} for f in existing['findings']):
        return dict(result,reason='Correct existing outdoor-area geometry findings before reserving additional space.')
    prop = site['property']
    lot = Polygon([(p['x'], p['z']) for p in prop['boundary']])
    tolerant_lot = lot.buffer(1e-7)
    boundary = list(lot.exterior.coords)[:-1]
    edges = [(LineString([a, boundary[(i + 1) % len(boundary)]]), prop['setbacksMeters'][
        'street' if i in prop['streetEdges'] else 'rear' if i in prop['rearEdges'] else 'side'])
        for i, a in enumerate(boundary)]
    # Existing pavement is what the design may replace, not space it must avoid.
    occupied = [Polygon([(p['x'], p['z']) for p in area['boundary']]) for area in site.get('areas', [])
                if area['kind'] not in REFERENCE_AREA_KINDS]
    def fits(shape, extra=()):
        return (tolerant_lot.covers(shape)
                and all(shape.distance(edge) + 1e-6 >= setback for edge, setback in edges)
                and not any(shape.intersection(other).area > 1e-6 for other in [*occupied, *extra]))
    local = [(0, 0), (width, 0), (width, depth), (0, depth)]
    local_court = None
    if dock is not None:
        a, b = local[dock], local[(dock + 1) % 4]
        length = math.dist(a, b)
        nx, nz = (b[1] - a[1]) / length, -(b[0] - a[0]) / length
        # A 1 mm reservation separation survives persisted micrometre rounding.
        gap = 0.001
        local_court = [(a[0]+nx*gap,a[1]+nz*gap),(b[0]+nx*gap,b[1]+nz*gap),
            (b[0]+nx*(court_depth+gap),b[1]+nz*(court_depth+gap)),
            (a[0]+nx*(court_depth+gap),a[1]+nz*(court_depth+gap))]
    parking_options = []
    if count:
        columns = min(count, 10)
        rows = math.ceil(count / columns)
        pw, pd = columns * stall_w, rows * stall_d + math.ceil(rows / 2) * aisle
        for x, z in [((width-pw)/2, -pd-2), ((width-pw)/2, depth+2), (-pw-2, (depth-pd)/2), (width+2, (depth-pd)/2)]:
            parking_options.append([(x,z),(x+pw,z),(x+pw,z+pd),(x,z+pd)])
    min_x, min_z, max_x, max_z = lot.bounds
    current_outline = building_outline(layout, site)
    current_center = (sum(p['x'] for p in current_outline)/4, sum(p['z'] for p in current_outline)/4)
    candidates = []
    for bearing in bearings:
        angle = math.radians(bearing); c, s = math.cos(angle), math.sin(angle)
        rotated = [(x*c+z*s, -x*s+z*c) for x,z in local]
        offset_x, offset_z = width*c/2+depth*s/2, -width*s/2+depth*c/2
        half_x = (max(x for x,z in rotated)-min(x for x,z in rotated))/2
        half_z = (max(z for x,z in rotated)-min(z for x,z in rotated))/2
        if max_x-min_x < half_x*2 or max_z-min_z < half_z*2:
            continue
        centers = {current_center, (lot.centroid.x,lot.centroid.y)}
        centers.update((min_x+half_x+(max_x-min_x-2*half_x)*i/8,
                        min_z+half_z+(max_z-min_z-2*half_z)*j/8) for i in range(9) for j in range(9))
        for cx, cz in sorted(centers):
            result['evaluatedPoses'] += 1
            pose = {'x': round(cx-offset_x,6), 'z': round(cz-offset_z,6), 'bearingDegrees': bearing}
            if max(abs(pose['x']),abs(pose['z'])) > 5000:
                continue
            def transform(points):
                return [{'x':pose['x']+x*c+z*s,'z':pose['z']-x*s+z*c} for x,z in points]
            def polygon(points):
                return Polygon([(p['x'],p['z']) for p in points])
            footprint = transform(local); shape = polygon(footprint)
            if not fits(shape):
                continue
            allocations, extra = [], [shape]
            if local_court:
                court = transform(local_court); court_shape = polygon(court)
                if not fits(court_shape,extra):
                    continue
                allocations.append({'kind':'truck_court','label':'Truck court','boundary':court,'surface':'asphalt'})
                extra.append(court_shape)
            if count:
                parking = next((points for points in (transform(p) for p in parking_options) if fits(polygon(points),extra)), None)
                if parking is None:
                    continue
                allocations.append({'kind':'parking','label':'Parking envelope','boundary':parking,'surface':'asphalt'})
                extra.append(polygon(parking))
            margin = min(part.distance(edge)-setback for part in extra for edge,setback in edges)
            distance = min((math.hypot(cx-e['x'],cz-e['z']) for e in prop['entrances']), default=math.dist((cx,cz),current_center))
            candidates.append({'buildingPose':pose,'buildingFootprint':footprint,'reservedAreas':allocations,
                'minimumSetbackSurplusMeters':round(margin,4),'rankingDistanceMeters':round(distance,4),
                'reasons':['Contained by the authored property; requested setbacks met.',
                           'No overlap with existing site areas or between proposed reservations.']})
    candidates.sort(key=lambda item:(-item['minimumSetbackSurplusMeters'],item['rankingDistanceMeters'],
        item['buildingPose']['bearingDegrees'],item['buildingPose']['x'],item['buildingPose']['z']))
    # Recheck through the persisted normalizer: rounding a rotated shared edge
    # must not turn a mathematically clean candidate into a saved overlap.
    for candidate in candidates[:32]:
        context = deepcopy(site)
        context['buildingPose'] = candidate['buildingPose']
        additions = deepcopy(candidate['reservedAreas'])
        identities = {area['areaId'] for area in context.get('areas',[])}
        for item in additions:
            suffix = 0
            while 'fit-reservation-'+str(suffix) in identities:
                suffix += 1
            item['areaId'] = 'fit-reservation-'+str(suffix); identities.add(item['areaId'])
        context['areas'] = [*context.get('areas',[]),*additions]
        checked = analyze_site_context({'extensions':{KEY:context,
            'facilityPlan':{'widthMeters':width,'depthMeters':depth}}})
        if not checked['findings']:
            result['candidates'].append(candidate)
            if len(result['candidates']) == 8:
                break
    result['searchComplete'] = True
    result['reason'] = ('Ranked by setback surplus, then proximity to an entrance or the current building center.' if result['candidates']
                        else 'No candidate in this bounded search. This does not prove the site is infeasible.')
    return result
