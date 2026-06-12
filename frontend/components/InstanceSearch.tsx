"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { useInstances } from "@/hooks/use-instances";
import { regionInfo } from "@/lib/regions";

// Cor do pontinho de status ao lado de cada resultado.
const DOT: Record<string, string> = {
  running: "bg-ok",
  stopped: "bg-fg-3",
  failed: "bg-danger",
};

const MAX_RESULTS = 6;

// Busca rápida de instâncias: filtra por nome (client-side) e navega ao detalhe.
export function InstanceSearch() {
  const { instances } = useInstances();
  const router = useRouter();

  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0); // índice destacado (teclado)

  const inputRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  // Resultados: só recalcula quando a query ou a lista muda (useMemo).
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return instances
      .filter((i) => i.name.toLowerCase().includes(q))
      .slice(0, MAX_RESULTS);
  }, [query, instances]);

  // Atalho "/" foca a busca (ignorado se já estamos digitando em outro campo).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = document.activeElement;
      const typing = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
      if (e.key === "/" && !typing) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Fecha o dropdown ao clicar fora do componente.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function go(id: string) {
    router.push(`/instances/${id}`);
    setQuery("");
    setOpen(false);
    inputRef.current?.blur();
  }

  // Navegação por teclado dentro do campo.
  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
      return;
    }
    if (results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(results[active].id);
    }
  }

  const showDropdown = open && query.trim().length > 0;

  return (
    <div ref={boxRef} className="relative hidden md:block">
      <Search
        size={14}
        className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-3"
      />
      <input
        ref={inputRef}
        type="text"
        value={query}
        placeholder="Buscar instância…"
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        className="h-7.5 w-56 rounded-md border border-border bg-surface pl-8 pr-7 text-[13px] text-foreground placeholder:text-fg-faint transition focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
      />
      {/* Dica visual do atalho de teclado */}
      {!query && (
        <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-border bg-bg-2 px-1 text-[10px] text-fg-3">
          /
        </kbd>
      )}

      {showDropdown && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-72 overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
          {results.length === 0 ? (
            <p className="px-3 py-3 text-[13px] text-fg-3">Nenhuma instância encontrada.</p>
          ) : (
            <ul className="py-1">
              {results.map((inst, i) => {
                const region = regionInfo(inst.region);
                return (
                  <li key={inst.id}>
                    <button
                      onMouseEnter={() => setActive(i)}
                      onClick={() => go(inst.id)}
                      className={`flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors ${
                        i === active ? "bg-surface-2" : ""
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[inst.status] ?? "bg-warn"}`}
                      />
                      <span className="flex-1 truncate font-mono text-[13px] text-foreground">
                        {inst.name}
                      </span>
                      {region && (
                        <span className="shrink-0 text-[11.5px] text-fg-3">{region.city}</span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
