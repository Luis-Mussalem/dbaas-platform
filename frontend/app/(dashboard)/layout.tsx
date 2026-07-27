import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { CommandPalette } from "@/components/CommandPalette";
import { DemoNotice } from "@/components/DemoNotice";

// Nested layout: everything inside app/(dashboard)/ is rendered as {children}
// in here, gaining Sidebar + Topbar. The "(dashboard)" doesn't show up in the URL.
export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="grid h-screen grid-cols-[280px_1fr] overflow-hidden bg-background text-foreground">
      <Sidebar />
      <div className="flex min-w-0 flex-col overflow-hidden">
        {/* Above the Topbar on purpose: the notice that the fleet is generated for
            demo purposes applies to everything below it, on any route. */}
        <DemoNotice />
        <Topbar />
        <div className="flex-1 overflow-y-auto p-6 md:px-7">{children}</div>
      </div>
      <CommandPalette />
    </div>
  );
}
