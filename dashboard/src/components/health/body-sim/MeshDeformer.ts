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

/** Hermite smoothstep — eases from 0 → 1 over the open interval (edge0, edge1).
 *  Accepts inverted edges (edge0 > edge1) for "fade out" by setting edge0 high.
 *  Used to make side-filter boundaries soft so the deformation doesn't ridge. */
function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.max(0, Math.min(1, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

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
    //
    // All side filters use **smoothstep falloffs** instead of binary cutoffs
    // so vertices on the boundary of a region get partial weight. Without
    // this, deformation at high skinfold deltas produces visible ridges
    // (sharp transitions between "fully displaced" and "not displaced" verts).
    this.weights = new Float32Array(this.nVerts * LANDMARK_NAMES.length);
    for (let vi = 0; vi < this.nVerts; vi++) {
      const y = this.basePositions[vi * 3 + 1];
      const yNorm = (y - yMin) / height;
      const nx = normal.getX(vi);
      const ny = normal.getY(vi);
      const nz = normal.getZ(vi);
      // Filter out vertices on tops of head, soles of feet — they shouldn't
      // pick up any caliper weight.
      const horizontalGate = smoothstep(0.95, 0.75, Math.abs(ny));

      for (let li = 0; li < LANDMARK_NAMES.length; li++) {
        const lm = LANDMARKS[LANDMARK_NAMES[li]];
        // Y-axis Gaussian falloff
        const dy = (yNorm - lm.yFrac) / lm.sigmaY;
        let w = Math.exp(-0.5 * dy * dy) * horizontalGate;

        // Side gate: 0..1 weight by how well the vertex's surface direction
        // matches the landmark's anatomical region. Soft on both boundaries.
        let sideGate = 0;
        switch (lm.side) {
          case 'front':
            // Anterior surface: nz close to +1, |nx| small.
            sideGate = smoothstep(0.15, 0.55, nz) *
                       smoothstep(0.75, 0.45, Math.abs(nx));
            break;
          case 'back':
            // Posterior surface: nz close to −1, |nx| small.
            sideGate = smoothstep(0.15, 0.55, -nz) *
                       smoothstep(0.75, 0.45, Math.abs(nx));
            break;
          case 'arm-back':
            // Upper-arm posterior: |nx| dominant (sideways) + nz negative.
            sideGate = smoothstep(0.35, 0.65, Math.abs(nx)) *
                       smoothstep(0.30, -0.10, nz);
            break;
          case 'lateral':
            // Torso flank: |nx| dominant, |nz| small.
            sideGate = smoothstep(0.40, 0.70, Math.abs(nx)) *
                       smoothstep(0.65, 0.35, Math.abs(nz));
            break;
        }
        this.weights[vi * LANDMARK_NAMES.length + li] = w * sideGate;
      }
    }
  }

  /** Re-deforms the mesh in place against `params`. Cheap (~5 ms for 13 k verts). */
  apply(params: DeformParams): void {
    const baseSkinfolds = BASELINE_SKINFOLDS_MM[params.sex];
    const baseBF = BASELINE_BF_PCT[params.sex];

    // Per-landmark fat-depth delta in cm. Two-stage transform:
    //   1) skinfold mm → fat-depth mm via the /2 (caliper pinches a double
    //      layer of skin + fat). Clamp inward so we can't pull the surface
    //      through the baseline lean skeleton.
    //   2) signed sqrt falloff: displacement_cm = sign(Δ) · √|Δ_mm| · GAIN
    //      A linear /10 makes small deltas vanish — a user whose actual
    //      body composition is close to the baked baseline gets a Current
    //      shape that matches well, but the Goal body in compare-mode
    //      collapses to the baseline as the projected fat drops. Sqrt
    //      amplifies near-zero deltas while compressing the extremes,
    //      so the Goal reads as visibly leaner without overshooting the
    //      Apple-shape case into "bulging" territory.
    const SQRT_GAIN = 0.22;
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
      deltaCm[li] = Math.sign(clamped) * Math.sqrt(Math.abs(clamped)) * SQRT_GAIN;
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
