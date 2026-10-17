"""Bounded visual finishes. These do not replace wall or opening geometry."""
from copy import deepcopy
import math
import re
from collections.abc import Mapping

MAX_WALL_ARTWORKS = 48


def normalize_exterior_finish(value, points, height, openings, layout):
    from .perimeter_walls import _number

    allowed = {'color', 'jointColor', 'panelWidthMeters', 'panelHeightMeters',
               'jointWidthMeters', 'artworks', 'accentStrips', 'wallFaces', 'fittedArtworks'}
    if not isinstance(value, Mapping) or set(value) - allowed:
        raise ValueError('Unsupported exterior finish')
    def color(item):
        if not isinstance(item, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', item):
            raise ValueError('Exterior finish colors must be six-digit hex values')
        return item.lower()
    result = dict(color=color(value.get('color')),
                  jointColor=color(value.get('jointColor', '#16191b')),
                  panelWidthMeters=_number(value.get('panelWidthMeters', 2), 'panelWidthMeters', .5, 10),
                  panelHeightMeters=_number(value.get('panelHeightMeters', 1.2), 'panelHeightMeters', .4, 5),
                  jointWidthMeters=_number(value.get('jointWidthMeters', .012), 'jointWidthMeters', .003, .05))
    lengths = [math.dist(a, points[(i + 1) % len(points)]) for i, a in enumerate(points)]
    if sum(math.ceil(n / result['panelWidthMeters']) for n in lengths) * math.ceil(height / result['panelHeightMeters']) > 5000:
        raise ValueError('Exterior finish exceeds the 5000-panel budget')
    def rows(key, maximum):
        entries = value.get(key, [])
        if not isinstance(entries, list) or len(entries) > maximum:
            raise ValueError(f'Invalid or excessive exterior {key}')
        return entries
    def rectangle(entry):
        edge = entry.get('edge')
        if type(edge) is not int or not 0 <= edge < len(points):
            raise ValueError('Exterior finish edge is outside the perimeter')
        start = _number(entry.get('startMeters'), 'startMeters', 0, lengths[edge])
        width = _number(entry.get('widthMeters'), 'widthMeters', .01, lengths[edge])
        if start + width > lengths[edge] + 1e-8:
            raise ValueError('Exterior finish extends past its edge')
        if any(o['edge'] == edge and start < o['endMeters'] and start + width > o['startMeters'] for o in openings):
            raise ValueError('Exterior finish would cover a door opening')
        return dict(edge=edge, startMeters=start, widthMeters=width)
    result['artworks'] = []
    ids = set()
    for entry in rows('artworks', MAX_WALL_ARTWORKS):
        keys = {'artworkId', 'edge', 'startMeters', 'widthMeters', 'bottomMeters',
                'heightMeters', 'imagePath', 'uv', 'backingColor', 'borderColor', 'side'}
        if not isinstance(entry, Mapping) or set(entry) - keys:
            raise ValueError('Unsupported exterior artwork fields')
        record = rectangle(entry)
        side = entry.get('side', 'exterior')
        if side not in ('exterior', 'interior'):
            raise ValueError('Artwork side must be exterior or interior')
        if side == 'interior':
            record['side'] = side
        if record['widthMeters'] < .3:
            raise ValueError('Exterior artwork must be at least 0.3 m wide')
        identifier = entry.get('artworkId')
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-z0-9-]{1,80}', identifier) or identifier in ids:
            raise ValueError('Exterior artwork needs a unique stable ID')
        ids.add(identifier)
        image = entry.get('imagePath')
        if not isinstance(image, str) or not re.fullmatch(r'/generated/facility-wall-art/[a-f0-9]{64}\.png', image):
            raise ValueError('Exterior artwork must reference a local content-addressed PNG')
        bottom = _number(entry.get('bottomMeters'), 'bottomMeters', 0, height)
        h = _number(entry.get('heightMeters'), 'heightMeters', .3, height)
        if bottom + h > height + 1e-8:
            raise ValueError('Exterior artwork extends above its wall')
        uv = entry.get('uv', [0, 0, 1, 1])
        if not isinstance(uv, list) or len(uv) != 4:
            raise ValueError('Artwork UV bounds must contain four numbers')
        uv = [_number(v, 'uv', 0, 1) for v in uv]
        if uv[2] - uv[0] < .001 or uv[3] - uv[1] < .001:
            raise ValueError('Empty artwork UV bounds')
        record.update(artworkId=identifier, imagePath=image, bottomMeters=bottom, heightMeters=h, uv=uv)
        for key in ('backingColor', 'borderColor'):
            if key in entry:
                record[key] = color(entry[key])
        result['artworks'].append(record)
    result['accentStrips'] = []
    for entry in rows('accentStrips', 64):
        if not isinstance(entry, Mapping) or set(entry) != {'edge', 'startMeters', 'widthMeters', 'color'}:
            raise ValueError('Unsupported exterior accent strip')
        result['accentStrips'].append(dict(rectangle(entry), color=color(entry['color'])))
    result['wallFaces'] = []
    placements = {p['placementId']: p for p in layout.get('placements', [])}
    targets = set()
    for entry in rows('wallFaces', 64):
        if not isinstance(entry, Mapping) or set(entry) != {'placementId', 'assetDefinitionRevision', 'face', 'color'}:
            raise ValueError('Unsupported placed-wall finish')
        if not isinstance(entry['placementId'], str) or not isinstance(entry['assetDefinitionRevision'], str):
            raise ValueError('Exterior wall binding must use string identities')
        placement = placements.get(entry['placementId'])
        if not placement or placement['assetDefinitionRevision'] != entry['assetDefinitionRevision']:
            raise ValueError('Exterior wall finish has a missing or stale placement binding')
        if entry['face'] not in ('positive_z', 'negative_z'):
            raise ValueError('Exterior wall face must be positive_z or negative_z')
        key = (entry['placementId'], entry['face'])
        if key in targets:
            raise ValueError('Duplicate exterior wall face')
        targets.add(key)
        result['wallFaces'].append(dict(deepcopy(entry), color=color(entry['color'])))
    if 'fittedArtworks' in value:
        result['fittedArtworks'] = []
        for entry in rows('fittedArtworks', MAX_WALL_ARTWORKS):
            fields = {'artworkId', 'imagePath', 'uv', 'target', 'region', 'coverage'}
            if not isinstance(entry, Mapping) or set(entry) != fields:
                raise ValueError('Unsupported fitted artwork fields')
            identifier = entry['artworkId']
            if not isinstance(identifier, str) or not re.fullmatch(r'[a-z0-9-]{1,80}', identifier) or identifier in ids:
                raise ValueError('Fitted artwork needs a unique stable ID')
            ids.add(identifier)
            if len(ids) > MAX_WALL_ARTWORKS:
                raise ValueError(f'Combined artwork count exceeds the {MAX_WALL_ARTWORKS}-image budget')
            if not isinstance(entry['imagePath'], str) or not re.fullmatch(r'/generated/facility-wall-art/[a-f0-9]{64}\.png', entry['imagePath']):
                raise ValueError('Fitted artwork must reference a local content-addressed PNG')
            record = dict(artworkId=identifier, imagePath=entry['imagePath'],
                coverage=_number(entry['coverage'], 'coverage', .95, 1))
            for key in ('uv', 'region'):
                values = entry[key]
                if not isinstance(values, list) or len(values) != 4:
                    raise ValueError('Fitted artwork '+key+' needs four fractions')
                values = [_number(v, key, 0, 1) for v in values]
                if values[2]-values[0] < .001 or values[3]-values[1] < .001:
                    raise ValueError('Empty fitted artwork '+key)
                record[key] = values
            target = entry['target']
            if not isinstance(target, Mapping):
                raise ValueError('Fitted artwork needs a wall target')
            if set(target) == {'edge', 'side'}:
                edge = target['edge']
                if type(edge) is not int or not 0 <= edge < len(points) or target['side'] not in ('interior', 'exterior'):
                    raise ValueError('Invalid fitted artwork perimeter target')
                start, end = (record['region'][i]*lengths[edge] for i in (0, 2))
                if any(o['edge'] == edge and start < o['endMeters'] and end > o['startMeters'] for o in openings):
                    raise ValueError('Fitted artwork would cover a door opening')
            elif set(target) == {'placementId', 'face'}:
                if not isinstance(target['placementId'], str) or target['placementId'] not in placements:
                    raise ValueError('Fitted artwork wall placement is missing')
                if target['face'] not in ('positive_z', 'negative_z', 'positive_x', 'negative_x'):
                    raise ValueError('Invalid fitted artwork wall face')
                # Visual binding follows the occurrence's current geometry, including resized definitions.
            else:
                raise ValueError('Unsupported fitted artwork wall target')
            record['target'] = dict(target)
            result['fittedArtworks'].append(record)
    return result
