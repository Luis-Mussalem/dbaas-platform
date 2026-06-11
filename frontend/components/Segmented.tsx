"use client";

// Controle segmentado genérico (pílula com N opções, uma ativa).
// Usado nos filtros de ambiente do Painel e no toggle Habitat/Console do topo.
// Componente "controlado": quem usa passa `value` e recebe `onChange` — o estado
// vive no pai (mesmo padrão de um <select> controlado no React).

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
  size?: "sm" | "md";
}) {
  const pad = size === "sm" ? "px-2.5 py-1 text-[12px]" : "px-3 py-1.5 text-[13px]";
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
