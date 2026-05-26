"use client";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { InstanceCard } from "@/components/InstanceCard";
import { useInstances } from "@/hooks/use-instances";
import { CreateInstanceDialog } from "@/components/CreateInstanceDialog";

export default function HomePage() {
  const { logout } = useAuth();
  const { instances, isLoading, error, create } = useInstances();
  const router = useRouter();

  if (isLoading) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-zinc-500 text-sm">Loading...</p>
      </main>
    );
  }
  if (error) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-red-400 text-sm">{error}</p>
      </main>
    );
  }
  return (
    <main className="flex flex-1 flex-col p-8 gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-zinc-100">Instances</h1>
        <div className="flex items-center gap-4">
          <CreateInstanceDialog onCreate={create} />
          <button
            onClick={logout}
            className="text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Sign out
          </button>
        </div>
      </div>
      {instances.length === 0 ? (
        <p className="text-zinc-500 text-sm">No instances yet.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {instances.map((instance) => (
            <InstanceCard
              key={instance.id}
              instance={instance}
              onClick={() => router.push(`/instances/${instance.id}`)}
            />
          ))}
        </div>
      )}
    </main>
  );
}