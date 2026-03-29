"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Backtests" },
  { href: "/optimization", label: "Optimization" },
  { href: "/detector-optimization", label: "Detectors" },
  { href: "/compare", label: "Compare" },
  { href: "/data", label: "Data" },
];

function useServerStatus() {
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    async function check() {
      try {
        const res = await fetch("http://localhost:9000/system/general-info", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        setConnected(res.ok || res.status === 401);
      } catch {
        setConnected(false);
      }
    }
    check();
    const interval = setInterval(check, 10000);
    return () => clearInterval(interval);
  }, []);

  return connected;
}

export function Nav() {
  const pathname = usePathname();
  const connected = useServerStatus();

  return (
    <nav className="flex items-center gap-6 px-6 py-3 border-b border-[var(--border)] bg-[var(--bg-surface)]">
      <span className="font-bold text-[15px] text-[var(--blue)] tracking-tight">
        OpenQuant
      </span>
      <div className="flex gap-1">
        {links.map((link) => {
          const isActive =
            link.href === "/"
              ? pathname === "/" || pathname.startsWith("/backtests")
              : pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`px-3 py-1.5 rounded-md text-[13px] transition-colors ${
                isActive
                  ? "bg-[var(--border)] text-[var(--text-primary)]"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
            >
              {link.label}
            </Link>
          );
        })}
      </div>
      <div className="ml-auto flex items-center gap-2 text-[var(--text-secondary)] text-xs">
        <span className={`w-2 h-2 rounded-full ${connected ? "bg-[var(--green)]" : "bg-[var(--red)]"}`} />
        {connected ? "Server connected" : "Server disconnected"}
      </div>
    </nav>
  );
}
