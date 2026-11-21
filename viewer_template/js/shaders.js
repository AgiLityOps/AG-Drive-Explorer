// Re-implementation of AG Drive's IonCore environment shaders (from the game's shader_*.lua scripts).
// Lighting in AG Drive is baked: COLOR_0.rgb = baked diffuse light, COLOR_0.a = sun visibility,
// TEXCOORD_1.x = sky visibility. Texture alpha is a reflection/emissive mask, NOT transparency.
import * as THREE from 'three';

export const shared = {
  glossy:     { value: null },               // per-track glossy reflection cubemap (game face order)
  skyCube:    { value: null },               // per-track skybox (three.js background convention)
  intensity:  { value: 1.5 },                // diffuse_lighting_coefficients.intensity
  gCoeff:     { value: new THREE.Vector3(0.25, 0.5, 1) }, // glossy_lighting_coefficients ambient, sky_visibility, sun_visibility
  sunDir:     { value: new THREE.Vector3(0, 1, 0) },
  sunColor:   { value: new THREE.Color(1, 1, 1) },
  fogFront:   { value: new THREE.Color(0.5, 0.6, 0.7) },
  fogBack:    { value: new THREE.Color(0.5, 0.6, 0.7) },
  fogRange:   { value: 30000 },
  fogCurve:   { value: 1 },
  fogOn:      { value: 1 },
  exposure:   { value: 1 },
  time:       { value: 0 },
};

// Shader constants are read from the game's own shader scripts by the converter (assets/shader_params.json).
// The defaults below are generic stand-ins used only if a value could not be found.
const P = { scroll_under: 0.03, metal_k: 4, w_uv: 0.01, w_o1: [0, 0], w_s1: 0.1, w_v1: 0.03, w_o2: [0.5, 0.5], w_s2: 0.5, w_v2: 0.02, fog_max: 0.99 };
export function setShaderParams(p) { Object.assign(P, p || {}); }
const f = (x) => { const v = Number(x); return Number.isInteger(v) ? v.toFixed(1) : String(v); };
function paramDefines() {
  return { P_SCROLL_UNDER: f(P.scroll_under), P_METAL_K: f(P.metal_k), P_W_UV: f(P.w_uv), P_W_S1: f(P.w_s1), P_W_V1: f(P.w_v1),
    P_W_S2: f(P.w_s2), P_W_V2: f(P.w_v2), P_FOG_MAX: f(P.fog_max),
    P_W_O1: `vec2(${f(P.w_o1[0])}, ${f(P.w_o1[1])})`, P_W_O2: `vec2(${f(P.w_o2[0])}, ${f(P.w_o2[1])})` };
}

const MODES = { env: 0, track: 0, grate: 0, emissive: 1, scroll: 2, metal: 3, selflit: 4, neon: 4, ads_cycle: 4, scroll_air: 5, additive: 6, water: 7 };

const vert = /* glsl */`
#include <common>
#include <logdepthbuf_pars_vertex>
attribute vec4 aColor;
attribute vec2 aSky;
uniform vec2 uScroll;   // per-material UV scroll offset (game: ScrollOffset of the scroll / scroll_air / texture_scroll shaders)
varying vec2 vUv;
varying vec4 vCol;
varying float vSky;
varying vec3 vWorldPos;
varying vec3 vNormalW;
void main() {
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorldPos = wp.xyz;
  #ifdef HAS_NORMAL
  vNormalW = normalize(mat3(modelMatrix) * normal);
  vCol = aColor;
  vSky = aSky.x;
  #else
  vNormalW = vec3(0.0, 1.0, 0.0);
  vCol = vec4(1.0);
  vSky = 0.0;
  #endif
  vUv = uv + uScroll;
  #if MODE == 2
  // shader_environment_scroll: the top side shows the scrolling traffic strip, the underside shows the strip
  // 64 texels further on in the atlas, unscrolled (v offset is negative because the UVs were flipped to top-down)
  if (dot(wp.xyz - cameraPosition, vNormalW) >= 0.0) vUv = uv + vec2(0.0, -P_SCROLL_UNDER);
  #endif
  gl_Position = projectionMatrix * viewMatrix * wp;
  #include <logdepthbuf_vertex>
}`;

const frag = /* glsl */`
#include <common>
#include <logdepthbuf_pars_fragment>
uniform sampler2D map;
uniform samplerCube glossy;
uniform samplerCube skyCube;
uniform float intensity;
uniform vec3 gCoeff;
uniform vec3 sunDir;
uniform vec3 sunColor;
uniform vec3 fogFront;
uniform vec3 fogBack;
uniform float fogRange;
uniform float fogCurve;
uniform float fogOn;
uniform float exposure;
uniform float time;
varying vec2 vUv;
varying vec4 vCol;
varying float vSky;
varying vec3 vWorldPos;
varying vec3 vNormalW;
// three.js Y-up world -> game Z-up world (game cubemaps are sampled with game-space directions)
vec3 toGame(vec3 d) { return vec3(d.x, -d.z, d.y); }
void main() {
  #include <logdepthbuf_fragment>
  vec3 V = vWorldPos - cameraPosition;
  float dist = length(V);
  vec3 N = normalize(vNormalW);
  if (!gl_FrontFacing) N = -N;
  vec3 R = reflect(V, N);
  vec4 tex = texture2D(map, vUv);
  vec3 diff = intensity * vCol.rgb;
  float dw = gCoeff.x + gCoeff.y * vSky + gCoeff.z * vCol.a;   // v_Diffuse.w
  float alpha = 1.0;
  vec3 color;
#if MODE == 0      // shader_environment / _track / _grate
  vec4 cube = textureCube(glossy, toGame(R));
  color = diff * tex.rgb + dw * tex.a * cube.rgb;
#elif MODE == 1    // shader_environment_emissive
  vec4 cube = textureCube(glossy, toGame(R));
  color = tex.a * tex.rgb + diff * tex.rgb + dw * tex.g * cube.rgb;
#elif MODE == 2    // shader_environment_scroll (traffic lanes)
  vec4 cube = textureCube(glossy, toGame(R));
  color = diff * tex.rgb + dw * tex.g * cube.rgb;
#elif MODE == 3    // shader_environment_metal
  vec4 cube = textureCube(glossy, toGame(R));
  color = tex.a * tex.rgb + P_METAL_K * cube.a * diff * tex.rgb;
#elif MODE == 4    // shader_selflit (ad screens, neon)
  color = tex.rgb;
#elif MODE == 5    // shader_environment_scroll_air (flying traffic, alpha blended)
  color = tex.rgb; alpha = tex.a;
#elif MODE == 6    // light flares, additive
  color = tex.rgb;
#elif MODE == 7    // shader_water: two scrolling normal-map samples, fresnel-weighted sky + glossy reflection
  vec3 g = toGame(vWorldPos);
  vec2 uv = P_W_UV * g.xy;
  vec2 t1 = P_W_O1 + uv * P_W_S1 - vec2(time) * P_W_V1 * 0.05;
  vec2 t2 = P_W_O2 + uv.yx * P_W_S2 + vec2(time) * P_W_V2 * 0.05;
  // the game samples the bottom-up GL texture; our images are stored upright, so flip t to sample the same texels
  vec3 nrm = texture2D(map, vec2(t1.x, 1.0 - t1.y)).xyz + texture2D(map, vec2(t2.x, 1.0 - t2.y)).xyz - 1.0;
  vec3 eye = normalize(-toGame(V));
  float f = 1.0 - dot(nrm, eye); f = f * f;
  vec3 Rg = reflect(toGame(V), vec3(0.0, 0.0, 1.0));
  vec3 Rt = vec3(Rg.x, Rg.z, -Rg.y);
  color = (f * f + 0.05) * (textureCube(glossy, Rg).rgb + textureCube(skyCube, vec3(-Rt.x, Rt.y, Rt.z)).rgb);
#endif
  if (fogOn > 0.5) {
    // track shader: t = min(0.99, sqrt(dist*density)); colour blends from back colour to front (sun-side) colour
    float t = min(P_FOG_MAX, sqrt(dist / fogRange));
    float s = pow(clamp(0.5 + 0.5 * dot(normalize(V), sunDir), 0.0, 1.0), fogCurve);
    vec3 fc = mix(fogBack, fogFront, s);
  #if MODE == 6
    color *= (1.0 - t);
  #else
    color = mix(color, fc, t);
  #endif
  }
  gl_FragColor = vec4(color * exposure, alpha);
}`;

export function makeMaterial(mode, map, hasNormal) {
  const m = MODES[mode] ?? 0;
  const mat = new THREE.ShaderMaterial({
    name: mode,
    uniforms: { ...shared, map: { value: map }, uScroll: { value: new THREE.Vector2() } },
    vertexShader: vert,
    fragmentShader: frag,
    defines: { MODE: m, ...paramDefines(), ...(hasNormal ? { HAS_NORMAL: 1 } : {}) },
    side: (mode === 'grate' || mode === 'selflit' || mode === 'ads_cycle' || mode === 'neon' || mode === 'additive' || mode === 'scroll_air') ? THREE.DoubleSide : THREE.FrontSide,
  });
  if (m === 5) { mat.transparent = true; mat.depthWrite = false; }
  if (m === 6) { mat.transparent = true; mat.depthWrite = false; mat.blending = THREE.AdditiveBlending; }
  return mat;
}
