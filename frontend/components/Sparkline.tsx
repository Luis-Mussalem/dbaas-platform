// Sparkline — mini line chart (with optional gradient fill)
// drawn in pure SVG, no external dependency. Scales the values to fit
// the viewBox and stretches to 100% of the container's width.
//
// New concept: responsive SVG. The viewBox defines a fixed coordinate
// system (W×H); preserveAspectRatio="none" lets the SVG stretch freely to the
// element's real size, so the drawing follows any card width.

type SparklineProps = {
  data: number[];
  // Line/fill color — accepts a CSS token (e.g.: "var(--brand)").
  color?: string;
  fill?: boolean;
  className?: string;
  strokeWidth?: number;
  // Explicit Y domain. Without it, each sparkline auto-scales to its own range
  // (good for seeing the SHAPE of an isolated series). With it — typically [0, fleet
  // ceiling] — the scale becomes SHARED across cards and the height starts to encode
  // MAGNITUDE: a 12 q/s card ends up taller than a 4 q/s one. Values outside the
  // domain are clamped (a rare spike touches the top instead of overflowing).
  domainMin?: number;
  domainMax?: number;
};

const W = 100;
const H = 32;

export function Sparkline({
  data,
  color = "var(--brand)",
  fill = true,
  className = "h-9 w-full",
  strokeWidth = 1.5,
  domainMin,
  domainMax,
}: SparklineProps) {
  // Not enough data: draws a subtle baseline (an honest placeholder,
  // instead of inventing a curve). Keeps the card visually complete.
  if (!data || data.length < 2) {
    return (
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className={className}
        aria-hidden
      >
        <line
          x1="0"
          y1={H - 1}
          x2={W}
          y2={H - 1}
          stroke="var(--border-strong)"
          strokeWidth={strokeWidth}
        />
      </svg>
    );
  }

  // Explicit domain (scale shared across cards) takes priority over
  // per-series auto-scaling.
  const min = domainMin ?? Math.min(...data);
  const max = domainMax ?? Math.max(...data);
  const span = max - min || 1; // avoids division by zero when the series is flat

  // Maps each point to viewBox coordinates. y is inverted (0 = top). The
  // clamp keeps the line inside the frame when the domain is shared.
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    const norm = Math.min(1, Math.max(0, (v - min) / span));
    const y = H - 2 - norm * (H - 4);
    return [x, y] as const;
  });

  const line = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  // Closed area for the fill: line + drop to the base + return.
  const area = `${line} L${W},${H} L0,${H} Z`;
  const gradId = `spark-${Math.abs(hash(data))}`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden
    >
      {fill && (
        <>
          {/* Gradient anchored at the BASE: more solid at the bottom (zero, on a
              shared scale) and soft near the line. This way the fill reads as
              a level COLUMN starting from zero — a 10 q/s series visibly fills
              twice as much as a 5 q/s one — instead of a thin strip under the line. */}
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.12" />
              <stop offset="100%" stopColor={color} stopOpacity="0.34" />
            </linearGradient>
          </defs>
          <path d={area} fill={`url(#${gradId})`} stroke="none" />
        </>
      )}
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

// Simple hash just to generate a gradient id stable per series (avoids
// two sparklines sharing the same <linearGradient>).
function hash(data: number[]): number {
  let h = 0;
  for (const v of data) h = (h * 31 + Math.round(v * 100)) | 0;
  return h;
}
