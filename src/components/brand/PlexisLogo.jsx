/**
 * PlexisLogo — the official Plexis brand mark.
 *
 * SINGLE SOURCE OF TRUTH for the canonical Plexis logo geometry.
 *
 * Shape: Lucide Sparkles v1.17.0 — exact path data extracted from
 *   node_modules/lucide-react/dist/esm/icons/sparkles.mjs
 *   This component renders the same geometric paths as <Sparkles /> from lucide-react,
 *   giving us full control over color, background, and favicon export without
 *   depending on the React component wrapper.
 *
 * ────────────────────────────────────────────────────────────────
 * CANONICAL PLEXIS SVG PATHS (viewBox 0 0 24 24, stroke-based):
 *
 *   path: M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594
 *         l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594
 *         l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594
 *         l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z
 *   path: M20 2v4
 *   path: M22 4h-4
 *   circle: cx=4 cy=20 r=2
 *
 * ────────────────────────────────────────────────────────────────
 *
 * Props:
 *   width, height  — size in px (default 32)
 *   variant        — "auto" | "blue" | "white"
 *                    "blue"  → always PLEXIS_BLUE (#2563eb)
 *                    "white" → always #ffffff (for use on blue/accent surfaces)
 *                    "auto"  → resolves via `surface` hint, defaults to "blue"
 *   surface        — "dark" | "accent" | "light" (used by "auto" variant)
 *                    "dark"   → blue logo
 *                    "accent" → white logo (on blue backgrounds)
 *                    "light"  → blue logo
 *   className      — extra class for the wrapper
 *
 * Usage:
 *   <PlexisLogo />                          dark bg → blue
 *   <PlexisLogo variant="white" />          white logo (blue surface)
 *   <PlexisLogo variant="auto" surface="accent" />   white
 *   <PlexisLogo variant="auto" surface="dark" />     blue
 */
import React from 'react';

// ── Design token — single source of truth for Plexis brand blue ──────────────
export const PLEXIS_BLUE = '#2563eb';
export const PLEXIS_WHITE = '#ffffff';

// ── Exact Lucide Sparkles v1.17.0 SVG paths ─────────────────────────────────
// These are the SAME paths rendered by <Sparkles /> from lucide-react.
// Geometry is identical — only color/surface behavior is added here.
export const SPARKLES_PATHS = {
  // Large 4-pointed star
  star: "M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z",
  // Small cross (upper-right sparkle) — vertical arm
  crossV: "M20 2v4",
  // Small cross (upper-right sparkle) — horizontal arm
  crossH: "M22 4h-4",
  // Small circle (lower-left sparkle)
  circleProps: { cx: "4", cy: "20", r: "2" },
};

// ── Color resolver ───────────────────────────────────────────────────────────
function resolveColor(variant, surface) {
  if (variant === 'white') return PLEXIS_WHITE;
  if (variant === 'blue') return PLEXIS_BLUE;
  // variant === 'auto'
  if (surface === 'accent') return PLEXIS_WHITE;
  // dark | light | undefined → blue (app is always dark-themed)
  return PLEXIS_BLUE;
}

// ── Component ────────────────────────────────────────────────────────────────
export default function PlexisLogo({
  width = 32,
  height = 32,
  variant = 'auto',
  surface = 'dark',
  color,           // manual override — bypasses variant/surface entirely
  className = '',
}) {
  // `color` prop is an escape hatch for legacy callers or one-off overrides.
  const iconColor = color ?? resolveColor(variant, surface);
  const iconSize = Math.min(width, height) * 0.82;

  return (
    <div
      className={`plexis-logo-container ${className}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: width,
        height: height,
        flexShrink: 0,
      }}
      aria-hidden="true"
    >
      {/*
        Inline SVG using the exact same paths as <Sparkles /> from lucide-react v1.17.0.
        fill="none", stroke-based — matches the outlined appearance of the sidebar logo.
      */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        width={iconSize}
        height={iconSize}
        viewBox="0 0 24 24"
        fill="none"
        stroke={iconColor}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{
          filter: `drop-shadow(0 0 6px ${iconColor}55)`,
          transition: 'stroke 0.2s ease, filter 0.2s ease',
          display: 'block',
        }}
      >
        <path d={SPARKLES_PATHS.star} />
        <path d={SPARKLES_PATHS.crossV} />
        <path d={SPARKLES_PATHS.crossH} />
        <circle {...SPARKLES_PATHS.circleProps} />
      </svg>
    </div>
  );
}
