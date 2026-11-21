"""AG Drive STG1 meshes -> glTF 2.0 binary (pre-compression). Z-up -> Y-up, clockwise -> counter-clockwise winding,
GL bottom-up V -> glTF top-down V (the texture images are written upright to match).
Vertex layout (stride 32): pos f32x3 | normal i16x4 (w = sky visibility) | uv f32x2 | color u8x4 (rgb baked light, a sun visibility)
Vertex layout (stride 20): pos f32x3 | uv f32x2 (self-lit screens)"""
import re, os, json, struct, numpy as np

# material name prefix "X#" -> shader family (IonCore naming convention)
PREFIX_MODE = {'': 'env', 'd': 'env', 'c': 'env', 't': 'track', 'e': 'emissive', 'm': 'metal', 'g': 'grate',
               'n': 'neon', '1': 'scroll', '2': 'scroll_air', 'w': 'water'}
def mat_info(mat, stride):
    pre = ''; rest = mat
    m = re.match(r'^(\w)#(.*)$', mat)
    if m: pre, rest = m.group(1), m.group(2)
    rest = re.sub(r'^\(\d+\)', '', rest)
    tex = os.path.splitext(rest)[0].replace(' ', '_')
    if pre == 'a': mode = 'ads_cycle'
    elif stride == 20: mode = 'selflit'
    elif tex == 'flares': mode = 'additive'
    else: mode = PREFIX_MODE.get(pre, 'env')
    return tex, mode, os.path.splitext(rest)[0]

def build(meshes, tex_dir_rel='tex'):
    bin_ = bytearray(); views = []; accs = []; gmeshes = []; nodes = []; mats = []; matidx = {}; texs = {}; images = []; textures = []
    def add(arr, target=None, comp=None, norm=False, typ='VEC3', minmax=False):
        nonlocal bin_
        while len(bin_) % 4: bin_.append(0)
        b = arr.tobytes(); views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=len(b), **({'target': target} if target else {}))); bin_ += b
        a = dict(bufferView=len(views) - 1, componentType=comp, count=int(arr.shape[0]), type=typ)
        if norm: a['normalized'] = True
        if minmax: a['min'] = arr.min(0).tolist(); a['max'] = arr.max(0).tolist()
        accs.append(a); return len(accs) - 1
    stats = []; texsrc = {}
    for mi, m in enumerate(meshes):
        tex, mode, src = mat_info(m['mat'], m['stride'])
        if not m['parts']: continue
        V = np.concatenate([q['V'] for q in m['parts']]); base = 0; I = []
        for q in m['parts']:
            I.append(q['I'].astype(np.uint32) + base); base += len(q['V'])
        if len(V) == 0: continue
        I = np.concatenate(I)
        if len(I) == 0: continue
        I = np.ascontiguousarray(I.reshape(-1, 3)[:, [0, 2, 1]]).reshape(-1)
        p = V[:, 0:12].copy().view('<f4').reshape(-1, 3)
        pos = np.stack([p[:, 0], p[:, 2], -p[:, 1]], 1).astype(np.float32)
        attrs = {'POSITION': add(pos, 34962, 5126, minmax=True)}
        if m['stride'] == 32:
            n = V[:, 12:20].copy().view('<i2').reshape(-1, 4).astype(np.float32) / 32767.0
            nn = np.stack([n[:, 0], n[:, 2], -n[:, 1]], 1); l = np.linalg.norm(nn, axis=1, keepdims=True); l[l < 1e-6] = 1
            nn = (nn / l).astype(np.float32); nn[(l[:, 0] < 1e-6)] = (0, 1, 0)
            attrs['NORMAL'] = add(nn, 34962, 5126)
            uv = V[:, 20:28].copy().view('<f4').reshape(-1, 2).copy(); uv[:, 1] = 1.0 - uv[:, 1]
            attrs['TEXCOORD_0'] = add(np.ascontiguousarray(uv, np.float32), 34962, 5126, typ='VEC2')
            sky = np.stack([np.clip(n[:, 3], 0, 1), np.zeros(len(n), np.float32)], 1).astype(np.float32)
            attrs['TEXCOORD_1'] = add(sky, 34962, 5126, typ='VEC2')
            attrs['COLOR_0'] = add(np.ascontiguousarray(V[:, 28:32]), 34962, 5121, norm=True, typ='VEC4')
        else:
            uv = V[:, 12:20].copy().view('<f4').reshape(-1, 2).copy(); uv[:, 1] = 1.0 - uv[:, 1]
            attrs['TEXCOORD_0'] = add(np.ascontiguousarray(uv, np.float32), 34962, 5126, typ='VEC2')
        ia = add(I, 34963, 5125, typ='SCALAR')
        key = (tex, mode)
        if key not in matidx:
            if tex not in texs:
                images.append(dict(uri='%s/%s.png' % (tex_dir_rel, tex))); textures.append(dict(source=len(images) - 1, sampler=0)); texs[tex] = len(textures) - 1
                texsrc[tex] = src
            mats.append(dict(name='%s|%s' % (mode, tex), pbrMetallicRoughness=dict(baseColorTexture=dict(index=texs[tex]), metallicFactor=0.0, roughnessFactor=1.0),
                             doubleSided=mode in ('grate', 'additive', 'selflit', 'ads_cycle', 'scroll_air'),
                             **({'alphaMode': 'BLEND'} if mode == 'scroll_air' else {}), extras=dict(mode=mode, tex=tex)))
            matidx[key] = len(mats) - 1
        gmeshes.append(dict(name='m%03d' % mi, primitives=[dict(attributes=attrs, indices=ia, material=matidx[key])]))
        am = re.match(r'^d#\((\d+)\)', m['mat'])
        nodes.append(dict(mesh=len(gmeshes) - 1, **({'name': 'anim_%03d_%d' % (int(am.group(1)), mi), 'extras': {'aga': int(am.group(1))}} if am else {})))
        stats.append((m['mat'], len(V), len(I) // 3))
    gl = dict(asset=dict(version='2.0', generator='AGDriveConverter'), scene=0, scenes=[dict(nodes=list(range(len(nodes))))], nodes=nodes, meshes=gmeshes,
              materials=mats, textures=textures, images=images, samplers=[dict(magFilter=9729, minFilter=9987, wrapS=10497, wrapT=10497)],
              accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    js = json.dumps(gl, separators=(',', ':')).encode()
    while len(js) % 4: js += b' '
    while len(bin_) % 4: bin_.append(0)
    out = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_)) + struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(bin_), 0x004E4942) + bytes(bin_)
    used_anim = sorted({int(mm.group(1)) for s in stats for mm in [re.match(r'^d#\((\d+)\)', s[0])] if mm})
    return out, dict(meshes=len(stats), verts=int(sum(s[1] for s in stats)), tris=int(sum(s[2] for s in stats)), textures=texsrc, anim_records=used_anim)

def read_glb(d):
    n = struct.unpack_from('<I', d, 12)[0]; return json.loads(d[20:20 + n]), d[20 + n:]
def write_glb(j, rest):
    js = json.dumps(j, separators=(',', ':')).encode()
    while len(js) % 4: js += b' '
    return struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + len(rest)) + struct.pack('<II', len(js), 0x4E4F534A) + js + rest
