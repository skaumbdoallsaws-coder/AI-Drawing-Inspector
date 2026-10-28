"""Site tools use the existing revision-bound gateway; no geocoder or file access."""
from copy import deepcopy
from ai_inspector.facility_layout.site_context import KEY, AREA_KINDS, AREA_SURFACES, normalize_site_context, analyze_site_context
from ai_inspector.facility_layout.site_context import REFERENCE_KINDS, REFERENCE_SOURCES
from ai_inspector.facility_layout.site_context import SOURCES as SITE_IMAGE_SOURCES, PROPERTY_SOURCES
from ai_inspector.facility_layout.site_roads import summarize_roads
from .edit_schemas import obj, array, number, text, nullable

STEP_TOOLS = {'plan_warehouse_building': 'building', 'plan_warehouse_zones': 'zones',
              'plan_floor_markings': 'markings', 'plan_storage_layout': 'layout', 'plan_site_docks': 'docks',
              'plan_site_parking': 'parking', 'plan_warehouse_contents': 'contents'}
NAMES = frozenset({'inspect_site_context', 'analyze_site_fit', 'look_at_site_photo', 'trace_site_feature',
                   'plan_design_paint', 'suggest_site_references', 'check_site_references', 'prepare_layout_pdf',
                   *STEP_TOOLS})
CATALOG_TOOLS = frozenset({'plan_storage_layout', 'plan_warehouse_contents'})  # model sizes and revisions
PHOTO_NAMES = frozenset({'look_at_site_photo', 'trace_site_feature'})


def schemas():
    point = obj({axis:number(-5000,5000) for axis in ('x','z')})
    boundary = array(point,128,3)
    identity = text(80,pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$')
    pose = obj({'x':number(-5000,5000),'z':number(-5000,5000),'bearingDegrees':number(-360,360)})
    edge = {'type':'integer','minimum':0,'maximum':127}
    property_schema = obj({'boundary':boundary,'source':{'enum':list(PROPERTY_SOURCES)},
        'sourceLabel':text(160,0),'setbacksMeters':obj({kind:number(0,500) for kind in ('street','side','rear')},[]),
        'streetEdges':array(edge,128,uniqueItems=True),'rearEdges':array(edge,128,uniqueItems=True),
        'entrances':array(obj({'entranceId':identity,'edgeIndex':edge,'x':number(-5000,5000),'z':number(-5000,5000),
            'use':{'enum':['shared','trucks','cars','pedestrians']},'widthMeters':number(.5,50)},
            ['entranceId','edgeIndex','x','z']),64)},['boundary'])
    area = obj({'areaId':identity,'label':text(120),'kind':{'enum':list(AREA_KINDS)},
                'surface':{'enum':list(AREA_SURFACES)},'boundary':boundary},['areaId','label','kind','boundary'])
    georeference = obj({'datum':{'const':'WGS84'},'originLatitude':number(-89,89),'originLongitude':number(-180,180),
        'placedBy':{'enum':['address','coordinates','map']},'label':text(160,0)},['originLatitude','originLongitude'])
    image = obj({'imageId':text(64,64,pattern='^[a-f0-9]{64}$'),
        'imagePath':text(256,pattern=r'^/api/facility-site-imagery/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/[a-f0-9]{64}\.jpg$'),
        'source':{'enum':sorted(SITE_IMAGE_SOURCES)},'captured':nullable(text(40,0)),
        'geoBounds':obj({'south':number(-89,89),'north':number(-89,89),'west':number(-180,180),'east':number(-180,180)}),
        'widthPixels':{'type':'integer','minimum':16,'maximum':4096},'heightPixels':{'type':'integer','minimum':16,'maximum':4096},
        'license':{'const':'public_domain'},'attribution':text(160),'corners':array(point,4,4),'metersPerPixel':number(0,1000)},
        ['imageId','imagePath','source','captured','geoBounds','widthPixels','heightPixels'])
    context = obj({'version':{'const':1},'georeference':georeference,'buildingPose':pose,
        'property':property_schema,'areas':array(area,64),'imagery':array(image,4)},['version','georeference'])
    located = {'x':number(-5000,5000),'z':number(-5000,5000),'accuracyMeters':number(0.005,100)}
    reference = obj({'referenceId':text(43,pattern='^rp-[a-z0-9][a-z0-9-]{0,39}$'),'label':text(120),
                     'kind':{'enum':list(REFERENCE_KINDS)},'source':{'enum':list(REFERENCE_SOURCES)},**located,
                     'measured':obj({**located,'source':{'enum':list(REFERENCE_SOURCES)}},['x','z','source'])},
                    ['referenceId','label','kind','source','x','z','accuracyMeters'])
    return {'siteContext':context,'buildingPose':pose,'siteArea':area,'siteAreaId':identity,
            'siteReference':reference,'siteReferenceId':text(43,pattern='^rp-[a-z0-9][a-z0-9-]{0,39}$')}


def tool_specs():
    from ai_inspector.facility_layout.site_paint import COLORS as PAINT_COLORS, WALL_CHOICES
    paint_color = text(24)
    return [{'name':'inspect_site_context','description':
        'Inspect the bound saved site: user-supplied lot, true bearings, building pose, setbacks, entrances, '
        'imagery provenance, paged outdoor areas, deterministic findings, and nearby roads and railways '
        '(US Census centerlines: kind, distance, side of the building, lot edges they run along). '
        'No network calls or edits. '
        'Area boundaries are optional and paged; never infer a legal property line from imagery.',
        'input_schema':obj({'areaOffset':{'type':'integer','minimum':0,'maximum':64},
            'areaLimit':{'type':'integer','minimum':1,'maximum':4},'includeAreaBoundaries':{'type':'boolean'}},[])},
        {'name':'plan_warehouse_building','description':
        'Build step 2: place exactly the warehouse the user asked for, after the lot is measured. lengthMeters runs '
        'along alignWith (a street name from inspect_site_context roads, or lot for the traced lot\'s long side) and '
        'widthMeters across it. It is centred on the traced lot unless fromStreetMeters (from that street\'s lot line '
        'to the near wall) or centre (property metres) says where. dockWall is the wall the docks will use: pass it, '
        'and pass the same dockWall to the zones, markings, layout and docks steps. Makes the plan size, building pose, '
        'plain walls (colours come with the paint step), the slab, and the traced lot paved. When the building would '
        'cross the setbacks it refuses and says where it would fit: tell the user and ask; never change their numbers. '
        'Replaces an earlier building and everything built on it. Returns a package to stage with '
        'preview_planned_design; no edits.',
        'input_schema':obj({'lengthMeters':number(20,600),'widthMeters':number(20,600),'heightMeters':number(4,30),
            'alignWith':text(80),'dockWall':{'enum':['north','east','south','west']},'fromStreetMeters':number(0,400),
            'centre':obj({'x':number(-5000,5000),'z':number(-5000,5000)}),'areaId':text(80)},['lengthMeters','widthMeters'])},
        {'name':'plan_warehouse_zones','description':
        'Build step 3 (dockWall: the wall the user chose for the docks when the building was made): receiving and '
        'shipping side by side along the dock wall (stagingDepthMeters deep, default 15 m; '
        'receivingShare of the wall, default 0.5), storage behind them, and a forklift charging bay along the back '
        'wall (chargingLengthMeters x chargingDepthMeters, default 20 x 4 m; 0 for none). Replaces earlier zones of this '
        'step. Package for preview_planned_design; no edits.',
        'input_schema':obj({'dockWall':{'enum':['north','east','south','west']},'stagingDepthMeters':number(4,60),
            'receivingShare':number(0.1,0.9),'chargingLengthMeters':number(0,300),'chargingDepthMeters':number(0,20)},
            ['dockWall'])},
        {'name':'plan_floor_markings','description':
        'Build step 4: white staging lanes where the dock doors will be (stagingLanes; give the number of doors the user '
        'wants, so the docks step lines its doors up with them; default as many as the wall takes), yellow edge lines '
        'along the 3.7 m cross aisle between staging and storage, and a green walkway (walkwayWidthMeters, default 1). '
        'Package for preview_planned_design; no edits.',
        'input_schema':obj({'dockWall':{'enum':['north','east','south','west']},
            'stagingLanes':{'type':'integer','minimum':0,'maximum':60},'walkwayWidthMeters':number(0,5),
            'aisleEdgeLines':{'type':'boolean'}},['dockWall'])},
        {'name':'plan_storage_layout','description':
        'Build step 5: the rack rows and aisles drawn in 2D, no models yet: back-to-back pallet-rack rows with '
        'aisleWidthMeters aisles (default 3.7 m, counterbalance forklifts), running across the building square to the '
        'dock wall (rowDirection across, the default) or along it (along); a cross aisle in front, a middle aisle when '
        'the rows are long (crossAisle none leaves it out) and a back aisle by the charging bay. The contents step fills '
        'the rows with racks. Package for preview_planned_design; no edits.',
        'input_schema':obj({'dockWall':{'enum':['north','east','south','west']},'rowDirection':{'enum':['across','along']},
            'aisleWidthMeters':number(2.5,6),'crossAisle':{'enum':['auto','none']}},['dockWall'])},
        {'name':'plan_site_docks','description':
        'Build step 6: dock doors on the dock wall (doors; default the staging-lane count, so they line up), the '
        'truck court beyond it (truckCourtDepthMeters, default 40 m), a truck drive with its own entrance on '
        'entranceStreet (default the best street it reaches, never across a railway), the court\'s circulation '
        'arrows, the paving and the route to the main road. Refuses when the court or the drive does not fit: explain '
        'why and ask. Package for preview_planned_design; no edits.',
        'input_schema':obj({'dockWall':{'enum':['north','east','south','west']},
            'doors':{'type':'integer','minimum':1,'maximum':60},'truckCourtDepthMeters':number(20,60),
            'entranceStreet':text(80)},['dockWall'])},
        {'name':'plan_site_parking','description':
        'Build step 7: the employee car park for `stalls` (default by building size) on `side` of the building, with '
        'its own drive and entrance on entranceStreet, the employee door and the walk to it. It keeps clear of the '
        'trucks: its entrance at least 40 m from the truck entrance, never between the truck entrance and the court, at '
        'least 10 m from the court and the truck drive. Refuses with the rule it could not keep, and reports when '
        'fewer stalls fit: tell the user and ask. Package for preview_planned_design; no edits.',
        'input_schema':obj({'stalls':{'type':'integer','minimum':1,'maximum':400},
            'side':{'enum':['north','east','south','west']},'entranceStreet':text(80)},[])},
        {'name':'plan_warehouse_contents','description':
        'Build step 8: the models, in their plain colours: racks in every outlined rack row (racks, default true), '
        'forklifts in the charging bay (forklifts, default 4), trucks backed up to `trucks` dock doors spread along '
        'the wall, and cars in `cars` stalls. Replaces earlier contents. Package for preview_planned_design; no edits.',
        'input_schema':obj({'racks':{'type':'boolean'},'forklifts':{'type':'integer','minimum':0,'maximum':40},
            'trucks':{'type':'integer','minimum':0,'maximum':60},'cars':{'type':'integer','minimum':0,'maximum':400}},[])},
        {'name':'plan_design_paint','description':
        'Build step 9, last: the colours the user names, as one package to stage with preview_planned_design. '
        'Pass only the items the user asked for, in the user\'s colours; nothing else is painted or added. walls: '
        'panel color, bandColor only when a band along the top is asked for, logoWalls only when the logo is '
        'asked for on the walls (compass sides, or beside_docks for the two walls either side of the dock wall). '
        'pavementLogo true only when the logo is asked for on the yard pavement. trucks: cab, container and chassis '
        'colours. racks: upright and beam colours. cars: colors in turn, or none for everyday colours. A colour is '
        'a plain name ('+', '.join(PAINT_COLORS)+') or #rrggbb. Models are coloured by set_component_materials with '
        'the exact visualSha256 of each saved visual, so no component inspection is needed. Returns the counts and '
        'the look in words; no edits.',
        'input_schema':obj({'walls':obj({'color':paint_color,'bandColor':paint_color,
            'logoWalls':array({'enum':list(WALL_CHOICES)},5,1,uniqueItems=True)},['color']),
            'pavementLogo':{'type':'boolean'},
            'trucks':obj({'cabColor':paint_color,'containerColor':paint_color,'chassisColor':paint_color}),
            'racks':obj({'uprightColor':paint_color,'beamColor':paint_color}),
            'cars':obj({'colors':array(paint_color,16,1)},[])},[],minProperties=1)},
        {'name':'suggest_site_references','description':
        'Propose reference points for setting the building out on site: the property corners first (county '
        'parcel, about 3 m), then corners of the existing pavement traced from the photo (about 6 m to true '
        'ground), well spread, the first nearest the building. Also lists road intersections and the rail crossing '
        'near the site (road map, about 8 m): use those only to check the photo against the map, never as '
        'references. Stage the points you keep with upsert_site_reference in one batch, keeping each suggested '
        'referenceId, label, kind, source, position and accuracy, and tell the user which sources they come from '
        'and how far each can be trusted. No edits.',
        'input_schema':obj({'maxPoints':{'type':'integer','minimum':1,'maximum':8}},[])},
        {'name':'prepare_layout_pdf','description':
        'Prepare the printable 2D layout as a PDF from the saved layout, 11 x 17 in: for a layout placed on a site '
        'the site plan (C-101) and the setting-out plan (C-102, with its reference points and fit check), and '
        'always the floor plan (A-101). It is built once here to check it, and the chat shows it as a file the '
        'user opens in the app. Tell the user which sheets it has; unsaved edits are not in it. No edits.',
        'input_schema':obj({},[])},
        {'name':'check_site_references','description':
        'Check how well the sources agree. At the mapped road intersections and rail crossing near the building, '
        'the road map is compared with the photo, whose own road centres are found across each road; a crossing '
        'the photo does not show clearly is left out rather than guessed. Where reference points have a measured '
        '(surveyed) position, the plan is fitted onto them with a move and turn, never a stretch, and each '
        'point\'s residual, the average, the worst and how far the building corners move are reported. Explain '
        'the result in plain words. A suggested move of the building is only staged when the user asks. No edits.',
        'input_schema':obj({},[])},
        {'name':'look_at_site_photo','description':
        'Find paved areas on the site\'s stored aerial photo (no network): lots, yards, slabs and flat roofs, '
        'lettered A, B, C... largest first. Each comes with its outline in property metres, area, length x width, '
        'long-axis bearing, direction and distance from the building, and roads within 15 m. When your runtime shows '
        'images, the photo also comes back with these outlines and a 50 m grid labelled in property metres (x east, '
        'z north). Use it to find the feature the user means, then trace_site_feature with a box around just that '
        'part. Lots and flat roofs can look alike in numbers: ask the user when unsure. No edits.',
        'input_schema':obj({'minAreaSquareMeters':number(200,100000)},[])},
        {'name':'trace_site_feature','description':
        'Trace one paved feature on the stored photo: at a property-frame point inside it (x, z), or the largest '
        'paved region inside a box (minX, maxX, minZ, maxZ) that keeps only the part meant, or withinProperty '
        'true for the largest paved region inside the property line (the lot on the user\'s property, apart from '
        'pavement and roofs beyond it; a box given too is narrowed to the property). Returns the outline '
        '(property metres, at most 48 points), area, perimeter, length x width, long-axis bearing, accuracy (about '
        'two photo pixels), the photo it came from and roads within 15 m. To keep it, stage upsert_site_area with '
        'kind existing_pavement and a label naming the photo and its date. It is existing pavement as seen on a '
        'dated photo, never a property line. No edits.',
        'input_schema':obj({'x':number(-5000,5000),'z':number(-5000,5000),
            'box':obj({key:number(-5000,5000) for key in ('minX','maxX','minZ','maxZ')},['minX','maxX','minZ','maxZ']),
            'withinProperty':{'type':'boolean'}},[])},
        {'name':'analyze_site_fit','description':
        'Search a bounded deterministic grid for building poses and optional truck-court/parking reservations '
        'inside the authored lot and requested setbacks, avoiding existing outdoor areas. No edits. '
        'dockWallEdge uses the unrotated building edges: 0 south, 1 east, 2 north, 3 west. '
        'Dimensions are conceptual assumptions, not verified standards. Parking envelopes include aisle space '
        'but do not author stalls or entrance connections. Empty candidates are not proof of infeasibility. '
        'Inspect the site first and preserve all existing interior equipment when applying any resize.',
        'input_schema':obj({'widthMeters':number(1,1000),'depthMeters':number(1,1000),
            'bearingsDegrees':array(number(-360,360),8,1,uniqueItems=True),
            'dockWallEdge':{'type':'integer','minimum':0,'maximum':3},'truckCourtDepthMeters':number(5,150),
            'parkingCount':{'type':'integer','minimum':0,'maximum':200},'stallWidthMeters':number(1.5,6),
            'stallDepthMeters':number(3,12),'driveAisleWidthMeters':number(3,15)},['widthMeters','depthMeters'])}]


def bounded_analysis(layout):
    result = analyze_site_context(layout)
    findings = result['findings']
    result['findingCount'] = len(findings)
    result['findingsTruncated'] = len(findings) > 40
    result['findings'] = findings[:40]
    return result


def read_site(layout, name, arguments, photo_path=None, catalog=None, inventory=None):
    if name == 'plan_design_paint':
        return paint_design(layout, arguments, inventory)
    if name == 'check_site_references':
        from ai_inspector.facility_layout.site_reference_fit import check_references
        from ai_inspector.facility_layout.site_trace import _site_photo
        raw = (layout.get('extensions') or {}).get(KEY)
        if raw is None:
            return {'available':False,'reason':'Place the layout on a site first.'}
        site = normalize_site_context(raw, layout)
        photo = _site_photo(site, photo_path) if site.get('imagery') and photo_path is not None else None
        return check_references(site, layout, photo)
    if name == 'suggest_site_references':
        from ai_inspector.facility_layout.site_references import suggest_references
        raw = (layout.get('extensions') or {}).get(KEY)
        if raw is None:
            return {'available':False,'reason':'Place the layout on a site first.'}
        return suggest_references(normalize_site_context(raw, layout), layout, arguments.get('maxPoints', 5))
    if name in PHOTO_NAMES:
        return read_photo(layout, name, arguments, photo_path)
    if name in STEP_TOOLS:
        return plan_step(layout, STEP_TOOLS[name], arguments, catalog)
    if name == 'analyze_site_fit':
        from ai_inspector.facility_layout.site_fit import analyze_site_fit
        return analyze_site_fit(layout,arguments)
    raw = (layout.get('extensions') or {}).get(KEY)
    if raw is None:
        return {'available':False,'reason':'Place the layout and draw its boundary in the Site tab first.'}
    site = normalize_site_context(raw,layout)
    offset, limit = arguments.get('areaOffset',0), arguments.get('areaLimit',4)
    areas = deepcopy(site.get('areas',[])[offset:offset+limit])
    if not arguments.get('includeAreaBoundaries',False):
        for area in areas:
            area.pop('boundary',None)
    analysis = bounded_analysis(layout)
    return {'available':True,'georeference':site['georeference'],'buildingPose':site['buildingPose'],
        'property':site.get('property'),'areas':areas,'areaCount':len(site.get('areas',[])),
        'nextAreaOffset':offset+limit if offset+limit<len(site.get('areas',[])) else None,
        'imagery':site['imagery'],
        'referenceLayers':[{'layer':o['layer'],'detail':o['detail'],'source':o['source'],'fetched':o['captured'],
                            'attribution':o['attribution']} for o in site.get('overlays',[])],
        'layerChecks':site.get('layerChecks'),
        'roads':summarize_roads(layout,site),
        'routes':[{key:value for key,value in route.items() if key!='points'} for route in site.get('routes',[])],
        'references':site.get('references',[]),
        'analysis':analysis}


def read_photo(layout, name, arguments, photo_path):
    """Sage's look at, and traces on, the photo the site already stores. Never a network call."""
    from ai_inspector.facility_layout.site_trace import annotated_photo, find_features, trace_feature
    raw = (layout.get('extensions') or {}).get(KEY)
    if raw is None:
        return {'available':False,'reason':'Place the layout and fetch its photo in the Site tab first.'}
    if photo_path is None:
        raise ValueError('The stored site photo is not available to this tool.')
    site = normalize_site_context(raw,layout)
    frame = 'Property metres: x east, z north, from the site point. Outlines are about two photo pixels accurate.'
    if name == 'look_at_site_photo':
        found = find_features(layout,site,photo_path,arguments.get('minAreaSquareMeters',600.0))
        photo = found.pop('photoObject')
        return {'available':True,'photo':found['photo'],'frame':frame,'features':found['features'],
                'note':'Existing pavement and flat roofs as seen on a dated photo; confirm the one meant with the user '
                       'when more than one fits.',
                '_image':{'mimeType':'image/jpeg','data':annotated_photo(photo,found['features'])}}
    box = arguments.get('box')
    if arguments.get('withinProperty'):
        prop = site.get('property')
        if not prop:
            return {'available':False,'reason':'The site has no property line yet: take the county parcel or draw it in '
                                               'the Site tab first.'}
        xs, zs = [p['x'] for p in prop['boundary']], [p['z'] for p in prop['boundary']]
        bounds = {'minX':min(xs),'maxX':max(xs),'minZ':min(zs),'maxZ':max(zs)}
        box = bounds if box is None else {'minX':max(box['minX'],bounds['minX']),'maxX':min(box['maxX'],bounds['maxX']),
                                          'minZ':max(box['minZ'],bounds['minZ']),'maxZ':min(box['maxZ'],bounds['maxZ'])}
        if box['minX'] >= box['maxX'] or box['minZ'] >= box['maxZ']:
            raise ValueError('That box lies outside the property line.')
    if box is None and (arguments.get('x') is None or arguments.get('z') is None):
        raise ValueError('Give x and z, a box, or withinProperty.')
    traced = trace_feature(layout,site,photo_path,arguments.get('x'),arguments.get('z'),box)
    return {'available':True,'frame':frame,**traced,
            'next':'Show the user the size; to keep it, stage upsert_site_area with kind existing_pavement.'}


def paint_design(layout, arguments, inventory):
    """The planned look on the saved trucks, pickups and racks (site_paint.py), as one package."""
    from ai_inspector.facility_layout.site_paint import PaintError, plan_paint
    if inventory is None:
        return {'available':False,'reason':'Component inspection is not configured for this host.'}
    try:
        return plan_paint(layout, inventory, arguments)
    except PaintError as error:
        return {'available':False,'reason':str(error)}


def plan_step(layout, step, arguments, catalog=None):
    """One step of the step-by-step build (site_steps.py): its operations for one review, and a summary."""
    from ai_inspector.facility_layout import site_steps
    if step == 'layout':
        return site_steps.plan_layout(layout, arguments, catalog)
    if step == 'contents':
        return site_steps.plan_contents(layout, arguments, catalog)
    return site_steps.PLANNERS[step](layout, arguments)
