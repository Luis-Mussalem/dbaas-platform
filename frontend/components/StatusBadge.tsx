"use client";

import { useTranslations } from "next-intl";
import type { InstanceStatus } from "@/lib/types";

// The design's colors by status (ok/info/warn/danger semantics from globals.css).
// The labels live in the messages: Status.* (raw technical status) and Health.*
// (product vocabulary) — same keys, different wording per locale.
const STATUS_CLS: Record<InstanceStatus, string> = {
  running: "text-ok border-ok/25 bg-ok/10",
  stopped: "text-fg-3 border-border bg-bg-2",
  pending: "text-info border-info/25 bg-info/10",
  provisioning: "text-info border-info/25 bg-info/10",
  deleting: "text-warn border-warn/25 bg-warn/10",
  deleted: "text-fg-3 border-border bg-bg-2",
  failed: "text-danger border-danger/25 bg-danger/10",
};

const BADGE =
  "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium";

export function StatusBadge({ status }: { status: InstanceStatus }) {
  const t = useTranslations("Status");
  const cls = STATUS_CLS[status] ?? STATUS_CLS.stopped;
  return (
    <span className={`${BADGE} ${cls}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {t(status)}
    </span>
  );
}

// HEALTH badge (Healthy / Paused / Failed...), derived from the technical status.
// Unlike StatusBadge, which shows the raw status. Used in the Dashboard's cards
// for a more "product" reading.
//
// Honest note: "Degraded" (running but unhealthy) would require a health check per
// card, which we don't yet do in the Dashboard — that's why we don't invent that state;
// we only derive it from the already-known status. Hence Health.* reusing the status keys.
export function HealthBadge({ status }: { status: InstanceStatus }) {
  const t = useTranslations("Health");
  const cls = STATUS_CLS[status] ?? STATUS_CLS.stopped;
  return (
    <span className={`${BADGE} ${cls}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {t(status)}
    </span>
  );
}
