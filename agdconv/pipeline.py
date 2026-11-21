"""AG Drive 1.4.5 IPA -> web track explorer. Everything game-specific is read from the user's IPA at run time."""
import io, os, re, csv, json, time, shutil, zipfile, plistlib, subprocess, sys, tempfile, datetime
import numpy as np
from PIL import Image, ImageFilter
from . import luac52, texdec, formats, glb, cubeutil

BUNDLE_ID = 'com.zorgentertainment.agdrive'
VERSION = '1.4.5'

class ConvertError(Exception):
    pass

def resource_dir():
    base = getattr(sys, '_MEIPASS', None)
    return base if base else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def gltfpack_path():
    r = resource_dir()
    for c in ((os.path.join(r, 'bin', 'gltfpack.exe'),) if os.name == 'nt' else (os.path.join(r, 'bin', 'gltfpack'),)):
        if os.path.exists(c): return c
    w = shutil.which('gltfpack')
    if w: return w
    raise ConvertError('gltfpack was not found next to the converter.')

# ---------------------------------------------------------------- IPA access
class IPA:
    def __init__(self, path):
        try: self.z = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as e: raise ConvertError('This file is not a valid IPA (zip) archive: %s' % e)
        names = self.z.namelist()
        apps = sorted({m.group(1) for n in names for m in [re.match(r'^(Payload/[^/]+\.app/)', n)] if m})
        if not apps: raise ConvertError('This IPA has no Payload/*.app folder, so it is not an iOS app archive.')
        self.app = apps[0]
        self.files = {n[len(self.app):]: n for n in names if n.startswith(self.app) and not n.endswith('/')}
    def has(self, name): return name in self.files
    def read(self, name):
        if name not in self.files: raise ConvertError('The IPA is missing %s' % name)
        return self.z.read(self.files[name])
    def validate(self):
        if not self.has('Info.plist'): raise ConvertError('Info.plist was not found in the IPA.')
        try: p = plistlib.loads(self.read('Info.plist'))
        except Exception as e: raise ConvertError('Info.plist could not be read: %s' % e)
        bid = p.get('CFBundleIdentifier'); ver = p.get('CFBundleShortVersionString') or p.get('CFBundleVersion')
        if bid != BUNDLE_ID:
            raise ConvertError('This IPA is not AG Drive (bundle id is "%s", expected "%s").' % (bid, BUNDLE_ID))
        if str(ver) != VERSION:
            raise ConvertError('This is AG Drive version %s. The converter only supports version %s.' % (ver, VERSION))
        return dict(bundle_id=bid, version=ver, name=p.get('CFBundleDisplayName') or p.get('CFBundleName'))

# ---------------------------------------------------------------- helpers
def cross_dir(p):
    """Sun pixel in a 4x3 horizontal-cross skybox image -> direction (game Z-up)."""
    S = p['w'] / 4; col = int(p['x'] // S); row = int(p['y'] // S); lx = (p['x'] % S) / S * 2 - 1; ly = (p['y'] % S) / S * 2 - 1
    if row == 0 and col == 1: d = (lx, ly, 1)
    elif row == 2 and col == 1: d = (lx, -ly, -1)
    else:
        fwd = {0: (-1, 0, 0), 1: (0, 1, 0), 2: (1, 0, 0), 3: (0, -1, 0)}[col]; up = np.array((0, 0, 1.))
        f = np.array(fwd, float); r = np.cross(f, up); d = f + lx * r - ly * up
    d = np.array(d, float); return d / np.linalg.norm(d)

def refine_sun(faces_rgba, d0):
    G = [np.asarray(Image.fromarray(f[:, :, :3]).convert('L').filter(ImageFilter.GaussianBlur(6)), np.float32)[..., None] for f in faces_rgba]
    d0 = np.array(d0) / np.linalg.norm(d0)
    a = np.array([1, 0, 0.]) if abs(d0[0]) < 0.9 else np.array([0, 1, 0.]); u = np.cross(d0, a); u /= np.linalg.norm(u); v = np.cross(d0, u)
    r = np.linspace(-np.tan(np.radians(20)), np.tan(np.radians(20)), 161); X, Y = np.meshgrid(r, r)
    D = d0 + X[..., None] * u + Y[..., None] * v; D /= np.linalg.norm(D, axis=-1, keepdims=True)
    L = cubeutil.sample(G, D)[..., 0]; i = np.unravel_index(L.argmax(), L.shape); d = D[i]
    ang = float(np.degrees(np.arccos(np.clip(d @ d0, -1, 1))))
    return d if ang < 8 else d0

C4 = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], float)
def _quat(R):
    t = np.trace(R)
    if t > 0: s = np.sqrt(t + 1) * 2; return np.array([(R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s, 0.25 * s])
    i = np.argmax(np.diag(R))
    if i == 0: s = np.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2; return np.array([0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s, (R[2, 1] - R[1, 2]) / s])
    if i == 1: s = np.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2; return np.array([(R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s, (R[0, 2] - R[2, 0]) / s])
    s = np.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2; return np.array([(R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s, (R[1, 0] - R[0, 1]) / s])
def _slerp(q0, q1, f):
    d = np.clip(np.sum(q0 * q1, -1, keepdims=True), -1, 1); w = np.arccos(d); sw = np.sin(w); sw[sw < 1e-6] = 1
    a = np.where(w < 1e-4, 1 - f, np.sin((1 - f) * w) / sw); b = np.where(w < 1e-4, f, np.sin(f * w) / sw); return a * q0 + b * q1
def _reduce(T, Q, S, tol_t=2.0, tol_deg=1.0):
    n = len(T); keep = {0, n - 1}; stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2: continue
        f = ((np.arange(i + 1, j) - i) / (j - i))[:, None]
        et = np.linalg.norm(T[i] + (T[j] - T[i]) * f - T[i + 1:j], axis=1) / tol_t
        qi = _slerp(np.repeat(Q[i][None], j - i - 1, 0), np.repeat(Q[j][None], j - i - 1, 0), f)
        eq = np.degrees(2 * np.arccos(np.clip(np.abs(np.sum(qi * Q[i + 1:j], 1)), 0, 1))) / tol_deg
        es = np.abs(S[i] + (S[j] - S[i]) * f[:, 0] - S[i + 1:j]) / 0.002
        e = np.maximum(np.maximum(et, eq), es); k = int(np.argmax(e))
        if e[k] > 1: m = i + 1 + k; keep.add(m); stack += [(i, m), (m, j)]
    return np.array(sorted(keep))

def export_anim(recs, used):
    pfs = [r for r in recs if r['name'] == 'PathFinder']
    if not pfs: raise ConvertError('no PathFinder racing line in the animation file')
    pf = pfs[0]['frames'].astype(np.float64)
    P = pf[::2, 3, :3]; U = pf[::2, 2, :3]; U = U / np.linalg.norm(U, axis=1, keepdims=True)
    Py = np.stack([P[:, 0], P[:, 2], -P[:, 1]], 1); Uy = np.stack([U[:, 0], U[:, 2], -U[:, 1]], 1)
    path = np.concatenate([np.round(Py, 1), np.round(Uy, 3)], 1).reshape(-1).tolist()
    blobs = []; meta = []; off = 0
    for k in used:
        if k >= len(recs): continue
        F = recs[k]['frames'].astype(np.float64)
        if len(F) < 2: continue
        D = np.einsum('ij,njk->nik', np.linalg.inv(F[0]), F)
        N = np.einsum('ij,njk,kl->nil', C4, np.transpose(D, (0, 2, 1)), C4.T)
        T = N[:, :3, 3]; L = N[:, :3, :3]; S = np.cbrt(np.abs(np.linalg.det(L))); Rm = L / S[:, None, None]
        Q = np.array([_quat(r) for r in Rm]); Q /= np.linalg.norm(Q, axis=1, keepdims=True)
        for i in range(1, len(Q)):
            if np.dot(Q[i], Q[i - 1]) < 0: Q[i] = -Q[i]
        moving = np.abs(T).max() > 0.05 or np.degrees(2 * np.arccos(np.clip(np.abs(Q[:, 3]).min(), 0, 1))) > 0.05 or np.abs(S - 1).max() > 1e-3
        if not moving: continue
        keys = _reduce(T, Q, S)
        arr = np.concatenate([keys[:, None], T[keys], Q[keys], S[keys, None]], 1).astype(np.float32)
        blobs.append(arr.tobytes()); meta.append(dict(rec=k, name=recs[k]['name'], frames=len(F), keys=len(keys), offset=off)); off += arr.nbytes
    return dict(fps=30, path_spacing=20, path=path, anims=meta,
                note='path = [x,y,z,upx,upy,upz]* (Y-up) from the PathFinder racing line; anims key layout float32 [frame,tx,ty,tz,qx,qy,qz,qw,scale]'), b''.join(blobs), Py

def shader_params(lua_files, log):
    """Read the handful of shader constants the viewer needs from the GLSL source embedded in the game's shader scripts."""
    src = {}
    for name, data in lua_files.items():
        if name.startswith('shader_'):
            try: src[name[:-5] if name.endswith('.luac') else name] = '\n'.join(luac52.all_strings(luac52.load(data)))
            except Exception: pass
    P = {}; num = r'([0-9]*\.?[0-9]+)'
    def find(script, pat, conv):
        m = re.search(pat, src.get(script, ''))
        if m:
            try: return conv(m)
            except Exception: return None
    v = find('shader_water', r'vec2\(\s*' + num + r'\s*\*\s*a_Position\.x', lambda m: float(m.group(1)))
    if v is not None: P['w_uv'] = v
    v = find('shader_water', r'vec2\(\s*' + num + r'\s*,\s*' + num + r'\s*\)\s*\+\s*uv\.xy\s*\*\s*' + num + r'\s*-\s*ScrollOffset\.\w+\s*\*\s*' + num,
             lambda m: [float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))])
    if v: P['w_o1'] = v[:2]; P['w_s1'] = v[2]; P['w_v1'] = v[3]
    v = find('shader_water', r'vec2\(\s*' + num + r'\s*,\s*' + num + r'\s*\)\s*\+\s*uv\.yx\s*\*\s*' + num + r'\s*\+\s*ScrollOffset\.\w+\s*\*\s*' + num,
             lambda m: [float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))])
    if v: P['w_o2'] = v[:2]; P['w_s2'] = v[2]; P['w_v2'] = v[3]
    v = find('shader_environment_scroll', r'vec2\(\s*0\.0\s*,\s*' + num + r'\s*/\s*' + num + r'\s*\)', lambda m: float(m.group(1)) / float(m.group(2)))
    if v is not None: P['scroll_under'] = v
    v = find('shader_environment_metal', r'\(\s*' + num + r'\s*\*\s*cubeLuminance\s*\)', lambda m: float(m.group(1)))
    if v is not None: P['metal_k'] = v
    v = find('shader_environment_track', r'min\(\s*' + num + r'\s*,\s*sqrt', lambda m: float(m.group(1)))
    if v is not None: P['fog_max'] = v
    missing = [k for k in ('w_uv', 'w_o1', 'w_o2', 'scroll_under', 'metal_k', 'fog_max') if k not in P]
    if missing: log('Note: some shader constants were not found in the game scripts (%s); generic values are used.' % ', '.join(missing))
    return P

# ---------------------------------------------------------------- main conversion
def convert(ipa_path, out_dir=None, log=print, progress=lambda f, msg=None: None, cancel=lambda: False):
    t0 = time.time()
    ipa_path = os.path.abspath(ipa_path)
    if not os.path.isfile(ipa_path): raise ConvertError('File not found: %s' % ipa_path)
    ipa = IPA(ipa_path); info = ipa.validate()
    log('AG Drive %s found (%s).' % (info['version'], info['bundle_id']))
    if out_dir is None: out_dir = os.path.join(os.path.dirname(ipa_path), 'AGDrive_Explorer')
    out_dir = os.path.abspath(out_dir)
    if os.path.exists(out_dir) and os.listdir(out_dir):
        if not os.path.exists(os.path.join(out_dir, 'assets', 'tracks.json')) and not os.path.exists(os.path.join(out_dir, '.agdconv')):
            raise ConvertError('The output folder already contains other files: %s\nChoose an empty folder.' % out_dir)
        shutil.rmtree(out_dir)
    A = os.path.join(out_dir, 'assets')
    for d in ('tracks', 'textures', 'sky', 'anim'): os.makedirs(os.path.join(A, d), exist_ok=True)
    open(os.path.join(out_dir, '.agdconv'), 'w').write('generated by AGDriveConverter\n')
    progress(0.01, 'Reading scripts')

    # scripts
    ipk_name = 'script64.ipk' if ipa.has('script64.ipk') else 'script.ipk'
    lua = formats.parse_ipk(ipa.read(ipk_name))
    log('Read %d game scripts from %s.' % (len(lua), ipk_name))
    names = {}; desc = {}
    if ipa.has('localization.csv'):
        rows = list(csv.reader(io.StringIO(ipa.read('localization.csv').decode('latin1'))))
        hdr = rows[0] if rows else []; ci = hdr.index('en') if 'en' in hdr else 2
        for r in rows[1:]:
            if len(r) > ci: names[r[0]] = r[ci]; desc[r[0]] = r[1] if len(r) > 1 else ''
    tracks = []; skipped = []
    for fn in sorted(lua):
        m = re.match(r'^(track_\w+)\.luac?$', fn)
        if not m: continue
        tid = m.group(1)
        try: G = luac52.to_py(luac52.run_main(luac52.load(lua[fn])))
        except Exception as e: log('Could not read %s: %s' % (fn, e)); continue
        stg = G.get('track_static_geom_file')
        if not isinstance(stg, str): continue
        if not ipa.has(stg) or not ipa.has(tid + '.aga'):
            skipped.append(dict(id=tid, reason='The track script exists, but the IPA has no geometry (%s) or animation file for it.' % stg)); continue
        tracks.append(dict(id=tid, G=G))
    if not tracks: raise ConvertError('No tracks were found in the IPA.')
    # names / planets / time of day
    for t in tracks:
        G = t['G']; sk = (G.get('skybox_cross_file') or '').rsplit('.', 1)[0]
        t['sky_tex'] = sk; t['sky'] = re.sub(r'^track_|_skybox$', '', sk)
        gl = (G.get('track_glossy_reflection_cubemap_file') or '').rsplit('.', 1)[0]
        t['glossy_tex'] = gl; t['glossy'] = re.sub(r'^track_|_glossy$', '', gl)
        t['time'] = t['sky'].split('_')[-1].capitalize() if t['sky'] else ''
        md = re.search(r'Name of (\w+) track', desc.get(t['id'], ''))
        t['planet'] = md.group(1).capitalize() if md else None
        t['name'] = names.get(t['id'])
        t['extra'] = t['name'] is None
    fam_planet = {}
    for t in tracks:
        if t['planet']: fam_planet.setdefault(t['sky'].split('_')[0], t['planet'])
    for t in tracks:
        if not t['planet']: t['planet'] = fam_planet.get(t['sky'].split('_')[0], t['id'].split('_')[1].capitalize())
        if not t['name']:
            base = re.sub(r'^track_', '', t['id']).replace('_', ' ')
            t['name'] = base[:1].upper() + base[1:] + ' track'
    tracks.sort(key=lambda t: (t['extra'], t['id']))
    log('Tracks: ' + ', '.join(t['name'] for t in tracks))
    if skipped: log('Skipped (no geometry in the IPA): ' + ', '.join(s['id'] for s in skipped))

    gp = gltfpack_path()
    tex_cache = {}
    def get_tex(name):
        if name not in tex_cache:
            fn = name + '.tex'
            tex_cache[name] = texdec.read(ipa.read(fn)) if ipa.has(fn) else None
        return tex_cache[name]
    used_tex = {}
    tmp = tempfile.mkdtemp(prefix='agdconv_')
    out_tracks = []; skies = {}
    try:
        n = len(tracks)
        for ti, t in enumerate(tracks):
            if cancel(): raise ConvertError('Cancelled.')
            tid = t['id']; G = t['G']; base = 0.03 + 0.6 * ti / n
            progress(base, 'Converting %s (%d/%d)' % (t['name'], ti + 1, n)); log('[%d/%d] %s: geometry' % (ti + 1, n, t['name']))
            meshes = formats.parse_stg(ipa.read(G['track_static_geom_file']))
            raw, st = glb.build(meshes, 'tex')
            for k, v in st['textures'].items(): used_tex.setdefault(k, v)
            rp = os.path.join(tmp, tid + '.glb'); pp = os.path.join(tmp, tid + '_p.glb')
            open(rp, 'wb').write(raw); del raw
            flags = 0x08000000 if os.name == 'nt' else 0
            p = subprocess.run([gp, '-i', rp, '-o', pp, '-cc', '-km', '-kn', '-kv', '-ke', '-tr', '-vpf', '-vp', '16', '-vtf'],
                               capture_output=True, text=True, creationflags=flags)
            if p.returncode or not os.path.exists(pp): raise ConvertError('gltfpack failed for %s: %s' % (tid, p.stderr.strip()[-500:]))
            j, rest = glb.read_glb(open(pp, 'rb').read())
            for im in j.get('images', []):
                nm = os.path.splitext(os.path.basename(im['uri']))[0]; im['uri'] = '../textures/%s.webp' % nm; im['mimeType'] = 'image/webp'
            for tx in j.get('textures', []):
                src = tx.pop('source'); tx.setdefault('extensions', {})['EXT_texture_webp'] = {'source': src}
            for k in ('extensionsUsed', 'extensionsRequired'): j[k] = sorted(set(j.get(k, [])) | {'EXT_texture_webp'})
            j['asset']['extras'] = {'source': '%s from the user-supplied AG Drive %s IPA' % (G['track_static_geom_file'], VERSION),
                                    'note': 'Z-up converted to Y-up. COLOR_0 = baked lighting (rgb) + sun visibility (a); TEXCOORD_1.x = sky visibility; material name = shader mode|texture'}
            gpath = os.path.join(A, 'tracks', tid + '.glb'); open(gpath, 'wb').write(glb.write_glb(j, rest))
            os.remove(rp); os.remove(pp)
            log('    %d meshes, %d triangles, %.1f MB' % (st['meshes'], st['tris'], os.path.getsize(gpath) / 1e6))
            # animation + racing line
            progress(base + 0.3 / n, 'Animations for %s' % t['name'])
            recs = formats.parse_aga(ipa.read(tid + '.aga'))
            aj, abin, Py = export_anim(recs, st['anim_records'])
            json.dump(aj, open(os.path.join(A, 'anim', tid + '.json'), 'w'), separators=(',', ':'))
            open(os.path.join(A, 'anim', tid + '.bin'), 'wb').write(abin)
            log('    racing line %d points, %d animated objects' % (len(Py), len(aj['anims'])))
            # sun
            sun = cross_dir(G['sun_position_in_skybox']) if isinstance(G.get('sun_position_in_skybox'), dict) else np.array([0.3, 0.3, 0.9])
            sk = get_tex(t['sky_tex']) if t['sky_tex'] else None
            if sk and sk['kind'] == 'cube': sun = refine_sun(sk['faces'], sun)
            skies[t['sky']] = t['sky_tex']; skies.setdefault('__glossy__' + t['glossy'], t['glossy_tex'])
            start = Py[0] + np.array([0, 30, 0]); look = Py[min(20, len(Py) - 1)] + np.array([0, 30, 0])
            f = G.get('fog') or {}; gc = G.get('glossy_lighting_coefficients') or {}; lt = G.get('lighting') or {}
            def rgb(d, default=(1, 1, 1)):
                return [round(d.get('r', default[0]), 4), round(d.get('g', default[1]), 4), round(d.get('b', default[2]), 4)] if isinstance(d, dict) else list(default)
            out_tracks.append(dict(id=tid, name=t['name'], planet=t['planet'], time=t['time'], extra=t['extra'],
                label='%s, %s, %s' % (t['name'], t['planet'], t['time']), note='',
                glb='assets/tracks/%s.glb' % tid, glb_bytes=os.path.getsize(gpath), sky=t['sky'], glossy=t['glossy'],
                fog=dict(range=f.get('range', 30000), curve=f.get('back_curve', 1),
                         front=[round(f.get('r', 0.5), 4), round(f.get('g', 0.5), 4), round(f.get('b', 0.5), 4)],
                         back=[round(f.get('back_r', 0.5), 4), round(f.get('back_g', 0.5), 4), round(f.get('back_b', 0.5), 4)]),
                sun=dict(dir=[round(float(v), 4) for v in (sun[0], sun[2], -sun[1])], color=rgb(G.get('sun_color')), specular=rgb(G.get('specular_color'))),
                skylight=rgb(G.get('skylight_color'), (0.25, 0.25, 0.25)),
                ambient_up=[lt.get('hemispherical_ambient_up_' + c, 0) for c in 'rgb'], ambient_down=[lt.get('hemispherical_ambient_down_' + c, 0) for c in 'rgb'],
                intensity=(G.get('diffuse_lighting_coefficients') or {}).get('intensity', 1.5),
                glossy_coeffs=dict(ambient=gc.get('ambient', 0.25), sky=gc.get('sky_visibility', 0.5), sun=gc.get('sun_visibility', 1)),
                start=dict(pos=[round(float(v), 1) for v in start], look=[round(float(v), 1) for v in look]),
                anim='assets/anim/%s.json' % tid, anim_bin='assets/anim/%s.bin' % tid, anim_objects=len(aj['anims']),
                stats=dict(meshes=st['meshes'], verts=st['verts'], tris=st['tris'])))
        # textures
        names_t = sorted(used_tex)
        for i, tn in enumerate(names_t):
            if cancel(): raise ConvertError('Cancelled.')
            progress(0.65 + 0.2 * i / max(1, len(names_t)), 'Texture %s' % tn)
            tx = get_tex(tn)
            if tx is None:
                log('    texture %s.tex not in the IPA; using a grey placeholder' % tn); a = np.full((4, 4, 4), 128, np.uint8)
            else: a = tx['faces'][0]
            im = Image.fromarray(a, 'RGBA').transpose(Image.FLIP_TOP_BOTTOM)
            if a[:, :, 3].min() == 255: im = im.convert('RGB')
            if im.size[0] > 2048: im = im.resize((2048, 2048 * im.size[1] // im.size[0]), Image.LANCZOS)
            im.save(os.path.join(A, 'textures', tn + '.webp'), 'WEBP', quality=85, method=6, alpha_quality=90, exact=True)
            tex_cache.pop(tn, None)
        log('Wrote %d textures.' % len(names_t))
        # skies
        N = 1024; u = (np.arange(N) + 0.5) / N; U, Vv = np.meshgrid(u, u)
        keys = sorted(k for k in skies if not k.startswith('__glossy__'))
        for i, key in enumerate(keys):
            progress(0.86 + 0.1 * i / max(1, len(keys)), 'Sky %s' % key)
            tx = get_tex(skies[key])
            if tx is None or tx['kind'] != 'cube': raise ConvertError('Skybox %s.tex is missing or not a cubemap' % skies[key])
            Gf = [f[:, :, :3].astype(np.float32) for f in tx['faces']]
            for fi in range(6):
                s = cubeutil.face_uv_to_dir(fi, U, Vv); g = np.stack([-s[..., 0], -s[..., 2], s[..., 1]], -1)
                Image.fromarray(np.clip(cubeutil.sample(Gf, g), 0, 255).astype(np.uint8)).save(os.path.join(A, 'sky', '%s_%d.jpg' % (key, fi)), quality=88)
            del Gf; tex_cache.pop(skies[key], None)
        for k in sorted(k for k in skies if k.startswith('__glossy__')):
            key = k[len('__glossy__'):]; tx = get_tex(skies[k])
            if tx is None or tx['kind'] != 'cube': raise ConvertError('Reflection map %s.tex is missing or not a cubemap' % skies[k])
            for fi, f in enumerate(tx['faces']): Image.fromarray(f).save(os.path.join(A, 'sky', '%s_glossy_%d.png' % (key, fi)))
        log('Wrote %d skyboxes.' % len(keys))
        # shader constants, metadata, viewer files
        progress(0.97, 'Viewer files')
        json.dump(shader_params(lua, log), open(os.path.join(A, 'shader_params.json'), 'w'), indent=1)
        json.dump(dict(tracks=out_tracks, skipped=skipped), open(os.path.join(A, 'tracks.json'), 'w'), separators=(',', ':'))
        vt = os.path.join(resource_dir(), 'viewer_template')
        for root, dirs, files in os.walk(vt):
            rel = os.path.relpath(root, vt); dst = os.path.join(out_dir, rel) if rel != '.' else out_dir
            os.makedirs(dst, exist_ok=True)
            for fn in files:
                if fn == 'README.md': continue
                shutil.copy2(os.path.join(root, fn), os.path.join(dst, fn))
        for fn in ('start.sh', 'start.command', 'serve.py'):
            try: os.chmod(os.path.join(out_dir, fn), 0o755)
            except OSError: pass
        keyl = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=']
        rows = ['| Key | Track | Planet | Time | File |', '|---|---|---|---|---|']
        for i, t in enumerate(out_tracks):
            rows.append('| %s | %s | %s | %s | %s |' % (keyl[i] if i < len(keyl) else '', t['name'], t['planet'], t['time'], t['id']))
        if skipped: rows.append('\nNot included (no geometry in the IPA): ' + ', '.join(s['id'] for s in skipped) + '.')
        rd = open(os.path.join(vt, 'README.md'), encoding='utf-8').read().replace('{{TRACKS}}', '\n'.join(rows)).replace('{{DATE}}', datetime.date.today().isoformat())
        open(os.path.join(out_dir, 'README.md'), 'w', encoding='utf-8', newline='\n').write(rd)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    progress(1.0, 'Done')
    log('Finished in %.0f s: %s' % (time.time() - t0, out_dir))
    return out_dir, out_tracks
