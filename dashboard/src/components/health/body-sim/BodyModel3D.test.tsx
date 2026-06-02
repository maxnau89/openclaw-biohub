/**
 * BodyModel3D smoke test in jsdom.
 *
 * jsdom has no WebGL, so this only verifies the React component:
 *   - renders without throwing during the initial mount cycle
 *   - mounts a container element with the right aria-label
 *   - tears down cleanly on unmount
 *
 * The actual Three.js scene + morph + deformer paths are exercised by
 * MeshDeformer.test.ts and the visual gallery (Playwright + a real
 * browser). Mocking Three.js here would just re-implement it in the
 * test, which adds no real safety.
 */
import { describe, expect, it, vi } from 'vitest';
import { render, cleanup } from '@testing-library/react';

import { BodyModel3D } from './BodyModel3D';

describe('BodyModel3D (jsdom smoke)', () => {
  it('mounts a container with the right aria-label and unmounts cleanly', () => {
    // Silence the "no WebGL" warning the component logs on mount.
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const { container, unmount } = render(
      <BodyModel3D
        weightKg={80}
        bfPct={15}
        heightM={1.75}
        sex="m"
      />,
    );

    const div = container.querySelector('[aria-label="3D body composition visualization"]');
    expect(div).not.toBeNull();
    expect(div?.tagName).toBe('DIV');

    unmount();
    cleanup();
    warn.mockRestore();
  });

  it('accepts skinfolds + compareWith props without throwing', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const { unmount } = render(
      <BodyModel3D
        weightKg={82}
        bfPct={13}
        heightM={1.75}
        sex="m"
        skinfolds={{
          chest: 8, abdominal: 14, thigh: 12, tricep: 10,
          subscapular: 12, suprailiac: 12, midaxillary: 8,
        }}
        compareWith={{ weightKg: 78, bfPct: 10 }}
      />,
    );
    unmount();
    cleanup();
    warn.mockRestore();
  });

  it('female sex prop renders without throwing', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const { unmount } = render(
      <BodyModel3D
        weightKg={65}
        bfPct={22}
        heightM={1.65}
        sex="f"
      />,
    );
    unmount();
    cleanup();
    warn.mockRestore();
  });
});
