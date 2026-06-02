import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";

// Layout aninhado: tudo dentro de app/(dashboard)/ é renderizado como {children}
// aqui dentro, ganhando Sidebar + Topbar. O "(dashboard)" não aparece na URL.
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="grid h-screen grid-cols-[232px_1fr] overflow-hidden bg-background text-foreground">
      <Sidebar />
      <div className="flex min-w-0 flex-col overflow-hidden">
        <Topbar />
        <div className="flex-1 overflow-y-auto p-6 md:px-7">{children}</div>
      </div>
    </div>
  );
}
