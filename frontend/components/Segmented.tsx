"use client";

// Generic segmented control (a pill with N options, one active).
// Used in the Dashboard's environment filters and in the top view toggle.
// A "controlled" component: the caller passes `value` and receives `onChange` — the state
// lives in the parent (the same pattern as a controlled <select> in React).

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = "md",
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: "sm" | "md" | "lg";
}) {
  // `lg` exists for the fixed frame (the topbar's EN/PT toggle), which is ~20% bigger
  // than the pages' controls — `sm`/`md` keep serving the content.
  const pad = {
    sm: "px-2.5 py-1 text-[12px]",
    md: "px-3 py-1.5 text-[13px]",
    lg: "px-3.5 py-1.5 text-[14.5px]",
  }[size];
  return (
    <div className="inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={`rounded-md font-medium transition-colors ${pad} ${
              active
                ? "bg-surface-2 text-foreground shadow-sm"
                : "text-fg-3 hover:text-foreground"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
