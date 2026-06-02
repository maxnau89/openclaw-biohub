/**
 * MeshDeformer unit tests.
 *
 * These run in jsdom against a hand-built BufferGeometry (no GLB load,
 * no WebGL context required). The fixture mesh is a thin vertical strip
 * of vertices spanning Y=0..1.75 m with X=±0.2 (lateral) and a few
 * Z values to simulate front/back surfaces. Each test pokes
 * `MeshDeformer.apply(...)` and checks that vertices in the expected
 * anatomical region moved (or didn't) the right amount.
 */
import { describe, expect, it } from 'vitest';
import * as THREE from 'three';

import { MeshDeformer } from './MeshDeformer';
import type { Skinfolds } from './anthropometrics';

// ─── Fixture mesh ────────────────────────────────────────────────────────────

/**
 * Build a synthetic human-ish vertex cloud spanning the expected
 * coordinate ranges of our baked GLBs (Y-up, 1.75 m tall, X-span ±0.25,
 * Z-span ±0.20). We don't need triangles — `MeshDeformer` only consumes
 * positions + normals.
 *
 * For each anatomical region, we plant one vertex with a normal pointing
 * outward in the expected direction. That way we can verify the deformer
 * (a) moves it the right amount and (b) along the surface normal.
 */
function buildFixture(): THREE.Mesh {
  const positions: number[] = [];
  const normals: number[] = [];

  function add(x: number, y: number, z: number, nx: number, ny: number, nz: number) {
    positions.push(x, y, z);
    normals.push(nx, ny, nz);
  }

  // Anchor extremes so the bounding box matches a real body GLB.
  add(0,  0.00, 0,    0, -1, 0);  // foot bottom
  add(0,  1.75, 0,    0,  1, 0);  // top of head
  add(-0.25, 0.9, 0, -1, 0, 0);   // X-min lateral
  add( 0.25, 0.9, 0,  1, 0, 0);   // X-max lateral
  add(0,  0.9, -0.20, 0, 0, -1);  // Z-min back
  add(0,  0.9,  0.20, 0, 0,  1);  // Z-max front

  // Anatomical probes — landmark, then anchor X/Y/Z per the spec.
  // 1.75 m mesh, so yFrac × 1.75 = Y position.

  // chest: yFrac 0.73 → Y=1.28, front (high Z), near midline (X≈0)
  add(0, 1.28, 0.18, 0, 0, 1);

  // abdominal: yFrac 0.59 → Y=1.03, front, midline
  add(0, 1.03, 0.18, 0, 0, 1);

  // thigh: yFrac 0.39 → Y=0.68, front, midline
  add(0, 0.68, 0.18, 0, 0, 1);

  // tricep: yFrac 0.71 → Y=1.24, arm-back (lateral X + Z below center)
  add(0.22, 1.24, -0.10, 1, 0, -0.3);

  // subscapular: yFrac 0.74 → Y=1.30, back (low Z, near midline)
  add(0, 1.30, -0.18, 0, 0, -1);

  // suprailiac: yFrac 0.53 → Y=0.93, lateral (X ≈ ±0.20)
  add(0.20, 0.93, 0, 1, 0, 0);

  // midaxillary: yFrac 0.65 → Y=1.14, lateral
  add(0.20, 1.14, 0, 1, 0, 0);

  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geom.setAttribute('normal',   new THREE.Float32BufferAttribute(normals,   3));
  return new THREE.Mesh(geom, new THREE.MeshBasicMaterial());
}

// Vertex indices for the probes added in buildFixture (after the 6 anchors).
const IDX = {
  chest:       6,
  abdominal:   7,
  thigh:       8,
  tricep:      9,
  subscapular: 10,
  suprailiac:  11,
  midaxillary: 12,
};

function vertexPos(mesh: THREE.Mesh, i: number): [number, number, number] {
  const p = mesh.geometry.attributes.position;
  return [p.getX(i), p.getY(i), p.getZ(i)];
}

function distance(a: [number, number, number], b: [number, number, number]): number {
  const dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2];
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

const BASE_SKINFOLDS_M: Skinfolds = {
  chest: 8, abdominal: 14, thigh: 12, tricep: 10,
  subscapular: 12, suprailiac: 12, midaxillary: 8,
};

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('MeshDeformer — construction', () => {
  it('captures the base height from the mesh bounding box', () => {
    const mesh = buildFixture();
    const d = new MeshDeformer(mesh);
    expect(d.getBaseHeight()).toBeCloseTo(1.75, 2);
  });
});

describe('MeshDeformer — uniform-distribution fallback (no skinfolds)', () => {
  it('inflates all anatomical probes when bfPct rises above baseline', () => {
    const mesh = buildFixture();
    const d = new MeshDeformer(mesh);
    const before = vertexPos(mesh, IDX.abdominal);
    d.apply({ weightKg: 80, bfPct: 25, heightM: 1.75, sex: 'm' });
    const after = vertexPos(mesh, IDX.abdominal);
    // Should have moved outward (along +Z normal, since abdominal probe
    // sits at z=0.18 with normal (0,0,1)).
    expect(after[2]).toBeGreaterThan(before[2]);
  });

  it('pulls vertices inward when bfPct drops below baseline', () => {
    const mesh = buildFixture();
    const d = new MeshDeformer(mesh);
    const before = vertexPos(mesh, IDX.abdominal);
    d.apply({ weightKg: 70, bfPct: 8, heightM: 1.75, sex: 'm' });
    const after = vertexPos(mesh, IDX.abdominal);
    expect(after[2]).toBeLessThan(before[2]);
  });

  it('clamps inward displacement so vertices never collapse below baseline floor', () => {
    const mesh = buildFixture();
    const d = new MeshDeformer(mesh);
    const before = vertexPos(mesh, IDX.abdominal);
    d.apply({ weightKg: 60, bfPct: 1, heightM: 1.75, sex: 'm' });
    const after = vertexPos(mesh, IDX.abdominal);
    const pullCm = (before[2] - after[2]) * 100;
    // Baseline abdominal skinfold = 14 mm → base fat 6 mm → 60 % floor = 3.6 mm pull.
    // At least one component (Z) here, so pull <~ 0.4 cm.
    expect(pullCm).toBeLessThan(0.5);
  });
});

describe('MeshDeformer — caliper-driven regional shape', () => {
  it('apple-shape skinfolds inflate abdominal far more than thigh', () => {
    const mesh = buildFixture();
    const d = new MeshDeformer(mesh);
    const beforeAbd = vertexPos(mesh, IDX.abdominal);
    const beforeThi = vertexPos(mesh, IDX.thigh);

    // Apple shape: big abdominal + suprailiac, lean thigh.
    const apple: Skinfolds = {
      chest: 10, abdominal: 30, thigh: 8, tricep: 9,
      subscapular: 14, suprailiac: 28, midaxillary: 10,
    };
    d.apply({
      weightKg: 85, bfPct: 22, heightM: 1.75, sex: 'm', skinfolds: apple,
    });
    const afterAbd = vertexPos(mesh, IDX.abdominal);
    const afterThi = vertexPos(mesh, IDX.thigh);

    const abdMoved = distance(beforeAbd, afterAbd);
    const thiMoved = distance(beforeThi, afterThi);
    expect(abdMoved).toBeGreaterThan(thiMoved);
    expect(abdMoved).toBeGreaterThan(0.005);  // ~0.5 cm minimum
  });

  it('pear-shape skinfolds inflate thigh far more than abdominal', () => {
    const mesh = buildFixture();
    const d = new MeshDeformer(mesh);
    const beforeAbd = vertexPos(mesh, IDX.abdominal);
    const beforeThi = vertexPos(mesh, IDX.thigh);

    // Pear shape: lean abdominal, much bigger thigh.
    const pear: Skinfolds = {
      chest: 9, abdominal: 14, thigh: 36, tricep: 17,
      subscapular: 13, suprailiac: 24, midaxillary: 11,
    };
    d.apply({
      weightKg: 75, bfPct: 25, heightM: 1.70, sex: 'f', skinfolds: pear,
    });
    const afterAbd = vertexPos(mesh, IDX.abdominal);
    const afterThi = vertexPos(mesh, IDX.thigh);

    const thiMoved = distance(beforeThi, afterThi);
    const abdMoved = distance(beforeAbd, afterAbd);
    expect(thiMoved).toBeGreaterThan(abdMoved);
  });

  it('zero-delta skinfolds (exact baseline) leave the abdominal probe at rest', () => {
    const mesh = buildFixture();
    const d = new MeshDeformer(mesh);
    const before = vertexPos(mesh, IDX.abdominal);
    d.apply({
      weightKg: 80, bfPct: 15, heightM: 1.75, sex: 'm',
      skinfolds: BASE_SKINFOLDS_M,
    });
    const after = vertexPos(mesh, IDX.abdominal);
    expect(distance(before, after)).toBeLessThan(1e-6);
  });
});

describe('MeshDeformer — reset()', () => {
  it('restores the deformed mesh to its baked positions', () => {
    const mesh = buildFixture();
    const d = new MeshDeformer(mesh);
    const before = vertexPos(mesh, IDX.abdominal);
    d.apply({ weightKg: 100, bfPct: 32, heightM: 1.75, sex: 'm' });
    const deformed = vertexPos(mesh, IDX.abdominal);
    expect(distance(before, deformed)).toBeGreaterThan(0.001);

    d.reset();
    const restored = vertexPos(mesh, IDX.abdominal);
    expect(distance(before, restored)).toBeLessThan(1e-6);
  });
});

describe('MeshDeformer — sex-specific baseline', () => {
  it('female baseline expects higher thigh skinfold than male baseline', () => {
    const mesh = buildFixture();
    const d = new MeshDeformer(mesh);
    // Apply the female baseline with sex='m' → male sees thigh skinfold 22
    // as fatter-than-baseline (12), so thigh probe moves outward.
    const before = vertexPos(mesh, IDX.thigh);
    const femaleBaseline: Skinfolds = {
      chest: 10, abdominal: 16, thigh: 22, tricep: 15,
      subscapular: 14, suprailiac: 14, midaxillary: 12,
    };
    d.apply({ weightKg: 70, bfPct: 22, heightM: 1.75, sex: 'm', skinfolds: femaleBaseline });
    const afterM = vertexPos(mesh, IDX.thigh);

    d.reset();
    // Same skinfolds with sex='f' → matches female baseline exactly, no move.
    d.apply({ weightKg: 70, bfPct: 22, heightM: 1.75, sex: 'f', skinfolds: femaleBaseline });
    const afterF = vertexPos(mesh, IDX.thigh);

    expect(distance(before, afterM)).toBeGreaterThan(distance(before, afterF));
    expect(distance(before, afterF)).toBeLessThan(1e-6);
  });
});
