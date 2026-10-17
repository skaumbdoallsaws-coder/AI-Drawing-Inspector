"""Editable small-sided soccer markings and a dimensioned concept goal."""
import math

FIELD = dict(minX=5, maxX=37, minZ=39, maxZ=57, centerX=21, centerZ=48,
             lineWidth=.08, centerRadius=3, penaltyRadius=6)
RULE_SOURCE = 'https://www.thefa.com/football-rules-governance/lawsandrules/laws/football-5-5/law-1---the-playing-area'


def soccer_markings():
    lines = []

    def line(key, a, b):
        dx, dz = b[0]-a[0], b[1]-a[1]
        lines.append(dict(key=key, x=(a[0]+b[0])/2, z=(a[1]+b[1])/2,
            width=math.hypot(dx,dz), depth=.08, rotation=-math.degrees(math.atan2(dz,dx))))

    def arc(key, x, z, r, start, end, count):
        for i in range(count):
            a,b = [start+(end-start)*j/count for j in (i,i+1)]
            line(key+'-'+str(i), (x+r*math.cos(a),z+r*math.sin(a)),
                 (x+r*math.cos(b),z+r*math.sin(b)))

    for key,a,b in [('south',(5,39),(37,39)),('north',(5,57),(37,57)),
                    ('west',(5,39),(5,57)),('east',(37,39),(37,57)),
                    ('halfway',(21,39),(21,57))]:
        line(key,a,b)
    arc('center-circle',21,48,3,0,math.tau,128)
    arc('west-penalty',5,48,6,-math.pi/2,math.pi/2,96)
    arc('east-penalty',37,48,6,math.pi/2,3*math.pi/2,96)
    for key,x,z,a,b in [('sw',5,39,0,math.pi/2),('se',37,39,math.pi/2,math.pi),
                       ('ne',37,57,math.pi,3*math.pi/2),('nw',5,57,3*math.pi/2,math.tau)]:
        arc('corner-'+key,x,z,.25,a,b,12)
    for key,x in [('center-spot',21),('west-spot',11),('east-spot',31)]:
        lines.append(dict(key=key,x=x,z=48,width=.16,depth=.16,rotation=0))
    return lines


def goal_glb():
    import numpy as np
    import trimesh
    scene = trimesh.Scene()
    frame, net = [], []

    def bar(a,b,r,group):
        a,b = np.array(a),np.array(b)
        mesh = trimesh.creation.cylinder(radius=r,height=np.linalg.norm(b-a),sections=8)
        mesh.apply_transform(trimesh.geometry.align_vectors([0,0,1],b-a))
        mesh.apply_translation((a+b)/2)
        group.append(mesh)

    for x in (-1.54,1.54):
        bar((x,.04,.61),(x,2.04,.61),.04,frame)
        bar((x,.04,-.61),(x,.04,.61),.04,frame)
        bar((x,.04,-.61),(x,2.04,.61),.02,frame)
    bar((-1.54,2.04,.61),(1.54,2.04,.61),.04,frame)
    bar((-1.54,.04,-.61),(1.54,.04,-.61),.04,frame)
    for x in np.linspace(-1.5,1.5,25):
        bar((x,.04,-.61),(x,2.04,.61),.0025,net)
    for y in np.linspace(.04,2.04,17):
        z=-.61+1.22*(y-.04)/2
        bar((-1.5,y,z),(1.5,y,z),.0025,net)
        for x in (-1.54,1.54):
            bar((x,y,z),(x,y,.61),.0025,net)
    for meshes,color,name in [(frame,[240,242,235,255],'White 3 x 2 m goal frame'),
                               (net,[126,142,132,255],'Concept goal net')]:
        mesh=trimesh.util.concatenate(meshes)
        mesh.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name=name,baseColorFactor=color,metallicFactor=0,roughnessFactor=.85))
        scene.add_geometry(mesh,node_name=name)
    return scene.export(file_type='glb')
