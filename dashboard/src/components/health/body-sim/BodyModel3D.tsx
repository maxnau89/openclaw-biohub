/**
 * BodyModel3D — React component that renders a deformable 3D body for the
 * Body Composition tab. Loads `male-base.glb` or `female-base.glb` from
 * `/body-sim/`, applies caliper-driven deformation via `MeshDeformer`, and
 * optionally renders a second side-by-side body for current-vs-projected
 * comparison.
 *
 * Three.js is loaded via dynamic import so it stays out of the initial JS
 * bundle. Only users who open the Body Comp tab pay the ~150 KB gzipped
 * Three.js cost; everyone else's first paint is unaffected.
 *
 * WebGL fallback: when no WebGL context is available, we render a small
 * div with the textual girths instead of attempting the canvas.
 */
'use client';

import { useEffect, useRef } from 'react';
import type * as THREE from 'three';

import type { Sex, Skinfolds } from './anthropometrics';

export interface BodyModel3DProps {
  weightKg: number;
  bfPct: number;
  heightM: number;
  sex: Sex;
  /** Optional 7-site caliper. When present, drives regional fat shape. */
  skinfolds?: Skinfolds;
  /** When set, render a second body next to the current for comparison. */
  compareWith?: {
    weightKg: number;
    bfPct: number;
    skinfolds?: Skinfolds;
  };
  /** Canvas height in px. Width fills the container. */
  height?: number;
}

// Slightly warmer than the previous 0xe2c4a0 — adds red/orange under-tone
// so the silhouette reads as living tissue, not a chalk maquette.
const SKIN_COLOR = 0xeac4a4;
const GOAL_COLOR = 0x86d6a8;
// Subtle warm emissive — fakes subsurface scattering "glow" without the
// shader cost. ~6 % of full intensity, in a warm rose tone.
const SKIN_EMISSIVE = 0x2a0c08;
const GOAL_EMISSIVE = 0x0c2a18;

// ─── MakeHuman macro grid: bilinear composition + physiological anchors ─────
//
// The baked GLBs are at the canonical "average muscle, average weight" point
// of MakeHuman's macro grid and carry all 8 non-center grid points as morph
// targets: the 4 axis extremes (muscle_high/low, weight_high/low) AND the 4
// corners (muscle_high_weight_high, …). The corners matter: MakeHuman
// composes macros by bilinear interpolation over the grid, and a corner
// shape is NOT the sum of its two axis extremes (measured error: 60–138 %
// of the deformation magnitude — the source of the surface rippling we saw
// when muscle_high + weight_high were simply added for strongly-modified
// bodies).
//
// Runtime composition mirrors MakeHuman exactly: normalize the user's FFMI
// to a muscle coordinate m ∈ [−1, 1] and BF % to a weight coordinate
// w ∈ [−1, 1], build per-axis hat weights, and weight each grid morph with
// the product of its axis hats. The hat products always sum to ≤ 1 per
// morph, so no morph ever extrapolates beyond its baked shape — full
// differentiation across the grid without caps.
//
// Anchors map measured inputs onto the grid so the mannequin stays true to
// the data ([min → −1, avg → 0, max → +1], piecewise linear, clamped):
//   - Male FFMI  16 / 20 / 25 — untrained-low, population average, natural
//     bodybuilder ceiling (FFMI ≈ 25, Kouri et al. 1995).
//   - Female FFMI 13 / 16.5 / 21 — same landmarks for women.
//   - Male BF %   5 / 15 / 32 — contest-lean, average-fit, obese class I
//     (≈ what MakeHuman's maxweight shape depicts).
//   - Female BF % 12 / 22 / 38 — essential-fat floor, average, obese.
const MUSCLE_ANCHORS: Record<Sex, [number, number, number]> = {
  m: [16, 20, 25],
  f: [13, 16.5, 21],
};
const BF_ANCHORS: Record<Sex, [number, number, number]> = {
  m: [5, 15, 32],
  f: [12, 22, 38],
};

// Belly-overhang threshold: real anterior abdominal mass kicks in around
// 22 % BF for men, 30 % BF for women. Ramped over 15 BF points; capped at
// 1.3 — mild extrapolation of the (smooth, localized) stomach target is
// safe, and the weight axis now carries most of the mass gain anyway.
const BELLY_THRESHOLD: Record<Sex, number> = { m: 22, f: 30 };
const BELLY_RANGE = 15;
const BELLY_CAP = 1.3;

// Visible-muscularity gate. FFMI is mechanically inflated at high fat mass
// (extra blood volume, organ + connective-tissue scaling, non-contractile
// lean mass), so a morbidly-obese person reads as high-FFMI without any
// shredded-delt look. We attenuate ONLY the muscle_high (positive) side by a
// leanness factor: full definition when lean, fading to average muscle tone
// as BF approaches the obese range — the weight axis then carries the mass so
// the body reads as fat, not Hulk. The muscle_low side is untouched (a soft,
// untrained body stays soft regardless of fat). MUSCLE_VIS_BF is the BF % at
// which gross muscularity is fully hidden; ramped over MUSCLE_VIS_RANGE below
// it. Tuned so a 22 %-BF strongman keeps full muscle while a 42 %-BF obese
// body drops to average tone.
const MUSCLE_VIS_BF: Record<Sex, number> = { m: 40, f: 45 };
const MUSCLE_VIS_RANGE = 15;

function clamp(x: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, x));
}

/** Piecewise-linear map of a measurement onto a grid axis coordinate:
 *  lo → −1, mid → 0, hi → +1, clamped to [−1, 1]. */
function axisCoord(x: number, [lo, mid, hi]: [number, number, number]): number {
  if (x >= mid) return clamp((x - mid) / (hi - mid), 0, 1);
  return -clamp((mid - x) / (mid - lo), 0, 1);
}

function computeMorphInfluences(
  weightKg: number, bfPct: number, heightM: number, sex: Sex,
): Record<string, number> {
  const LBM = weightKg * (1 - bfPct / 100);
  const ffmi = LBM / (heightM * heightM);
  const rawM = axisCoord(ffmi, MUSCLE_ANCHORS[sex]);
  const w = axisCoord(bfPct, BF_ANCHORS[sex]);
  // Attenuate visible muscularity by leanness — only the positive side, so
  // fat is carried by the weight axis instead of reading as huge shoulders.
  const muscleVis = clamp((MUSCLE_VIS_BF[sex] - bfPct) / MUSCLE_VIS_RANGE, 0, 1);
  const m = rawM > 0 ? rawM * muscleVis : rawM;

  // Per-axis hat weights over {min, avg, max}. At m = +0.6 the muscle axis
  // is 60 % max / 40 % avg; the avg column needs no morph (it's the base
  // mesh), so only the max/min hats appear below.
  const mHi = Math.max(0, m);
  const mLo = Math.max(0, -m);
  const wHi = Math.max(0, w);
  const wLo = Math.max(0, -w);
  const mAvg = 1 - Math.abs(m);
  const wAvg = 1 - Math.abs(w);

  // Belly morph composition:
  //   - belly_high (anterior abdominal mass / "overhang") only engages
  //     once BF crosses the threshold where real overhang appears in
  //     human bodies (~22 % male, ~30 % female): a "skinny-fat" male at
  //     28 % gets mild overhang (0.4) while morbid obesity at 42 % gets
  //     strong overhang (1.3, capped).
  //   - belly_low (abs / muscle relief) needs BOTH low BF AND high muscle
  //     to read — gated multiplicatively so a thin-but-untrained user
  //     doesn't get unearned abs.
  const bellyHigh = clamp((bfPct - BELLY_THRESHOLD[sex]) / BELLY_RANGE, 0, BELLY_CAP);
  const bellyLow = Math.min(mHi, wLo * 1.5);

  const inf: Record<string, number> = {
    muscle_high: mHi * wAvg,
    muscle_low:  mLo * wAvg,
    weight_high: mAvg * wHi,
    weight_low:  mAvg * wLo,
    muscle_high_weight_high: mHi * wHi,
    muscle_high_weight_low:  mHi * wLo,
    muscle_low_weight_high:  mLo * wHi,
    muscle_low_weight_low:   mLo * wLo,
    belly_high:  bellyHigh,
    belly_low:   bellyLow,
  };
  // Female-only chest tissue: driven by the weight coordinate. MakeHuman's
  // weight macro barely touches breast geometry, so we drive a dedicated
  // breast morph in parallel from the same signal.
  if (sex === 'f') {
    inf.breast_high = wHi;
    inf.breast_low  = wLo;
  }
  return inf;
}

function setMorphInfluences(mesh: THREE.Mesh, weightKg: number, bfPct: number, heightM: number, sex: Sex) {
  const dict = mesh.morphTargetDictionary;
  const inf = mesh.morphTargetInfluences;
  if (!dict || !inf) return;
  const values = computeMorphInfluences(weightKg, bfPct, heightM, sex);
  for (const [name, v] of Object.entries(values)) {
    const idx = dict[name];
    if (idx !== undefined) inf[idx] = v;
  }
}

export function BodyModel3D({
  weightKg, bfPct, heightM, sex, skinfolds, compareWith, height = 480,
}: BodyModel3DProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // Holds the imperative update + cleanup closures so the props-effect can
  // poke them when weight/bfPct change without re-creating the scene.
  const stateRef = useRef<{
    rerender?: (props: BodyModel3DProps) => void;
    cleanup?: () => void;
  }>({});

  // ── Mount: lazy-load three + build the scene ──────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let alive = true;

    (async () => {
      // Lazy imports keep three out of the initial JS bundle.
      const THREE = await import('three');
      const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js');
      const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js');
      const { MeshDeformer } = await import('./MeshDeformer');

      if (!alive || !containerRef.current) return;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x0b0f14);

      const camera = new THREE.PerspectiveCamera(35, 1, 0.05, 100);
      const renderer = (() => {
        try {
          return new THREE.WebGLRenderer({ antialias: true, alpha: false });
        } catch {
          return null;
        }
      })();
      if (!renderer) {
        container.innerText = 'WebGL is not available on this device.';
        return;
      }
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      container.appendChild(renderer.domElement);

      function resize() {
        if (!containerRef.current) return;
        const w = containerRef.current.clientWidth;
        const h = containerRef.current.clientHeight;
        renderer!.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      }
      resize();
      window.addEventListener('resize', resize);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.target.set(0, 0.95, 0);
      controls.enableDamping = true;
      controls.dampingFactor = 0.1;
      controls.minDistance = 1.5;
      controls.maxDistance = 7;
      controls.enablePan = false;
      controls.minPolarAngle = Math.PI * 0.25;
      controls.maxPolarAngle = Math.PI * 0.6;
      // Reduced motion: disable damping so the scene settles in one frame.
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        controls.enableDamping = false;
        controls.autoRotate = false;
      }

      // ── Three-point lighting, scaled for ACES tonemap ─────────────────────
      // Slightly cooler ambient so the warm key reads as direct sunlight
      // rather than flat overall warmth.
      scene.add(new THREE.AmbientLight(0xbfd0e0, 0.28));
      // Key: warm directional, slightly more lateral so it carves the
      // deltoid + ribcage silhouette better.
      const key = new THREE.DirectionalLight(0xfff0d8, 2.6);
      key.position.set(3.0, 3.2, 2.0);
      scene.add(key);
      // Fill: muted cool blue-grey, low enough not to fight the key but
      // present enough to fill in shadows on the opposite side.
      const fill = new THREE.DirectionalLight(0xa3b4cc, 0.55);
      fill.position.set(-3.0, 1.5, 1.0);
      scene.add(fill);
      // Rim: warm-tinged back light to separate body from background.
      const rim = new THREE.DirectionalLight(0xffe4c0, 1.1);
      rim.position.set(0, 2.2, -3.0);
      scene.add(rim);

      // Floor disc for grounding
      const ground = new THREE.Mesh(
        new THREE.CircleGeometry(2.5, 64),
        new THREE.MeshStandardMaterial({ color: 0x141a22, roughness: 0.95 }),
      );
      ground.rotation.x = -Math.PI / 2;
      ground.position.y = -0.001;
      scene.add(ground);

      // ── Load both base meshes once, cache for sex toggle ──────────────────
      const loader = new GLTFLoader();
      const loadMesh = async (s: Sex): Promise<THREE.Mesh> => {
        const gltf = await loader.loadAsync(`/body-sim/${s === 'm' ? 'male' : 'female'}-base.glb`);
        const meshes: THREE.Mesh[] = [];
        gltf.scene.traverse((o) => {
          if ((o as THREE.Mesh).isMesh) meshes.push(o as THREE.Mesh);
        });
        if (meshes.length === 0) throw new Error(`No mesh found in ${s}-base.glb`);
        return meshes[0];
      };

      // Two scene bodies — "current" and (optional) "goal".
      let currentBody: THREE.Mesh | null = null;
      let goalBody: THREE.Mesh | null = null;
      let currentDeformer: InstanceType<typeof MeshDeformer> | null = null;
      let goalDeformer: InstanceType<typeof MeshDeformer> | null = null;
      let lastSex: Sex | null = null;

      function makeSkinMaterial(color: number, emissive: number) {
        return new THREE.MeshStandardMaterial({
          color,
          emissive,
          emissiveIntensity: 0.6,
          roughness: 0.62,
          metalness: 0.0,
        });
      }

      async function ensureBodies(s: Sex) {
        if (lastSex === s && currentBody) return;
        // Dispose old bodies
        for (const b of [currentBody, goalBody]) {
          if (b) {
            scene.remove(b);
            (b.geometry as THREE.BufferGeometry).dispose();
            const m = b.material as THREE.Material | THREE.Material[];
            if (Array.isArray(m)) m.forEach((mm) => mm.dispose());
            else m.dispose();
          }
        }
        currentBody = null;
        goalBody = null;
        currentDeformer = null;
        goalDeformer = null;

        const base = await loadMesh(s);
        // Clone two independent meshes so compare-mode never shares geometry
        // — POC1's "second body invisible" bug came from shared buffers.
        //
        // `new THREE.Mesh(geometry, material)` calls updateMorphTargets()
        // which rebuilds morphTargetDictionary using fallback string indices
        // ("0", "1", ...) because the cloned geometry's morphAttributes don't
        // carry the original target names. The names were originally written
        // onto the base mesh by GLTFLoader from `extras.targetNames`; we
        // copy them across so callers can address morphs by name.
        const baseDict = base.morphTargetDictionary ?? {};
        currentBody = new THREE.Mesh(
          (base.geometry as THREE.BufferGeometry).clone(),
          makeSkinMaterial(SKIN_COLOR, SKIN_EMISSIVE),
        );
        goalBody = new THREE.Mesh(
          (base.geometry as THREE.BufferGeometry).clone(),
          makeSkinMaterial(GOAL_COLOR, GOAL_EMISSIVE),
        );
        currentBody.morphTargetDictionary = { ...baseDict };
        goalBody.morphTargetDictionary = { ...baseDict };
        currentDeformer = new MeshDeformer(currentBody);
        goalDeformer = new MeshDeformer(goalBody);
        scene.add(currentBody);
        scene.add(goalBody);
        lastSex = s;
      }

      async function rerender(p: BodyModel3DProps) {
        await ensureBodies(p.sex);
        if (!currentBody || !goalBody || !currentDeformer || !goalDeformer) return;

        // Scale the mesh proportionally to the user's height. The baked GLB
        // is 1.75 m; this stretches/shrinks uniformly so a 2.05 m user gets
        // a visibly taller silhouette. Goal body uses the same height since
        // a cut/bulk doesn't change skeletal proportions.
        const scale = p.heightM / 1.75;
        currentBody.scale.setScalar(scale);
        goalBody.scale.setScalar(scale);

        // Step 1: broad muscle/weight macros via GLB morph targets.
        // Step 2: fine regional shape via MeshDeformer (caliper-driven).
        // The two compose additively in Three's vertex shader — morphs
        // sit on top of whatever positions the deformer writes.
        setMorphInfluences(currentBody, p.weightKg, p.bfPct, p.heightM, p.sex);
        currentDeformer.apply({
          weightKg: p.weightKg, bfPct: p.bfPct, heightM: p.heightM,
          sex: p.sex, skinfolds: p.skinfolds,
        });

        if (p.compareWith) {
          goalBody.visible = true;
          setMorphInfluences(goalBody, p.compareWith.weightKg, p.compareWith.bfPct, p.heightM, p.sex);
          goalDeformer.apply({
            weightKg: p.compareWith.weightKg, bfPct: p.compareWith.bfPct,
            heightM: p.heightM, sex: p.sex,
            skinfolds: p.compareWith.skinfolds,
          });
          // Side-by-side framing.
          currentBody.position.x = -0.55;
          goalBody.position.x = 0.55;
          camera.position.set(0, 1.00, 4.0);
          controls.target.set(0, 0.95, 0);
        } else {
          goalBody.visible = false;
          currentBody.position.x = 0;
          // Tighter framing: pulled in from 3.4m → 2.8m, eye-level target
          // dropped to 0.90m (just above body center of mass) so the head
          // is in the upper third — natural rule-of-thirds composition.
          camera.position.set(0, 1.00, 2.8);
          controls.target.set(0, 0.90, 0);
        }
      }

      let raf = 0;
      function tick() {
        controls.update();
        renderer!.render(scene, camera);
        raf = requestAnimationFrame(tick);
      }
      tick();

      rerender({ weightKg, bfPct, heightM, sex, skinfolds, compareWith, height });
      stateRef.current.rerender = (p) => { void rerender(p); };
      stateRef.current.cleanup = () => {
        cancelAnimationFrame(raf);
        window.removeEventListener('resize', resize);
        for (const b of [currentBody, goalBody]) {
          if (b) {
            (b.geometry as THREE.BufferGeometry).dispose();
            const m = b.material as THREE.Material | THREE.Material[];
            if (Array.isArray(m)) m.forEach((mm) => mm.dispose());
            else m.dispose();
          }
        }
        renderer.dispose();
        if (container.contains(renderer.domElement)) {
          container.removeChild(renderer.domElement);
        }
      };
    })();

    return () => {
      alive = false;
      stateRef.current.cleanup?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Props update: re-deform without rebuilding the scene ─────────────────
  useEffect(() => {
    // Defer one tick so the mount-effect has time to publish rerender.
    const id = setTimeout(() => {
      stateRef.current.rerender?.({
        weightKg, bfPct, heightM, sex, skinfolds, compareWith, height,
      });
    }, 0);
    return () => clearTimeout(id);
  }, [
    weightKg, bfPct, heightM, sex,
    skinfolds?.chest, skinfolds?.abdominal, skinfolds?.thigh, skinfolds?.tricep,
    skinfolds?.subscapular, skinfolds?.suprailiac, skinfolds?.midaxillary,
    compareWith?.weightKg, compareWith?.bfPct,
    compareWith?.skinfolds?.chest, compareWith?.skinfolds?.abdominal,
    compareWith?.skinfolds?.thigh, compareWith?.skinfolds?.tricep,
    compareWith?.skinfolds?.subscapular, compareWith?.skinfolds?.suprailiac,
    compareWith?.skinfolds?.midaxillary,
    height,
  ]);

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height,
        borderRadius: 8,
        overflow: 'hidden',
        background: '#0b0f14',
      }}
      aria-label="3D body composition visualization"
    />
  );
}
