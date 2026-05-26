"use client";
import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { InstanceCreate } from "@/lib/types";

interface CreateInstanceDialogProps {
  onCreate: (data: InstanceCreate) => Promise<void>;
}

export function CreateInstanceDialog({ onCreate }: CreateInstanceDialogProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [engineVersion, setEngineVersion] = useState<"14" | "15" | "16" | "17">("16");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await onCreate({ name, engine_version: engineVersion });
      setName("");
      setEngineVersion("16");
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create instance");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button />}>
        <Button>New Instance</Button>
      </DialogTrigger>
      <DialogContent className="bg-zinc-900 border-zinc-800">
        <DialogHeader>
          <DialogTitle className="text-zinc-100">New Instance</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 mt-2">
          <div className="space-y-1">
            <label htmlFor="name" className="text-sm text-zinc-400">
              Name
            </label>
            <input
              id="name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              placeholder="client-prod"
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-zinc-500"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="engine" className="text-sm text-zinc-400">
              PostgreSQL version
            </label>
            <select
              id="engine"
              value={engineVersion}
              onChange={(e) =>
                setEngineVersion(e.target.value as "14" | "15" | "16" | "17")
              }
              className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-500"
            >
              <option value="17">PostgreSQL 17</option>
              <option value="16">PostgreSQL 16</option>
              <option value="15">PostgreSQL 15</option>
              <option value="14">PostgreSQL 14</option>
            </select>
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              className="text-zinc-400 hover:text-zinc-100"
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}