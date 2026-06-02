"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronLeft, ChevronRight, X, Zap, RefreshCw } from "lucide-react";
import { createInstance } from "@/lib/api";
import { cn } from "@/lib/utils";

// Versões disponíveis (viram a tag postgres:<v>-alpine no provisionador).
const PG_VERSIONS = ["17", "16", "15", "14"] as const;
const RECOMMENDED = "16";

// "Planos" do design viram presets de recursos reais (cpu/memória/disco).
type Size = {
  id: string;
  label: string;
  desc: string;
  cpu: number;
  memory_mb: number;
  storage_gb: number;
};
const SIZES: Size[] = [
  { id: "hobby", label: "Hobby", desc: "Para experimentar", cpu: 1, memory_mb: 512, storage_gb: 10 },
  { id: "starter", label: "Starter", desc: "Projetos pequenos", cpu: 2, memory_mb: 2048, storage_gb: 50 },
  { id: "pro", label: "Pro", desc: "Produção", cpu: 4, memory_mb: 8192, storage_gb: 200 },
  { id: "business", label: "Business", desc: "Escala alta", cpu: 8, memory_mb: 16384, storage_gb: 500 },
];

const STEPS = ["Identidade", "Tamanho", "Revisar"];

// Classes de botão reutilizadas (mantêm consistência visual).
const BTN = "inline-flex h-9 items-center gap-1.5 rounded-md px-4 text-sm font-medium transition";
const BTN_PRIMARY = `${BTN} bg-primary text-primary-foreground hover:brightness-110`;
const BTN_DEFAULT = `${BTN} border border-border text-fg-2 hover:bg-surface-2 hover:text-foreground`;

export default function CreateInstancePage() {
  const router = useRouter();

  // ── estado do wizard ──
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [version, setVersion] = useState<string>(RECOMMENDED);
  const [sizeId, setSizeId] = useState("starter");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const size = SIZES.find((s) => s.id === sizeId)!;

  // Só deixa avançar do passo 0 com um nome válido.
  const canNext = step === 0 ? name.trim().length >= 2 : true;

  async function handleCreate() {
    setCreating(true);
    setError(null);
    try {
      // Submit REAL: este await dura ~10-30s (o backend sobe o container,
      // espera o PostgreSQL aceitar conexões e cria role + banco).
      const created = await createInstance({
        name: name.trim(),
        engine_version: version as "14" | "15" | "16" | "17",
        cpu: size.cpu,
        memory_mb: size.memory_mb,
        storage_gb: size.storage_gb,
      });
      router.push(`/instances/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao provisionar");
      setCreating(false);
    }
  }

  // ── tela de provisionamento (enquanto o POST não volta) ──
  if (creating) {
    return (
      <div className="mx-auto mt-20 max-w-md text-center">
        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-subtle text-brand">
          <RefreshCw size={28} className="animate-spin" />
        </div>
        <h2 className="text-2xl font-semibold">Provisionando…</h2>
        <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
          Subindo um container PostgreSQL {version} para{" "}
          <span className="font-mono text-foreground">{name}</span>. Leva ~30 segundos.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl">
      {/* header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Criar nova instância</h1>
          <p className="mt-1 text-sm text-muted-foreground">Passo {step + 1} de 3</p>
        </div>
        <button onClick={() => router.push("/instances")} className={BTN_DEFAULT}>
          <X size={13} /> Cancelar
        </button>
      </div>

      {/* indicador de passos */}
      <div className="mb-7 flex items-center">
        {STEPS.map((label, i) => (
          <div key={label} className="flex flex-1 items-center gap-2">
            <div
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold transition",
                i < step
                  ? "border-primary bg-primary text-primary-foreground"
                  : i === step
                    ? "border-brand bg-brand-subtle text-brand"
                    : "border-border text-fg-3"
              )}
            >
              {i < step ? <Check size={14} /> : i + 1}
            </div>
            <span
              className={cn(
                "text-[13px] font-medium",
                i === step ? "text-foreground" : "text-fg-3"
              )}
            >
              {label}
            </span>
            {i < STEPS.length - 1 && (
              <div className={cn("mx-3 h-px flex-1", i < step ? "bg-primary" : "bg-border")} />
            )}
          </div>
        ))}
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      {/* Passo 0 — Identidade */}
      {step === 0 && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <div className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <label className="text-[11px] font-medium uppercase tracking-wide text-fg-3">
                Nome da instância
              </label>
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="checkout-prod"
                className="h-9 rounded-md border border-border-strong bg-surface px-3 text-sm outline-none focus:border-brand"
              />
              <span className="text-xs text-fg-3">Algo memorável. Letras, números e hífens.</span>
            </div>

            <div className="flex flex-col gap-2">
              <label className="text-[11px] font-medium uppercase tracking-wide text-fg-3">
                Versão do PostgreSQL
              </label>
              <div className="flex flex-wrap gap-2">
                {PG_VERSIONS.map((v) => (
                  <button
                    key={v}
                    onClick={() => setVersion(v)}
                    className={cn(
                      "relative rounded-md border px-4 py-2.5 font-mono text-sm font-medium transition",
                      version === v
                        ? "border-brand bg-brand-subtle text-brand"
                        : "border-border hover:border-border-strong"
                    )}
                  >
                    {v}
                    {v === RECOMMENDED && (
                      <span className="absolute -right-1.5 -top-2 rounded bg-primary px-1.5 text-[9.5px] font-semibold text-primary-foreground">
                        recomendado
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Passo 1 — Tamanho */}
      {step === 1 && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h2 className="mb-1 text-sm font-semibold">Quanto poder?</h2>
          <p className="mb-4 text-xs text-fg-3">
            Define CPU, memória e disco do container.
          </p>
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            {SIZES.map((s) => {
              const on = sizeId === s.id;
              return (
                <button
                  key={s.id}
                  onClick={() => setSizeId(s.id)}
                  className={cn(
                    "rounded-md border p-4 text-left transition",
                    on ? "border-brand bg-brand-subtle" : "border-border hover:border-border-strong"
                  )}
                >
                  <div className={cn("text-[13px] font-semibold", on ? "text-brand" : "text-foreground")}>
                    {s.label}
                  </div>
                  <div className="text-[11.5px] text-fg-3">{s.desc}</div>
                  <div className="mt-3 font-mono text-[11.5px] leading-relaxed text-fg-3">
                    <div>
                      {s.cpu} vCPU · {s.memory_mb / 1024} GB RAM
                    </div>
                    <div>{s.storage_gb} GB SSD</div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Passo 2 — Revisar */}
      {step === 2 && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h2 className="mb-1 text-sm font-semibold">Revise antes de criar</h2>
          <p className="mb-5 text-xs text-fg-3">Quase lá.</p>
          <div className="grid grid-cols-2 gap-4">
            <Review label="Nome" value={name || "—"} mono />
            <Review label="Versão" value={`PostgreSQL ${version}`} />
            <Review label="Recursos" value={`${size.cpu} vCPU · ${size.memory_mb / 1024} GB RAM`} />
            <Review label="Disco" value={`${size.storage_gb} GB`} />
          </div>
          <div className="mt-5 rounded-md border border-info/25 bg-info/10 px-3 py-2.5 text-[12.5px] text-fg-2">
            Após criar, a string de conexão fica disponível no detalhe da instância — a senha é
            cifrada e guardada com segurança (nunca é devolvida pela API).
          </div>
        </div>
      )}

      {/* footer de navegação */}
      <div className="mt-6 flex items-center justify-between">
        <button
          onClick={() => (step > 0 ? setStep(step - 1) : router.push("/instances"))}
          className={BTN_DEFAULT}
        >
          <ChevronLeft size={13} /> {step > 0 ? "Voltar" : "Cancelar"}
        </button>
        {step < 2 ? (
          <button
            onClick={() => setStep(step + 1)}
            disabled={!canNext}
            className={cn(BTN_PRIMARY, !canNext && "cursor-not-allowed opacity-50")}
          >
            Continuar <ChevronRight size={13} />
          </button>
        ) : (
          <button onClick={handleCreate} className={BTN_PRIMARY}>
            <Zap size={14} /> Criar instância
          </button>
        )}
      </div>
    </div>
  );
}

function Review({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-md bg-bg-2 p-4">
      <div className="text-[11px] font-medium uppercase tracking-wide text-fg-3">{label}</div>
      <div className={cn("mt-1 text-[15px] font-semibold", mono && "font-mono")}>{value}</div>
    </div>
  );
}
