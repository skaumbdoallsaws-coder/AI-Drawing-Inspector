"""Bounded upright wall mounting against a revision-bound asset face.

This proves geometric alignment, not anchor capacity or an installation rating.
The child rear (-Z) face mounts on one of a support's upright AABB faces: +/-Z, where localX places
the child along the support's X axis, or +/-X (a wall that runs along its own Z axis), where localZ
places it along the support's Z axis. localY is the child's base above the support's base.
"""
import math
from collections.abc import Mapping

FIELDS = {'family', 'supportPlacementId', 'supportAssetDefinitionRevision', 'face',
          'localX', 'localY', 'normalGapMeters'}
X_FACE_FIELDS = FIELDS - {'localX'} | {'localZ'}
X_FACES = {'positive_x', 'negative_x'}


def validate_relationship(value):
    if not isinstance(value, Mapping) or value.get('family') != 'wall_attachment':
        raise ValueError('Wall attachment fields are incomplete or unsupported')
    if not isinstance(value.get('face'), str) or value['face'] not in {'positive_z', 'negative_z'} | X_FACES:
        raise ValueError('Wall attachment face must be positive_z, negative_z, positive_x or negative_x')
    along = 'localZ' if value['face'] in X_FACES else 'localX'
    if set(value) != (X_FACE_FIELDS if along == 'localZ' else FIELDS):
        raise ValueError('Wall attachment fields are incomplete or unsupported')
    for key in ('supportPlacementId', 'supportAssetDefinitionRevision'):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError('Wall attachment requires '+key)
    for key in (along, 'localY', 'normalGapMeters'):
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
            face=relation['face'];gap=relation['normalGapMeters']
            positive=face.startswith('positive')
            # Canonical equipment is centered in X/Z, with its base at Y=0, so its rear face is at
            # b.minimum.z and it spans its X extent along the face.
            normal='x' if face in X_FACES else 'z'
            depth=(a['maximum'][normal]+gap-b['minimum']['z'] if positive else
                   a['minimum'][normal]-gap+b['minimum']['z'])
            if normal=='x':
                local=(depth,relation['localY'],relation['localZ'])
                spans=[('z',relation['localZ']),('y',relation['localY'])]
            else:
                local=(relation['localX'],relation['localY'],depth)
                spans=[('x',relation['localX']),('y',relation['localY'])]
            pp=_point3(parent['transform']['position'],'support position')
            cp=_point3(child['transform']['position'],'child position')
            offset=_rotate_vector(local,pq)
            if any(abs(cp[i]-pp[i]-offset[i])>1e-6 for i in range(3)):
                raise ValueError('Wall attachment position no longer matches its support')
            sign=1 if positive else -1
            outward=_rotate_vector((sign,0,0) if normal=='x' else (0,0,sign),pq)
            facing=_rotate_vector((0,0,1),cq)
            if any(abs(outward[i]-facing[i])>1e-6 for i in range(3)):
                raise ValueError('Mounted equipment must face away from the selected wall face')
            for axis,origin in spans:
                own='y' if axis=='y' else 'x'   # along a face the child spans its own X extent
                overlap=min(a['maximum'][axis],origin+b['maximum'][own])-max(a['minimum'][axis],origin+b['minimum'][own])
                if overlap <= 1e-6: raise ValueError('Equipment has no projected contact with its support face')
            contacts.add(tuple(sorted((pid,sid))));mounted.add(pid)
            findings.append(_finding('wall_attachment_safety_unverified','unverified',
                'Wall mounting is geometrically aligned; structure, fixings and load capacity are unverified.',
                subject_refs=(sid,pid),details={'face':relation['face']}))
        except (ValueError,TypeError,KeyError) as error:
            findings.append(_finding('invalid_wall_attachment','error',str(error),subject_refs=tuple(filter(None,(sid,pid)))))
    return findings,contacts,mounted
