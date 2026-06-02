import * as React from "react";

import { cn } from "@/lib/utils";

export function Input({
  className,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-2xl border border-neutral-300 bg-white px-3 text-sm text-neutral-950 outline-none focus:border-neutral-900",
        className,
      )}
      {...props}
    />
  );
}
