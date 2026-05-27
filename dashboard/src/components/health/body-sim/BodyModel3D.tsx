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

const SKIN_COLOR = 0xe2c4a0;
const GOAL_COLOR = 0x80d0a0;

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
      scene.add(new THREE.AmbientLight(0xffffff, 0.35));
      const key = new THREE.DirectionalLight(0xffffff, 2.2);
      key.position.set(2.5, 3.0, 2.5);
      scene.add(key);
      const fill = new THREE.DirectionalLight(0x88aacc, 0.9);
      fill.position.set(-3.0, 1.8, 1.5);
      scene.add(fill);
      const rim = new THREE.DirectionalLight(0xffffff, 1.4);
      rim.position.set(0, 2.0, -3.0);
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

      function makeSkinMaterial(color: number) {
        return new THREE.MeshStandardMaterial({
          color,
          roughness: 0.55,
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
        currentBody = new THREE.Mesh(
          (base.geometry as THREE.BufferGeometry).clone(),
          makeSkinMaterial(SKIN_COLOR),
        );
        goalBody = new THREE.Mesh(
          (base.geometry as THREE.BufferGeometry).clone(),
          makeSkinMaterial(GOAL_COLOR),
        );
        currentDeformer = new MeshDeformer(currentBody);
        goalDeformer = new MeshDeformer(goalBody);
        scene.add(currentBody);
        scene.add(goalBody);
        lastSex = s;
      }

      async function rerender(p: BodyModel3DProps) {
        await ensureBodies(p.sex);
        if (!currentBody || !goalBody || !currentDeformer || !goalDeformer) return;

        currentDeformer.apply({
          weightKg: p.weightKg, bfPct: p.bfPct, heightM: p.heightM,
          sex: p.sex, skinfolds: p.skinfolds,
        });

        if (p.compareWith) {
          goalBody.visible = true;
          goalDeformer.apply({
            weightKg: p.compareWith.weightKg, bfPct: p.compareWith.bfPct,
            heightM: p.heightM, sex: p.sex,
            skinfolds: p.compareWith.skinfolds,
          });
          // Side-by-side framing.
          currentBody.position.x = -0.55;
          goalBody.position.x = 0.55;
          camera.position.set(0, 1.05, 4.6);
          controls.target.set(0, 0.95, 0);
        } else {
          goalBody.visible = false;
          currentBody.position.x = 0;
          camera.position.set(0, 1.05, 3.4);
          controls.target.set(0, 0.95, 0);
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
