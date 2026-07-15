import { getTranslations } from "next-intl/server";
import { EmptyState } from "@/components/EmptyState";

export default async function HelpPage() {
  const t = await getTranslations("Help");
  return <EmptyState title={t("title")} subtitle={t("subtitle")} />;
}
