"""Bounded upright wall mounting against a revision-bound asset face.

This proves geometric alignment, not anchor capacity or an installation rating.
The child rear (-Z) face mounts on a support's named +/-Z AABB face.
"""
import math
from collections.abc import Mapping

FIELDS = {'family', 'supportPlacementId', 'supportAssetDefinitionRevision', 'face',
          'localX', 'localY', 'normalGapMeters'}


def validate_relationship(value):
    if not isinstance(value, Mapping) or set(value) != FIELDS or value['family'] != 'wall_attachment':
        raise ValueError('Wall attachment fields are incomplete or unsupported')
    if value['face'] not in {'positive_z', 'negative_z'}:
        raise ValueError('Wall attachment face must be positive_z or negative_z')
    for key in ('supportPlacementId', 'supportAssetDefinitionRevision'):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError('Wall attachment requires '+key)
    for key in ('localX', 'localY', 'normalGapMeters'):
        number=value[key]
        if (isinstance(number,bool) or not isinstance(number,(float,int))
                or abs(number)>10000 or not math.isfinite(number)):
            raise ValueError('Wall attachment '+key+' must be finite and bounded')
    if not 0 <= value['normalGapMeters'] <= .02:
        raise ValueError('Wall mounting gap must be between 0 and 0.02 m')


def check_wall_attachments(placements, records, catalog):
    from .spatial import _asset_field, _catalog_asset, _finding, _point3, _quaternion, _rotate_vector
    findings, contacts, mounted = [], set(), set()
    for pid, child in sorted(placements.items()):
        relation=child.get('snapRelationship')
        if not isinstance(relation,Mapping) or relation.get('family')!='wall_attachment': continue
        sid=str(relation.get('supportPlacementId') or '')
        try:
            validate_relationship(relation)
            parent=placements.get(sid)
            if not parent or not records.get(pid) or not records.get(sid):
                raise ValueError('Wall attachment support or geometry is missing')
            seen={pid}; cursor=sid
            while cursor:
                if cursor in seen: raise ValueError('Wall attachment cycle')
                seen.add(cursor)
                next_relation=placements.get(cursor,{}).get('snapRelationship') or {}
                cursor=next_relation.get('supportPlacementId')
            if parent['assetDefinitionRevision']!=relation['supportAssetDefinitionRevision']:
                raise ValueError('Wall support asset revision changed')
            support=_catalog_asset(catalog,parent['assetId'],parent['assetDefinitionRevision'])
            asset=_catalog_asset(catalog,child['assetId'],child['assetDefinitionRevision'])
            tags=set(_asset_field(support,'tags',[]))
            if not tags.intersection({'wall','mounting-bracket'}):
                raise ValueError('Support is not an authored wall or mounting bracket')
            a=_asset_field(support,'geometry',{})['aabb']
            b=_asset_field(asset,'geometry',{})['aabb']
            if (abs(b['minimum']['y'])>1e-6 or any(abs(b['minimum'][axis]+b['maximum'][axis])>1e-6 for axis in ('x','z'))):
                raise ValueError('Mounted equipment must have a centered X/Z frame and a Y=0 base')
            pq=_quaternion(parent['transform']['quaternion']); cq=_quaternion(child['transform']['quaternion'])
            for obj,q in ((parent,pq),(child,cq)):
                up=_rotate_vector((0,1,0),q)
                if abs(float(obj['transform'].get('scale',1))-1)>1e-8 or any(abs(up[i]-(1 if i==1 else 0))>1e-6 for i in range(3)):
                    raise ValueError('Wall attachments require upright, unscaled assets')
            positive=relation['face']=='positive_z'
            # Canonical equipment is centered in X/Z, with its base at Y=0.
            z=(a['maximum']['z']+relation['normalGapMeters']-b['minimum']['z'] if positive else
               a['minimum']['z']-relation['normalGapMeters']+b['minimum']['z'])
            local=(relation['localX'],relation['localY'],z)
            pp=_point3(parent['transform']['position'],'support position')
            cp=_point3(child['transform']['position'],'child position')
            offset=_rotate_vector(local,pq)
            if any(abs(cp[i]-pp[i]-offset[i])>1e-6 for i in range(3)):
                raise ValueError('Wall attachment position no longer matches its support')
            outward=_rotate_vector((0,0,1 if positive else -1),pq)
            facing=_rotate_vector((0,0,1),cq)
            if any(abs(outward[i]-facing[i])>1e-6 for i in range(3)):
                raise ValueError('Mounted equipment must face away from the selected wall face')
            for axis,origin in [('x',relation['localX']),('y',relation['localY'])]:
                overlap=min(a['maximum'][axis],origin+b['maximum'][axis])-max(a['minimum'][axis],origin+b['minimum'][axis])
                if overlap <= 1e-6: raise ValueError('Equipment has no projected contact with its support face')
            contacts.add(tuple(sorted((pid,sid))));mounted.add(pid)
            findings.append(_finding('wall_attachment_safety_unverified','unverified',
                'Wall mounting is geometrically aligned; structure, fixings and load capacity are unverified.',
                subject_refs=(sid,pid),details={'face':relation['face']}))
        except (ValueError,TypeError,KeyError) as error:
            findings.append(_finding('invalid_wall_attachment','error',str(error),subject_refs=tuple(filter(None,(sid,pid)))))
    return findings,contacts,mounted
