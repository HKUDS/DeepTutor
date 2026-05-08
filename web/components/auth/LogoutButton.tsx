"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { AUTH_ENABLED, logout } from "@/lib/auth";

interface LogoutButtonProps {
  collapsed?: boolean;
}

export function LogoutButton({ collapsed = false }: LogoutButtonProps) {
  const router = useRouter();

  if (!AUTH_ENABLED) return null;

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  if (collapsed) {
    return (
      <button
        onClick={handleLogout}
        className="rounded-lg p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/50 hover:text-red-500"
        aria-label="Sign out"
        title="Sign out"
      >
        <LogOut size={16} strokeWidth={1.5} />
      </button>
    );
  }

  return (
    <button
      onClick={handleLogout}
      className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/50 hover:text-red-500"
    >
      <LogOut size={16} strokeWidth={1.5} />
      <span>Sign out</span>
    </button>
  );
}
