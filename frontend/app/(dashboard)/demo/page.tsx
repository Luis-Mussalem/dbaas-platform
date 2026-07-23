"use client";

import { useTranslations } from "next-intl";
import {
  Activity,
  Archive,
  BellRing,
  Database,
  Gauge,
  Info,
  Languages,
  Network,
  Server,
  Sparkles,
} from "lucide-react";

// Página estática "Sobre esta demo": a divulgação completa de que a frota é
// gerada de propósito para a plataforma poder ser explorada por inteiro, além de
// um guia de exploração e a stack — serve de porta de entrada para recrutadores.
// Não faz chamadas de API nem tem controles; é documentação na tela. A faixa do
// topo (DemoNotice) aponta para cá.

// Nomes de tecnologia são substantivos próprios, não strings de UI — ficam fora
// do i18n de propósito.
const STACK = [
  "FastAPI",
  "SQLAlchemy",
  "PostgreSQL 16",
  "Alembic",
  "Pytest",
  "Next.js 16",
  "React 19",
  "TypeScript",
  "Tailwind v4",
  "shadcn/ui",
  "Docker Compose",
  "Ruff",
];

export default function AboutDemoPage() {
  const t = useTranslations("AboutDemo");

  const exploreItems = [
    { key: "fleet", icon: <Gauge size={16} className="text-brand" /> },
    { key: "instance", icon: <Server size={16} className="text-info" /> },
    { key: "backups", icon: <Archive size={16} className="text-ok" /> },
    { key: "alerts", icon: <BellRing size={16} className="text-warn" /> },
    { key: "replication", icon: <Network size={16} className="text-info" /> },
    { key: "tenancy", icon: <Languages size={16} className="text-brand" /> },
  ] as const;

  return (
    <div className="flex flex-col gap-8">
      <header className="max-w-4xl">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-info/25 bg-info/10 px-2.5 py-1 text-xs font-medium text-info">
          <Info size={13} />
          {t("title")}
        </span>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">
          {t("subtitle")}
        </p>
      </header>

      <section className="flex flex-col gap-4">
        <SectionHeading title={t("explore.title")} subtitle={t("explore.subtitle")} />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {exploreItems.map(({ key, icon }) => (
            <Card
              key={key}
              icon={icon}
              title={t(`explore.items.${key}.title`)}
            >
              {t(`explore.items.${key}.body`)}
            </Card>
          ))}
        </div>
      </section>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card icon={<Database size={16} className="text-ok" />} title={t("real.title")}>
          {t("real.body")}
        </Card>
        <Card icon={<Activity size={16} className="text-info" />} title={t("generated.title")}>
          {t("generated.body")}
        </Card>
        <Card icon={<Sparkles size={16} className="text-brand" />} title={t("howItWorks.title")}>
          {t("howItWorks.body")}
        </Card>
        <Card icon={<Info size={16} className="text-muted-foreground" />} title={t("decision.title")}>
          {t("decision.body")}
        </Card>
      </div>

      <section className="rounded-xl border border-border bg-surface p-5">
        <SectionHeading title={t("stack.title")} subtitle={t("stack.subtitle")} />
        <ul className="mt-4 flex flex-wrap gap-2">
          {STACK.map((tech) => (
            <li
              key={tech}
              className="rounded-md border border-border bg-surface-2 px-2.5 py-1 text-[13px] font-medium text-fg-2"
            >
              {tech}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function SectionHeading({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div>
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>
    </div>
  );
}

function Card({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col rounded-xl border border-border bg-surface p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-surface-2">
          {icon}
        </span>
        {title}
      </h3>
      <p className="mt-2 whitespace-pre-line text-[13px] leading-relaxed text-muted-foreground">
        {children}
      </p>
    </section>
  );
}
