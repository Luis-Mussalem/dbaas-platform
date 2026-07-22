"use client";

import { useTranslations } from "next-intl";
import { Activity, Database, Info, Sparkles } from "lucide-react";

// Página estática "Sobre esta demo": a divulgação completa de que a frota é
// gerada de propósito para a plataforma poder ser explorada por inteiro. Não faz
// chamadas de API nem tem controles — é documentação na tela. A faixa fina do
// topo (DemoNotice) aponta para cá.
export default function AboutDemoPage() {
  const t = useTranslations("AboutDemo");

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <header>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Info size={20} className="text-info" />
          {t("title")}
        </h1>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          {t("subtitle")}
        </p>
      </header>

      <div className="grid gap-3 md:grid-cols-2">
        <Section icon={<Database size={15} className="text-ok" />} title={t("real.title")}>
          {t("real.body")}
        </Section>
        <Section icon={<Activity size={15} className="text-info" />} title={t("generated.title")}>
          {t("generated.body")}
        </Section>
      </div>

      <Section icon={<Sparkles size={15} className="text-brand" />} title={t("howItWorks.title")}>
        {t("howItWorks.body")}
      </Section>

      <Section icon={<Info size={15} className="text-muted-foreground" />} title={t("decision.title")}>
        {t("decision.body")}
      </Section>
    </div>
  );
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-surface p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        {icon}
        {title}
      </h2>
      <p className="mt-1.5 whitespace-pre-line text-[13px] leading-relaxed text-muted-foreground">
        {children}
      </p>
    </section>
  );
}
