import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { shared, makeMaterial, setShaderParams } from './shaders.js';

const $ = (id) => document.getElementById(id);
const showError = (msg) => { const e = $('error'); e.textContent = msg; e.classList.remove('hidden'); console.error(msg); };
window.addEventListener('error', (e) => showError('Error: ' + e.message));
window.addEventListener('unhandledrejection', (e) => showError('Error: ' + (e.reason && e.reason.message || e.reason)));

// ---------- renderer / scene ----------
const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, logarithmicDepthBuffer: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.LinearSRGBColorSpace; // the game writes raw values to the framebuffer
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, 1, 2, 250000);
camera.rotation.order = 'YXZ';
scene.add(camera);
// Scene lights carry each track's Lua sun / ambient values (the game's own lighting is baked into vertex colours;
// these lights only affect non-game materials, the custom shaders use the same values through uniforms).
const sunLight = new THREE.DirectionalLight(0xffffff, 1); scene.add(sunLight); scene.add(sunLight.target);
const hemi = new THREE.HemisphereLight(0x404040, 0x101010, 1); scene.add(hemi);

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize); resize();

const loader = new GLTFLoader();
loader.setMeshoptDecoder(MeshoptDecoder);
const cubeLoader = new THREE.CubeTextureLoader();
const skyCache = {}, glossyCache = {};
function loadCube(urls) {
  return new Promise((res, rej) => cubeLoader.load(urls, (t) => { t.colorSpace = THREE.NoColorSpace; t.generateMipmaps = true; t.minFilter = THREE.LinearMipmapLinearFilter; res(t); }, undefined, rej));
}
function getSky(key) { return skyCache[key] ??= loadCube([0,1,2,3,4,5].map(i => `assets/sky/${key}_${i}.jpg`)); }
function getGlossy(key) { return glossyCache[key] ??= loadCube([0,1,2,3,4,5].map(i => `assets/sky/${key}_glossy_${i}.png`)); }

// ---------- track list UI ----------
let DATA, TRACKS = [], cur = -1, root = null, loadToken = 0;
const keyLabels = ['1','2','3','4','5','6','7','8','9','0','-','='];
async function init() {
  const r = await fetch('assets/tracks.json');
  if (!r.ok) throw new Error('Could not load assets/tracks.json (' + r.status + '). Start the viewer with start.bat / start.command / start.sh.');
  DATA = await r.json(); TRACKS = DATA.tracks;
  try { const sp = await fetch('assets/shader_params.json'); if (sp.ok) setShaderParams(await sp.json()); } catch (e) { console.warn('shader_params.json not loaded'); }
  const list = $('tracklist'); let lastGroup = '';
  TRACKS.forEach((t, i) => {
    const group = t.extra ? 'Extra' : t.planet;
    if (group !== lastGroup) { const g = document.createElement('div'); g.className = 'group'; g.textContent = group === 'Extra' ? 'Extra' : group + ' tracks'; list.appendChild(g); lastGroup = group; }
    const b = document.createElement('button'); b.className = 'trk'; b.id = 'trk_' + t.id;
    b.title = t.label + (t.note ? ' (' + t.note + ')' : '');
    b.innerHTML = `<span><span class="k">${keyLabels[i] ?? ''}</span><span class="n"></span></span><span class="t ${t.time}">${t.planet} · ${t.time}</span>`;
    b.querySelector('.n').textContent = t.name;
    b.onclick = () => { selectTrack(i); b.blur(); };
    list.appendChild(b);
  });
  const hashIdx = TRACKS.findIndex(t => '#' + t.id === location.hash);
  await selectTrack(hashIdx >= 0 ? hashIdx : 0);
}

function setLoading(on, text, frac) {
  $('loading').classList.toggle('hidden', !on);
  if (text) $('loadtext').textContent = text;
  if (frac != null) $('loadbar').style.width = Math.round(frac * 100) + '%';
}

function disposeRoot() {
  if (!root) return;
  scene.remove(root);
  root.traverse(o => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) { if (o.material.uniforms?.map?.value) o.material.uniforms.map.value.dispose(); o.material.dispose(); }
  });
  root = null;
}

async function selectTrack(i) {
  i = (i + TRACKS.length) % TRACKS.length;
  const t = TRACKS[i]; const token = ++loadToken;
  document.querySelectorAll('.trk').forEach(b => b.classList.toggle('active', b.id === 'trk_' + t.id));
  history.replaceState(null, '', '#' + t.id);
  setLoading(true, `Loading ${t.name} (${t.planet}, ${t.time})…`, 0);
  window.__trackReady = false;
  const [gltf, sky, glossy, animJson, animBin] = await Promise.all([
    new Promise((res, rej) => loader.load(t.glb, res, (e) => {
      if (token === loadToken) setLoading(true, `Loading ${t.name}: ${(e.loaded / 1e6).toFixed(1)} / ${(t.glb_bytes / 1e6).toFixed(1)} MB`, Math.min(1, e.loaded / t.glb_bytes) * 0.9);
    }, rej)),
    getSky(t.sky), getGlossy(t.glossy),
    fetch(t.anim).then(r => { if (!r.ok) throw new Error('Could not load ' + t.anim); return r.json(); }),
    fetch(t.anim_bin).then(r => { if (!r.ok) throw new Error('Could not load ' + t.anim_bin); return r.arrayBuffer(); })]);
  if (token !== loadToken) { gltf.scene.traverse(o => { o.geometry?.dispose(); }); return; }
  setLoading(true, `Preparing ${t.name}…`, 0.95);
  disposeRoot();
  cur = i;
  root = gltf.scene;
  const matCache = new Map();
  setupRide(animJson);
  setupAnimations(animJson, animBin);
  root.traverse(o => {
    if (!o.isMesh) return;
    const g = o.geometry;
    if (g.attributes.color) { g.setAttribute('aColor', g.attributes.color); g.deleteAttribute('color'); }
    if (g.attributes.uv1) { g.setAttribute('aSky', g.attributes.uv1); g.deleteAttribute('uv1'); }
    const src = o.material; const [mode, texName] = (src.name || 'env|').split('|');
    const map = src.map; if (map) { map.colorSpace = THREE.NoColorSpace; map.anisotropy = 8; map.needsUpdate = true; }
    const key = src.name + (g.attributes.normal ? '+n' : '');
    let m = matCache.get(key);
    if (!m) { m = makeMaterial(mode, map, !!g.attributes.normal); matCache.set(key, m); }
    o.userData.srcMaterial = src.name; o.material = m; o.frustumCulled = true;
    if (mode === 'scroll_air') o.renderOrder = 2; else if (mode === 'additive') o.renderOrder = 3;
    const am = /^anim_(\d+)_/.exec(o.name || '');
    if (am && animByRec.has(+am[1])) animObjs.push({ obj: o, a: animByRec.get(+am[1]), last: 0 });
  });
  scrollMats = [...matCache.values()].filter(m => SCROLL[m.name]);
  scene.add(root);
  applyEnvironment(t, sky, glossy);
  resetCamera();
  const info = `<b>${t.label}</b>${t.note ? '<br><i>' + t.note + '</i>' : ''}<br>` +
    `Fog range ${t.fog.range}, curve ${t.fog.curve} · diffuse ×${t.intensity}<br>` +
    `${(t.stats.tris / 1000).toFixed(0)}k triangles · ${(t.glb_bytes / 1e6).toFixed(1)} MB · ${animObjs.length} animated objects`;
  $('trackinfo').innerHTML = info;
  renderer.compile(scene, camera);
  setLoading(false);
  window.__trackReady = t.id;
}

function applyEnvironment(t, sky, glossy) {
  scene.background = sky;
  shared.skyCube.value = sky;
  shared.glossy.value = glossy;
  shared.intensity.value = t.intensity;
  shared.gCoeff.value.set(t.glossy_coeffs.ambient, t.glossy_coeffs.sky, t.glossy_coeffs.sun);
  shared.sunDir.value.fromArray(t.sun.dir).normalize();
  shared.sunColor.value.fromArray(t.sun.color);
  shared.fogFront.value.fromArray(t.fog.front);
  shared.fogBack.value.fromArray(t.fog.back);
  shared.fogRange.value = t.fog.range;
  shared.fogCurve.value = t.fog.curve;
  sunLight.color.fromArray(t.sun.color); sunLight.position.fromArray(t.sun.dir).multiplyScalar(10000);
  hemi.color.fromArray(t.skylight); hemi.groundColor.fromArray(t.ambient_down);
}

// ---------- fly controls ----------
const keys = new Set();
let yaw = 0, pitch = 0, follow = false, followS = 0;
const speedEl = $('speed');
const SPEED_MIN = 10, SPEED_MAX = 30000;
const sliderToSpeed = (v) => SPEED_MIN * Math.pow(SPEED_MAX / SPEED_MIN, v / 1000);
const speedToSlider = (s) => 1000 * Math.log(s / SPEED_MIN) / Math.log(SPEED_MAX / SPEED_MIN);
let speed = 800;
function setSpeed(s) { speed = Math.min(SPEED_MAX, Math.max(SPEED_MIN, s)); speedEl.value = speedToSlider(speed); $('speedval').textContent = Math.round(speed) + ' u/s'; }
speedEl.addEventListener('input', () => setSpeed(sliderToSpeed(+speedEl.value)));
setSpeed(speed);
$('exposure').addEventListener('input', (e) => { shared.exposure.value = e.target.value / 100; $('expval').textContent = e.target.value + '%'; });
$('expval').textContent = '100%';
$('fogOn').addEventListener('change', (e) => { shared.fogOn.value = e.target.checked ? 1 : 0; });
$('follow').addEventListener('change', (e) => setFollow(e.target.checked));
$('resetBtn').onclick = (e) => { resetCamera(); e.target.blur(); };
$('helpBtn').onclick = (e) => { $('help').classList.toggle('hidden'); e.target.blur(); };
$('helpClose').onclick = () => $('help').classList.add('hidden');

function lookAt(target) {
  const d = new THREE.Vector3().subVectors(target, camera.position).normalize();
  yaw = Math.atan2(-d.x, -d.z); pitch = Math.asin(THREE.MathUtils.clamp(d.y, -1, 1));
}
function setAnim(on) { animOn = on; $('animOn').checked = on; }
$('animOn').addEventListener('change', (e) => setAnim(e.target.checked));
function resetCamera() {
  const t = TRACKS[cur]; if (!t) return;
  if (follow) setFollow(false);
  camera.position.fromArray(t.start.pos); lookAt(new THREE.Vector3().fromArray(t.start.look));
  followS = 0;
}
// ---------- racing-line ride ----------
// The PathFinder record of each track's .aga file is the game's racing line: one full matrix every 10 units
// (row 1 = forward, row 2 = track up, so it carries banking and the upside-down sections). anim.py exports every
// 2nd frame (position + up). Here it becomes a closed centripetal Catmull-Rom spline that is sampled by arc length,
// so the ride moves at exactly the slider speed and the camera orientation is slerp-damped.
let ride = null;
const RIDE_HEIGHT = 14;
function setupRide(aj) {
  const a = aj.path, n = a.length / 6, pts = [], ups = [];
  for (let i = 0; i < n; i++) { pts.push(new THREE.Vector3(a[i * 6], a[i * 6 + 1], a[i * 6 + 2])); ups.push(new THREE.Vector3(a[i * 6 + 3], a[i * 6 + 4], a[i * 6 + 5]).normalize()); }
  // smooth the up vectors a little (window of +-3 points = +-60 units) so the roll never twitches
  const sm = ups.map((u, i) => { const v = new THREE.Vector3(); for (let k = -3; k <= 3; k++) v.add(ups[(i + k + n) % n]); return v.normalize(); });
  const curve = new THREE.CatmullRomCurve3(pts, true, 'centripetal');
  curve.arcLengthDivisions = n * 4;
  const length = curve.getLength();
  ride = { curve, pts, ups: sm, n, length };
}
const rp = new THREE.Vector3(), rq = new THREE.Vector3(), ru = new THREE.Vector3(), ru2 = new THREE.Vector3(), rf = new THREE.Vector3(), rr = new THREE.Vector3();
const rm = new THREE.Matrix4(), rTargetQ = new THREE.Quaternion(), rOffQ = new THREE.Quaternion(), rEuler = new THREE.Euler(0, 0, 0, 'YXZ');
let rideYaw = 0, ridePitch = 0;
function rideSample(s, pos, up) {
  const L = ride.length; let u = (s % L) / L; if (u < 0) u += 1;
  ride.curve.getPointAt(u, pos);
  const t = ride.curve.getUtoTmapping(u) * ride.n, i = Math.floor(t) % ride.n, f = t - Math.floor(t);
  up.copy(ride.ups[i]).lerp(ride.ups[(i + 1) % ride.n], f).normalize();
}
function rideOrientation(s, look, outPos, outQ) {
  rideSample(s, rp, ru);
  rideSample(s + look, rq, ru2);
  outPos.copy(rp).addScaledVector(ru, RIDE_HEIGHT);
  rq.addScaledVector(ru2, RIDE_HEIGHT);
  rf.subVectors(rq, outPos).normalize();
  ru.add(ru2).normalize();                       // up halfway between here and the look-ahead point
  rr.crossVectors(rf, ru).normalize(); ru.crossVectors(rr, rf).normalize();
  rm.makeBasis(rr, ru, rf.negate());
  outQ.setFromRotationMatrix(rm);
}
function setFollow(on) {
  if (on && !ride) return;
  follow = on; $('follow').checked = on;
  if (on) { followS = nearestPathS(); rideYaw = ridePitch = 0; }
  else {   // leave the ride looking the same way (roll is dropped)
    camera.getWorldDirection(fwd); lookAt(tmpA.copy(camera.position).add(fwd));
  }
}
function nearestPathS() {
  if (!ride) return 0;
  const p = ride.pts; let best = 0, bd = Infinity;
  for (let i = 0; i < p.length; i++) { const d = p[i].distanceToSquared(camera.position); if (d < bd) { bd = d; best = i; } }
  return best / ride.n * ride.length;
}

// ---------- animated world objects (.aga) and scrolling shaders ----------
// d#(NNN) meshes are baked at frame 0 of .aga record NNN; anim.py exported the node transform inv(M0)*M(t)
// as reduced keyframes [frame, tx,ty,tz, qx,qy,qz,qw, scale] at 30 fps.
let animByRec = new Map(), animObjs = [], scrollMats = [], animOn = true, animTime = 0;
function setupAnimations(aj, bin) {
  animByRec = new Map(); animObjs = [];
  for (const a of aj.anims) animByRec.set(a.rec, { frames: a.frames, n: a.keys, k: new Float32Array(bin, a.offset, a.keys * 9), name: a.name });
}
const aq0 = new THREE.Quaternion(), aq1 = new THREE.Quaternion();
function updateAnimations(t) {
  const fr = t * 30;
  for (const ao of animObjs) {
    const { k, n, frames } = ao.a, o = ao.obj;
    if (!animOn) { o.position.set(0, 0, 0); o.quaternion.identity(); o.scale.setScalar(1); continue; }
    const f = fr % frames;
    let i = ao.last; if (i >= n - 1 || k[i * 9] > f) i = 0;
    while (i < n - 2 && k[(i + 1) * 9] <= f) i++;
    ao.last = i;
    const j = Math.min(i + 1, n - 1), f0 = k[i * 9], f1 = k[j * 9], w = f1 > f0 ? Math.min(1, Math.max(0, (f - f0) / (f1 - f0))) : 0;
    const a = i * 9, b = j * 9;
    o.position.set(k[a + 1] + (k[b + 1] - k[a + 1]) * w, k[a + 2] + (k[b + 2] - k[a + 2]) * w, k[a + 3] + (k[b + 3] - k[a + 3]) * w);
    aq0.set(k[a + 4], k[a + 5], k[a + 6], k[a + 7]); aq1.set(k[b + 4], k[b + 5], k[b + 6], k[b + 7]);
    o.quaternion.slerpQuaternions(aq0, aq1, w);
    o.scale.setScalar(k[a + 8] + (k[b + 8] - k[a + 8]) * w);
  }
  // UV scroll rates are set by the engine at run time and are not in the game data: these are hand-picked
  for (const m of scrollMats) SCROLL[m.name](m.uniforms.uScroll.value, animOn ? t : 0);
}
const SCROLL = {
  scroll:     (v, t) => v.set(-(t * 0.05 % 1), 0),        // 1# ground traffic lanes (strip runs along u)
  scroll_air: (v, t) => v.set(-(t * 0.08 % 1), 0),        // 2# flying traffic lanes
  ads_cycle:  (v, t) => v.set(Math.floor(t / 6) * 0.25 % 1, 0),  // a# ad screens: next ad of the atlas row every 6 s
};

canvas.addEventListener('click', () => { if (document.pointerLockElement !== canvas) canvas.requestPointerLock?.(); });
document.addEventListener('pointerlockchange', () => { $('clickhint').classList.toggle('hidden', document.pointerLockElement === canvas); });
let dragging = false, lastX = 0, lastY = 0;
canvas.addEventListener('mousedown', (e) => { dragging = true; lastX = e.clientX; lastY = e.clientY; });
window.addEventListener('mouseup', () => dragging = false);
window.addEventListener('mousemove', (e) => {
  let dx = 0, dy = 0;
  if (document.pointerLockElement === canvas) { dx = e.movementX; dy = e.movementY; }
  else if (dragging) { dx = e.clientX - lastX; dy = e.clientY - lastY; lastX = e.clientX; lastY = e.clientY; }
  else return;
  if (follow) { rideYaw = THREE.MathUtils.clamp(rideYaw - dx * 0.0022, -2.5, 2.5); ridePitch = THREE.MathUtils.clamp(ridePitch - dy * 0.0022, -1.2, 1.2); return; }
  yaw -= dx * 0.0022; pitch -= dy * 0.0022; pitch = Math.max(-1.55, Math.min(1.55, pitch));
});
canvas.addEventListener('wheel', (e) => { e.preventDefault(); setSpeed(speed * Math.pow(1.15, -Math.sign(e.deltaY))); }, { passive: false });
window.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' && e.target.type === 'range') e.target.blur();
  keys.add(e.code);
  if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown'].includes(e.code)) e.preventDefault();
  if (e.repeat) return;
  if (e.code === 'KeyR') resetCamera();
  else if (e.code === 'KeyH') $('help').classList.toggle('hidden');
  else if (e.code === 'KeyF') setFollow(!follow);
  else if (e.code === 'KeyV') { rideYaw = ridePitch = 0; }
  else if (e.code === 'KeyN') setAnim(!animOn);
  else if (e.code === 'KeyG') { const c = $('fogOn'); c.checked = !c.checked; shared.fogOn.value = c.checked ? 1 : 0; }
  else if (e.code === 'BracketRight' || e.code === 'PageDown') selectTrack(cur + 1);
  else if (e.code === 'BracketLeft' || e.code === 'PageUp') selectTrack(cur - 1);
  else {
    const map = { Digit1: 0, Digit2: 1, Digit3: 2, Digit4: 3, Digit5: 4, Digit6: 5, Digit7: 6, Digit8: 7, Digit9: 8, Digit0: 9, Minus: 10, Equal: 11 };
    if (e.code in map && map[e.code] < TRACKS.length) selectTrack(map[e.code]);
  }
});
window.addEventListener('keyup', (e) => keys.delete(e.code));
window.addEventListener('blur', () => keys.clear());

const fwd = new THREE.Vector3(), right = new THREE.Vector3(), move = new THREE.Vector3(), tmpA = new THREE.Vector3(), tmpB = new THREE.Vector3();
const clock = new THREE.Clock();
function tick() {
  const dt = Math.min(clock.getDelta(), 0.1);
  shared.time.value += dt;
  const boost = (keys.has('ShiftLeft') || keys.has('ShiftRight')) ? 5 : 1;
  if (animOn) animTime += dt;
  updateAnimations(animTime);
  if (follow && ride) {
    followS += speed * boost * dt;
    const look = THREE.MathUtils.clamp(speed * 0.3, 60, 400);
    rideOrientation(followS, look, camera.position, rTargetQ);
    rEuler.set(ridePitch, rideYaw, 0); rOffQ.setFromEuler(rEuler); rTargetQ.multiply(rOffQ);
    camera.quaternion.slerp(rTargetQ, 1 - Math.exp(-dt * 5));
  } else {
    camera.rotation.set(pitch, yaw, 0);
    camera.getWorldDirection(fwd); right.crossVectors(fwd, camera.up).normalize();
    move.set(0, 0, 0);
    if (keys.has('KeyW') || keys.has('ArrowUp')) move.add(fwd);
    if (keys.has('KeyS') || keys.has('ArrowDown')) move.sub(fwd);
    if (keys.has('KeyD') || keys.has('ArrowRight')) move.add(right);
    if (keys.has('KeyA') || keys.has('ArrowLeft')) move.sub(right);
    if (keys.has('Space') || keys.has('KeyE')) move.y += 1;
    if (keys.has('KeyC') || keys.has('KeyQ')) move.y -= 1;
    if (move.lengthSq() > 0) camera.position.addScaledVector(move.normalize(), speed * boost * dt);
  }
  const p = camera.position;
  $('hudpos').textContent = `x ${p.x.toFixed(0)}  y ${p.y.toFixed(0)}  z ${p.z.toFixed(0)}   (game: ${p.x.toFixed(0)}, ${(-p.z).toFixed(0)}, ${p.y.toFixed(0)})  ${follow ? `RIDING ${(followS % ride.length / 1000).toFixed(1)} / ${(ride.length / 1000).toFixed(1)}k  roll ${rollDeg().toFixed(0)}°` : ''}`;
  renderer.render(scene, camera);
  requestAnimationFrame(tick);
}
function rollDeg() { rideSample(followS, rp, ru); return THREE.MathUtils.radToDeg(Math.acos(THREE.MathUtils.clamp(ru.y, -1, 1))); }
// test hook for automated screenshots
window.__viewer = { rideAt: (s, spd = 10) => { setSpeed(spd); setFollow(true); followS = s; rideOrientation(s, THREE.MathUtils.clamp(spd * 0.3, 60, 400), camera.position, camera.quaternion); }, stopRide: () => setFollow(false),
  rideInfo: () => ride && { length: ride.length, s: followS, roll: rollDeg() }, setAnimTime: (t) => { animTime = t; }, animCount: () => animObjs.length, nearestS: () => nearestPathS(), selectTrack: (id) => selectTrack(TRACKS.findIndex(t => t.id === id)), setView: (pos, look) => { if (follow) setFollow(false); camera.position.fromArray(pos); lookAt(new THREE.Vector3().fromArray(look)); }, tracks: () => TRACKS.map(t => t.id), renderer, scene, camera };
init().catch(e => showError(e.message || String(e)));
tick();
