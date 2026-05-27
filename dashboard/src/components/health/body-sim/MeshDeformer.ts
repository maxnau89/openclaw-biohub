/**
 * MeshDeformer — caliper-driven vertex deformation on a loaded human GLB.
 *
 * The base GLBs at `dashboard/public/body-sim/{male,female}-base.glb` are
 * baked at neutral BF% (~15 % male, ~22 % female — the MakeHuman caucasian-
 * young defaults). For a given user's body composition, we morph the mesh by
 * displacing each vertex along its surface normal proportionally to the
 * difference between the user's skinfold measurements (mm) and the base
 * mesh's implied baseline. Vertices near a caliper site (e.g. the abdominal
 * site, at ~0.59 of mesh height, anterior) move outward more than vertices
 * far from any site; the Gaussian falloff smooths the transition between
 * regional fat deposits so a user with apple-shape distribution looks
 * apple-shaped without hard seams between regions.
 *
 * When skinfolds are not available (e.g. weight came from Apple Health, or
 * the user only has a scale BF reading), we fall back to a single uniform
 * fat depth scaled from `bfPct − baseBFPct`. The fall-back loses the regional
 * shape signature but still reads as "leaner" vs "softer".
 */
import * as THREE from 'three';
import type { Skinfolds, Sex } from './anthropometrics';

// ─── Anatomical landmarks ────────────────────────────────────────────────────
//
// Y-fractions of the mesh's total height (0 = feet, 1 = top of head).
// In Three.js / glTF Y-up world, the loaded GLB has the head at +Y, feet at
// Y=0, X is left/right, Z is forward (+Z toward viewer / anterior).
//
// `side` controls which half of the body each landmark belongs to. The
// numeric thresholds are fractions of the mesh's bounding-box extent on that
// axis. They were tuned against the baked MakeHuman base mesh; if a
// contributor swaps in a different base mesh with a different bounding box
// or pose, these may need re-tuning.

export type LandmarkName =
  | 'chest' | 'abdominal' | 'thigh'
  | 'tricep' | 'subscapular' | 'suprailiac' | 'midaxillary';

interface LandmarkSpec {
  yFrac: number;     // 0 = feet, 1 = head
  side: 'front' | 'back' | 'arm-back' | 'lateral';
  sigmaY: number;    // Gaussian falloff radius as fraction of mesh height
}

const LANDMARKS: Record<LandmarkName, LandmarkSpec> = {
  chest:       { yFrac: 0.73, side: 'front',    sigmaY: 0.04 },
  abdominal:   { yFrac: 0.59, side: 'front',    sigmaY: 0.04 },
  thigh:       { yFrac: 0.39, side: 'front',    sigmaY: 0.04 },
  tricep:      { yFrac: 0.71, side: 'arm-back', sigmaY: 0.05 },
  subscapular: { yFrac: 0.74, side: 'back',     sigmaY: 0.04 },
  suprailiac:  { yFrac: 0.53, side: 'lateral',  sigmaY: 0.04 },
  midaxillary: { yFrac: 0.65, side: 'lateral',  sigmaY: 0.04 },
};

const LANDMARK_NAMES = Object.keys(LANDMARKS) as LandmarkName[];

// ─── Baseline skinfolds for the baked GLBs ──────────────────────────────────
//
// Educated guesses for the MakeHuman caucasian-young default at ~15 % BF
// (male) and ~22 % BF (female). These are the skinfold readings we ASSUME
// our baked GLB silhouettes represent; a user supplying real caliper data
// is interpreted as a delta from these. If the baked mesh changes (different
// MakeHuman target, different ethnicity etc.) these need to be re-derived.
const BASELINE_SKINFOLDS_MM: Record<Sex, Skinfolds> = {
  m: {
    chest: 8, abdominal: 14, thigh: 12, tricep: 10,
    subscapular: 12, suprailiac: 12, midaxillary: 8,
  },
  f: {
    chest: 10, abdominal: 16, thigh: 22, tricep: 15,
    subscapular: 14, suprailiac: 14, midaxillary: 12,
  },
};

// Baseline BF% the baked meshes are assumed to represent.
const BASELINE_BF_PCT: Record<Sex, number> = { m: 15, f: 22 };

// ─── Public API ──────────────────────────────────────────────────────────────

export interface DeformParams {
  weightKg: number;
  bfPct: number;
  heightM: number;
  sex: Sex;
  /** Optional 7-site caliper. When present, drives regional fat shape. */
  skinfolds?: Skinfolds;
}

export class MeshDeformer {
  private readonly geometry: THREE.BufferGeometry;
  /** Base (un-deformed) vertex positions, owned by the deformer. */
  private readonly basePositions: Float32Array;
  /** Per-vertex × per-landmark weights, row-major (N_verts × 7). */
  private readonly weights: Float32Array;
  private readonly nVerts: number;
  private readonly baseHeight: number;

  constructor(mesh: THREE.Mesh) {
    this.geometry = mesh.geometry as THREE.BufferGeometry;
    if (!this.geometry.attributes.position) {
      throw new Error('MeshDeformer: geometry has no position attribute');
    }
    if (!this.geometry.attributes.normal) {
      throw new Error('MeshDeformer: geometry has no normal attribute (load a GLB with normals or call computeVertexNormals() on the mesh first)');
    }

    const pos = this.geometry.attributes.position;
    this.nVerts = pos.count;
    this.basePositions = new Float32Array(pos.array);

    // Bounding box
    this.geometry.computeBoundingBox();
    const bb = this.geometry.boundingBox!;
    const yMin = bb.min.y, yMax = bb.max.y;
    const height = yMax - yMin;
    this.baseHeight = height;

    const normal = this.geometry.attributes.normal as THREE.BufferAttribute;

    // Precompute per-vertex weights for each landmark.
    //
    // Side classification uses the vertex *normal* direction, which encodes
    // which surface of the body the vertex sits on regardless of the mesh's
    // overall bounding-box proportions. That makes the filter robust across
    // different base meshes (T-pose vs A-pose, different arm spans, etc.).
    //   - front:    normal points anterior (+Z)
    //   - back:     normal points posterior (-Z)
    //   - lateral:  normal points sideways (|X| dominant), Z near zero
    //   - arm-back: lateral component + posterior Z component
    this.weights = new Float32Array(this.nVerts * LANDMARK_NAMES.length);
    for (let vi = 0; vi < this.nVerts; vi++) {
      const y = this.basePositions[vi * 3 + 1];
      const yNorm = (y - yMin) / height;
      const nx = normal.getX(vi);
      const ny = normal.getY(vi);
      const nz = normal.getZ(vi);
      // Filter out vertices on tops of head, soles of feet — they shouldn't
      // pick up any caliper weight.
      const isHorizontal = Math.abs(ny) > 0.85;

      for (let li = 0; li < LANDMARK_NAMES.length; li++) {
        const lm = LANDMARKS[LANDMARK_NAMES[li]];
        // Y-axis Gaussian falloff
        const dy = (yNorm - lm.yFrac) / lm.sigmaY;
        let w = Math.exp(-0.5 * dy * dy);
        if (isHorizontal) w = 0;

        switch (lm.side) {
          case 'front':
            // Anterior surface: forward-facing normal, near body midline.
            if (nz < 0.30) w = 0;
            if (Math.abs(nx) > 0.55) w = 0;
            break;
          case 'back':
            if (nz > -0.30) w = 0;
            if (Math.abs(nx) > 0.55) w = 0;
            break;
          case 'arm-back':
            // Upper-arm posterior: lateral-facing with rearward bias.
            if (Math.abs(nx) < 0.50) w = 0;
            if (nz > 0.20) w = 0;
            break;
          case 'lateral':
            // Side of torso: lateral-facing, Z component small.
            if (Math.abs(nx) < 0.55) w = 0;
            if (Math.abs(nz) > 0.55) w = 0;
            break;
        }
        this.weights[vi * LANDMARK_NAMES.length + li] = w;
      }
    }
  }

  /** Re-deforms the mesh in place against `params`. Cheap (~5 ms for 13 k verts). */
  apply(params: DeformParams): void {
    const baseSkinfolds = BASELINE_SKINFOLDS_MM[params.sex];
    const baseBF = BASELINE_BF_PCT[params.sex];

    // Per-landmark fat-depth delta in cm (skinfold mm → fat thickness):
    //   depth_cm = max(clampFloor, ((current - base) / 2) / 10)
    // The /2 is because a caliper measures a double layer of skin + fat;
    // /10 converts mm → cm. We clamp to avoid negative thickness pulling
    // the mesh through itself when a very lean user is read against a
    // less-lean baseline.
    const deltaCm = new Array<number>(LANDMARK_NAMES.length);
    for (let li = 0; li < LANDMARK_NAMES.length; li++) {
      const name = LANDMARK_NAMES[li];
      let deltaMM: number;
      if (params.skinfolds) {
        deltaMM = (params.skinfolds[name] - baseSkinfolds[name]) / 2;
      } else {
        // Fallback: uniform proxy from BF% delta, scaled so 1 % BF drift
        // ≈ 0.6 mm of subcutaneous fat (rough textbook number).
        deltaMM = (params.bfPct - baseBF) * 0.6;
      }
      // Floor: never pull more than 60 % of the baseline thickness inward.
      const floor = -((baseSkinfolds[name] - 2) / 2) * 0.6;
      const clamped = Math.max(floor, deltaMM);
      deltaCm[li] = clamped / 10;
    }

    const pos = this.geometry.attributes.position as THREE.BufferAttribute;
    const normal = this.geometry.attributes.normal as THREE.BufferAttribute;
    const nLm = LANDMARK_NAMES.length;

    for (let vi = 0; vi < this.nVerts; vi++) {
      // Per-vertex displacement = Σ_landmarks weight_li × deltaCm_li
      let disp = 0;
      const wRow = vi * nLm;
      for (let li = 0; li < nLm; li++) {
        disp += this.weights[wRow + li] * deltaCm[li];
      }

      // Displace along normal. Convert cm → meters (the GLB units).
      const dispM = disp / 100;
      const nx = normal.getX(vi);
      const ny = normal.getY(vi);
      const nz = normal.getZ(vi);
      pos.setXYZ(
        vi,
        this.basePositions[vi * 3 + 0] + nx * dispM,
        this.basePositions[vi * 3 + 1] + ny * dispM,
        this.basePositions[vi * 3 + 2] + nz * dispM,
      );
    }

    pos.needsUpdate = true;
    this.geometry.computeVertexNormals();
  }

  /** Restore the mesh to its baked (un-deformed) shape. */
  reset(): void {
    const pos = this.geometry.attributes.position as THREE.BufferAttribute;
    (pos.array as Float32Array).set(this.basePositions);
    pos.needsUpdate = true;
    this.geometry.computeVertexNormals();
  }

  /** Mesh height (m) at baked, before deformation. Used by BodyModel3D for
   *  the height scale factor when the user is taller/shorter than 1.75 m. */
  getBaseHeight(): number {
    return this.baseHeight;
  }
}
