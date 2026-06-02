import * as React from "react";

import { cn } from "@/lib/utils";

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-32 w-full rounded-2xl border border-neutral-300 bg-white px-3 py-3 text-sm text-neutral-950 outline-none focus:border-neutral-900",
        className,
      )}
      {...props}
    />
  );
}
