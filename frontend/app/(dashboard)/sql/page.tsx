"use client";

import { type KeyboardEvent, useMemo, useRef, useState } from "react";
import { Loader2, Play, Workflow } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useInstances } from "@/hooks/use-instances";
import { runQuery, explainQuery } from "@/lib/api";
import type { QueryResult } from "@/lib/types";
import { EmptyState } from "@/components/EmptyState";
import { SchemaBrowser } from "@/components/sql/SchemaBrowser";
import { ResultsTable } from "@/components/sql/ResultsTable";
import { QueryHistory } from "@/components/sql/QueryHistory";

// ─── Histórico (localStorage, por empresa + instância) ──────────────────────
// Mantido fora do componente: são funções puras de I/O, não dependem de estado.
// O escopo de empresa evita que o histórico de um tenant apareça para outro no
// mesmo navegador (troca de workspace do superuser ou de conta).
const HISTORY_LIMIT = 15;
const historyKey = (companyScope: string, instanceId: string) =>
  `sql_history:${companyScope}:${instanceId}`;

function loadHistory(companyScope: string, instanceId: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(historyKey(companyScope, instanceId));
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveHistory(companyScope: string, instanceId: string, items: string[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(historyKey(companyScope, instanceId), JSON.stringify(items));
}

export default function SqlPage() {
  const { user } = useAuth();
  const { instances, isLoading, error: instancesError } = useInstances();

  // Empresa ativa: a do WorkspaceSwitcher (superuser) ou a do próprio usuário.
  // Trocar de workspace recarrega a página, então ler uma vez por render basta.
  const companyScope =
    (typeof window !== "undefined" ? localStorage.getItem("active_company_id") : null) ??
    user?.company_id ??
    "all";

  // Só instâncias RUNNING aceitam query (o backend devolve 409 para as demais).
  // useMemo estabiliza a referência do array para os efeitos abaixo.
  const runningInstances = useMemo(
    () => instances.filter((i) => i.status === "running"),
    [instances]
  );

  // `selectedId` guarda a escolha EXPLÍCITA do usuário no seletor; pode ficar
  // inválida (instância parou/saiu da lista). A seleção efetiva é derivada no
  // render — sem effect — caindo para a primeira RUNNING quando a escolha não vale.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [plan, setPlan] = useState<unknown[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<string[]>([]);

  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const effectiveId =
    selectedId && runningInstances.some((i) => i.id === selectedId)
      ? selectedId
      : runningInstances[0]?.id ?? null;

  const selectedInstance = useMemo(
    () => instances.find((i) => i.id === effectiveId) ?? null,
    [instances, effectiveId]
  );

  // Reset ao trocar de instância efetiva: carrega o histórico dela e zera a saída.
  // Padrão "ajustar estado durante o render" (react.dev) em vez de um effect —
  // evita flash e o set-state-in-effect. `undefined` força o load no 1º render.
  const [prevId, setPrevId] = useState<string | null | undefined>(undefined);
  if (prevId !== effectiveId) {
    setPrevId(effectiveId);
    setHistory(effectiveId ? loadHistory(companyScope, effectiveId) : []);
    setResult(null);
    setPlan(null);
    setError(null);
  }

  function rememberQuery(raw: string) {
    if (!effectiveId) return;
    const trimmed = raw.trim();
    setHistory((prev) => {
      const next = [trimmed, ...prev.filter((q) => q !== trimmed)].slice(0, HISTORY_LIMIT);
      saveHistory(companyScope, effectiveId, next);
      return next;
    });
  }

  function clearHistory() {
    if (!effectiveId) return;
    saveHistory(companyScope, effectiveId, []);
    setHistory([]);
  }

  function insertTable(table: string) {
    setQuery((cur) => (cur.trim() ? `${cur} ${table}` : `SELECT * FROM ${table} LIMIT 100`));
    textareaRef.current?.focus();
  }

  async function run() {
    if (!effectiveId || !query.trim() || running) return;
    setRunning(true);
    setError(null);
    setPlan(null);
    try {
      const r = await runQuery(effectiveId, query.trim());
      setResult(r);
      rememberQuery(query);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao executar a query");
      setResult(null);
    } finally {
      setRunning(false);
    }
  }

  async function explain() {
    if (!effectiveId || !query.trim() || running) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await explainQuery(effectiveId, query.trim());
      setPlan(r.plan);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao gerar o plano");
      setPlan(null);
    } finally {
      setRunning(false);
    }
  }

  // Ctrl/Cmd + Enter executa — atalho clássico de consoles SQL.
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      run();
    }
  }

  if (isLoading) return <p className="text-sm text-fg-3">Carregando…</p>;
  if (instancesError) return <p className="text-sm text-danger">{instancesError}</p>;

  const canSubmit = !!effectiveId && !!query.trim() && !running;

  return (
    <div className="flex flex-col gap-4">
      {/* Cabeçalho + seletor de instância */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Console SQL</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Execute consultas <span className="font-mono">SELECT</span> read-only nos bancos gerenciados.
          </p>
        </div>
        {runningInstances.length > 0 && (
          <select
            value={effectiveId ?? ""}
            onChange={(e) => setSelectedId(e.target.value)}
            className="h-9 rounded-md border border-border bg-surface px-3 text-sm text-foreground outline-none"
          >
            {runningInstances.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {runningInstances.length === 0 ? (
        <EmptyState
          title="Nenhuma instância em execução"
          subtitle="Inicie uma instância para abrir o console SQL."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
          {/* Navegador de tabelas (clicável → insere no editor) */}
          <aside className="order-2 lg:order-1">
            {selectedInstance && (
              <SchemaBrowser
                key={selectedInstance.id}
                instance={selectedInstance}
                onPickTable={insertTable}
              />
            )}
          </aside>

          {/* Editor + ações + saída */}
          <section className="order-1 flex flex-col gap-3 lg:order-2">
            <div className="overflow-hidden rounded-xl border border-border bg-surface">
              <textarea
                ref={textareaRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKeyDown}
                rows={6}
                spellCheck={false}
                placeholder="SELECT * FROM ..."
                className="w-full resize-y bg-transparent px-4 py-3 font-mono text-sm text-foreground outline-none placeholder:text-fg-3"
              />
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2">
                <span className="text-[11px] text-fg-3">
                  Somente SELECT · <span className="font-mono">Ctrl/Cmd + Enter</span> executa
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={explain}
                    disabled={!canSubmit}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-[13px] text-fg-2 transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-50"
                  >
                    <Workflow size={14} />
                    Plano
                  </button>
                  <button
                    onClick={run}
                    disabled={!canSubmit}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground transition hover:brightness-110 disabled:opacity-50"
                  >
                    {running ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Play size={14} />
                    )}
                    Executar
                  </button>
                </div>
              </div>
            </div>

            {/* Painel de erro: 422 (query barrada pelo guard) ou 400 (erro do Postgres) */}
            {error && (
              <div className="whitespace-pre-wrap wrap-break-word rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
                {error}
              </div>
            )}

            {plan && (
              <div className="overflow-hidden rounded-xl border border-border bg-surface">
                <div className="flex items-center justify-between border-b border-border px-4 py-3">
                  <h2 className="text-sm font-semibold">Plano de execução</h2>
                  <span className="text-xs text-fg-3">EXPLAIN ANALYZE</span>
                </div>
                <pre className="overflow-x-auto px-4 py-3 font-mono text-xs text-fg-2">
                  {JSON.stringify(plan, null, 2)}
                </pre>
              </div>
            )}

            {result && <ResultsTable result={result} />}

            <QueryHistory items={history} onSelect={setQuery} onClear={clearHistory} />
          </section>
        </div>
      )}
    </div>
  );
}
