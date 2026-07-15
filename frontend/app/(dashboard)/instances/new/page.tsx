"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronLeft, ChevronRight, X, Zap, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { createInstance } from "@/lib/api";
import { cn } from "@/lib/utils";
import { BTN_PRIMARY, BTN_DEFAULT } from "@/lib/ui";
import { useToast } from "@/context/ToastProvider";
import { ENVIRONMENTS } from "@/lib/environment";
import { listRegions } from "@/lib/regions";
import type { Environment } from "@/lib/types";

// Versões disponíveis (viram a tag postgres:<v>-alpine no provisionador).
const PG_VERSIONS = ["17", "16", "15", "14"] as const;
const RECOMMENDED = "16";

const REGIONS = listRegions();

// "Planos" do design viram presets de recursos reais (cpu/memória/disco).
// `id` é a chave do i18n da descrição; `label` é nome de plano — não se traduz.
type Size = {
  id: "hobby" | "starter" | "pro" | "business";
  label: string;
  cpu: number;
  memory_mb: number;
  storage_gb: number;
};
const SIZES: Size[] = [
  { id: "hobby", label: "Hobby", cpu: 1, memory_mb: 512, storage_gb: 10 },
  { id: "starter", label: "Starter", cpu: 2, memory_mb: 2048, storage_gb: 50 },
  { id: "pro", label: "Pro", cpu: 4, memory_mb: 8192, storage_gb: 200 },
  { id: "business", label: "Business", cpu: 8, memory_mb: 16384, storage_gb: 500 },
];

const STEPS = ["identity", "size", "review"] as const;

export default function CreateInstancePage() {
  const t = useTranslations("NewInstance");
  const tc = useTranslations("Common");
  const tEnv = useTranslations("Environments");
  const router = useRouter();

  // ── estado do wizard ──
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [version, setVersion] = useState<string>(RECOMMENDED);
  const [sizeId, setSizeId] = useState("starter");
  const [environment, setEnvironment] = useState<Environment | "">("");
  const [region, setRegion] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

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
        // Campos opcionais: só enviados quando o usuário escolheu.
        ...(environment ? { environment } : {}),
        ...(region ? { region } : {}),
      });
      toast.success(t("created", { name: created.name }));
      router.push(`/instances/${created.id}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("createFailed");
      setError(msg);
      toast.error(msg);
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
        <h2 className="text-2xl font-semibold">{t("provisioning.title")}</h2>
        <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
          {t.rich("provisioning.note", {
            version,
            name,
            mono: (chunks) => <span className="font-mono text-foreground">{chunks}</span>,
          })}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl">
      {/* header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("step", { current: step + 1, total: STEPS.length })}
          </p>
        </div>
        <button onClick={() => router.push("/instances")} className={BTN_DEFAULT}>
          <X size={13} /> {tc("cancel")}
        </button>
      </div>

      {/* indicador de passos */}
      <div className="mb-7 flex items-center">
        {STEPS.map((key, i) => (
          <div key={key} className="flex flex-1 items-center gap-2">
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
              {t(`steps.${key}`)}
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
                {t("identity.nameLabel")}
              </label>
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("identity.namePlaceholder")}
                className="h-9 rounded-md border border-border-strong bg-surface px-3 text-sm outline-none focus:border-brand"
              />
              <span className="text-xs text-fg-3">{t("identity.nameHint")}</span>
            </div>

            <div className="flex flex-col gap-2">
              <label className="text-[11px] font-medium uppercase tracking-wide text-fg-3">
                {t("identity.versionLabel")}
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
                        {t("recommended")}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Ambiente (opcional) — usado para agrupar/filtrar no Painel */}
            <div className="flex flex-col gap-2">
              <label className="text-[11px] font-medium uppercase tracking-wide text-fg-3">
                {t("environment")} <span className="text-fg-faint">{t("optional")}</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {ENVIRONMENTS.map((e) => (
                  <button
                    key={e.value}
                    onClick={() => setEnvironment((cur) => (cur === e.value ? "" : e.value))}
                    className={cn(
                      "rounded-md border px-4 py-2 text-sm font-medium transition",
                      environment === e.value
                        ? "border-brand bg-brand-subtle text-brand"
                        : "border-border hover:border-border-strong"
                    )}
                  >
                    {tEnv(e.value)}
                  </button>
                ))}
              </div>
            </div>

            {/* Região (opcional) */}
            <div className="flex flex-col gap-2">
              <label className="text-[11px] font-medium uppercase tracking-wide text-fg-3">
                {t("region")} <span className="text-fg-faint">{t("optional")}</span>
              </label>
              <select
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                className="h-9 rounded-md border border-border-strong bg-surface px-3 text-sm outline-none focus:border-brand"
              >
                <option value="">{t("noRegion")}</option>
                {REGIONS.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.flag} {r.city}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}

      {/* Passo 1 — Tamanho */}
      {step === 1 && (
        <div className="rounded-xl border border-border bg-surface p-6">
          <h2 className="mb-1 text-sm font-semibold">{t("size.title")}</h2>
          <p className="mb-4 text-xs text-fg-3">{t("size.subtitle")}</p>
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
                  <div className="text-[11.5px] text-fg-3">{t(`sizes.${s.id}`)}</div>
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
          <h2 className="mb-1 text-sm font-semibold">{t("review.title")}</h2>
          <p className="mb-5 text-xs text-fg-3">{t("review.subtitle")}</p>
          <div className="grid grid-cols-2 gap-4">
            <Review label={t("review.name")} value={name || tc("none")} mono />
            <Review label={t("review.version")} value={`PostgreSQL ${version}`} />
            <Review
              label={t("review.resources")}
              value={`${size.cpu} vCPU · ${size.memory_mb / 1024} GB RAM`}
            />
            <Review label={t("review.disk")} value={`${size.storage_gb} GB`} />
            <Review
              label={t("environment")}
              value={environment ? tEnv(environment) : tc("none")}
            />
            <Review
              label={t("region")}
              value={(() => {
                const r = REGIONS.find((x) => x.code === region);
                return r ? `${r.flag} ${r.city}` : tc("none");
              })()}
            />
          </div>
          <div className="mt-5 rounded-md border border-info/25 bg-info/10 px-3 py-2.5 text-[12.5px] text-fg-2">
            {t("review.note")}
          </div>
        </div>
      )}

      {/* footer de navegação */}
      <div className="mt-6 flex items-center justify-between">
        <button
          onClick={() => (step > 0 ? setStep(step - 1) : router.push("/instances"))}
          className={BTN_DEFAULT}
        >
          <ChevronLeft size={13} /> {step > 0 ? t("back") : tc("cancel")}
        </button>
        {step < 2 ? (
          <button
            onClick={() => setStep(step + 1)}
            disabled={!canNext}
            className={cn(BTN_PRIMARY, !canNext && "cursor-not-allowed opacity-50")}
          >
            {t("next")} <ChevronRight size={13} />
          </button>
        ) : (
          <button onClick={handleCreate} className={BTN_PRIMARY}>
            <Zap size={14} /> {t("create")}
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
