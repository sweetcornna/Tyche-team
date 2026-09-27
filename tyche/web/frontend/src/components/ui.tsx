import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as Menu from "@radix-ui/react-dropdown-menu";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import clsx from "clsx";
import { Loader2, X } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type ComponentPropsWithoutRef, type ReactNode } from "react";
import type { RunStatus } from "../api/types";

/* ---------- Buttons ---------- */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "outline";

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: "sm" | "md"; loading?: boolean; icon?: ReactNode }
>(function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }, ref) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-full font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-9 px-4 text-sm",
        {
          "bg-inverse text-on-inverse hover:bg-inverse/85": variant === "primary",
          "bg-subtle/[0.06] text-fg hover:bg-subtle/10": variant === "secondary",
          "text-fg hover:bg-subtle/[0.06]": variant === "ghost",
          "bg-bad text-white hover:bg-bad/90": variant === "danger",
          "border border-line/15 text-fg hover:bg-subtle/[0.04]": variant === "outline",
        },
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
});

export const IconButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string; tooltip?: boolean; size?: "sm" | "md"; active?: boolean; shortcut?: string }
>(function IconButton({ label, tooltip = true, size = "md", active, shortcut, className, children, ...rest }, ref) {
  const button = (
    <button
      ref={ref}
      aria-label={label}
      className={clsx(
        "inline-flex shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-subtle/[0.06] hover:text-fg disabled:pointer-events-none disabled:opacity-40",
        size === "sm" ? "h-8 w-8" : "h-9 w-9",
        active && "bg-subtle/[0.07] text-fg",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
  if (!tooltip) return button;
  return (
    <Tooltip content={label} shortcut={shortcut}>
      {button}
    </Tooltip>
  );
});

/* ---------- Tooltip ---------- */

export function Tooltip({
  content,
  shortcut,
  side = "bottom",
  children,
}: {
  content: ReactNode;
  shortcut?: string;
  side?: "top" | "bottom" | "left" | "right";
  children: ReactNode;
}) {
  return (
    <TooltipPrimitive.Root delayDuration={350}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className="z-[90] flex animate-fade-in items-center gap-2 rounded-lg bg-[#0d0d0d] px-2.5 py-1.5 text-xs font-medium text-white shadow-lg dark:bg-[#f4f4f4] dark:text-[#0d0d0d]"
        >
          {content}
          {shortcut && <span className="text-white/55 dark:text-black/45">{shortcut}</span>}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export const TooltipProvider = TooltipPrimitive.Provider;

/* ---------- Dropdown menu ---------- */

export const MenuRoot = Menu.Root;
export const MenuTrigger = Menu.Trigger;

export function MenuContent({
  children,
  className,
  align = "start",
  side = "bottom",
  sideOffset = 6,
  ...rest
}: ComponentPropsWithoutRef<typeof Menu.Content>) {
  return (
    <Menu.Portal>
      <Menu.Content
        align={align}
        side={side}
        sideOffset={sideOffset}
        collisionPadding={10}
        className={clsx(
          "z-[80] min-w-[200px] animate-pop-in rounded-2xl bg-elevated p-1.5 text-sm text-fg shadow-menu outline-none",
          className,
        )}
        {...rest}
      >
        {children}
      </Menu.Content>
    </Menu.Portal>
  );
}

export function MenuItem({
  icon,
  children,
  danger,
  hint,
  className,
  ...rest
}: ComponentPropsWithoutRef<typeof Menu.Item> & { icon?: ReactNode; danger?: boolean; hint?: ReactNode }) {
  return (
    <Menu.Item
      className={clsx(
        "flex min-h-9 cursor-pointer select-none items-center gap-2.5 rounded-lg px-2.5 py-1.5 outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-subtle/[0.06] data-[disabled]:opacity-45",
        danger ? "text-bad" : "text-fg",
        className,
      )}
      {...rest}
    >
      {icon && <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center [&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</span>}
      <span className="min-w-0 flex-1">{children}</span>
      {hint && <span className="ml-3 shrink-0 text-xs text-faint">{hint}</span>}
    </Menu.Item>
  );
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <Menu.Label className="px-2.5 pb-1 pt-2 text-xs font-medium text-faint">{children}</Menu.Label>;
}

export function MenuSeparator() {
  return <Menu.Separator className="mx-1 my-1.5 h-px bg-line/10" />;
}

export const MenuSub = Menu.Sub;
export function MenuSubTrigger({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <Menu.SubTrigger className="flex min-h-9 cursor-pointer select-none items-center gap-2.5 rounded-lg px-2.5 py-1.5 outline-none data-[highlighted]:bg-subtle/[0.06] data-[state=open]:bg-subtle/[0.06]">
      {icon && <span className="flex h-[18px] w-[18px] items-center justify-center [&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</span>}
      <span className="flex-1">{children}</span>
      <span className="text-faint">›</span>
    </Menu.SubTrigger>
  );
}
export function MenuSubContent({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <Menu.Portal>
      <Menu.SubContent
        sideOffset={8}
        collisionPadding={10}
        className={clsx("z-[81] min-w-[200px] animate-pop-in rounded-2xl bg-elevated p-1.5 text-sm shadow-menu", className)}
      >
        {children}
      </Menu.SubContent>
    </Menu.Portal>
  );
}

/* ---------- Dialog ---------- */

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
  hideClose,
  wide,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  hideClose?: boolean;
  wide?: boolean;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-[70] animate-fade-in bg-black/40 dark:bg-black/60" />
        <DialogPrimitive.Content
          className={clsx(
            "fixed left-1/2 top-1/2 z-[71] flex max-h-[min(88vh,820px)] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 animate-pop-in flex-col overflow-hidden rounded-3xl bg-elevated text-fg shadow-menu outline-none",
            wide ? "max-w-[880px]" : "max-w-[480px]",
            className,
          )}
          aria-describedby={description ? undefined : undefined}
        >
          {(title || !hideClose) && (
            <div className="flex shrink-0 items-center justify-between gap-4 px-6 pb-2 pt-5">
              {title ? (
                <DialogPrimitive.Title className="text-lg font-semibold">{title}</DialogPrimitive.Title>
              ) : (
                <DialogPrimitive.Title className="sr-only">Dialog</DialogPrimitive.Title>
              )}
              {!hideClose && (
                <DialogPrimitive.Close asChild>
                  <IconButton label="Close" tooltip={false} size="sm" className="-mr-2">
                    <X className="h-5 w-5" />
                  </IconButton>
                </DialogPrimitive.Close>
              )}
            </div>
          )}
          {description && (
            <DialogPrimitive.Description className="px-6 text-sm text-muted">{description}</DialogPrimitive.Description>
          )}
          {!description && <DialogPrimitive.Description className="sr-only">{typeof title === "string" ? title : ""}</DialogPrimitive.Description>}
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/* ---------- Small pieces ---------- */

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("animate-spin text-faint", className ?? "h-4 w-4")} />;
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-line/15 bg-subtle/[0.03] px-1.5 font-sans text-[11px] font-medium text-muted">
      {children}
    </kbd>
  );
}

export function StatusDot({ status, className }: { status: RunStatus; className?: string }) {
  if (status === "running") {
    return (
      <span className={clsx("relative flex h-2 w-2 shrink-0", className)}>
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-info/50" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-info" />
      </span>
    );
  }
  return (
    <span
      className={clsx(
        "inline-flex h-2 w-2 shrink-0 rounded-full",
        {
          "bg-ok": status === "done",
          "bg-bad": status === "failed",
          "bg-warn": status === "stopped" || status === "paused",
          "bg-faint/50": status === "pending",
        },
        className,
      )}
    />
  );
}

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "bad" | "info";
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex h-[22px] items-center gap-1 whitespace-nowrap rounded-full px-2 text-xs font-medium",
        {
          "bg-subtle/[0.06] text-muted": tone === "neutral",
          "bg-ok/10 text-ok": tone === "ok",
          "bg-warn/12 text-warn": tone === "warn",
          "bg-bad/10 text-bad": tone === "bad",
          "bg-info/10 text-info": tone === "info",
        },
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  className,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div className={clsx("inline-flex rounded-full bg-subtle/[0.06] p-0.5", className)} role="radiogroup">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "h-8 rounded-full px-3.5 text-[13px] font-medium transition-colors",
            o.value === value ? "bg-main text-fg shadow-card" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative inline-flex h-6 w-10 shrink-0 items-center rounded-full transition-colors",
        checked ? "bg-inverse" : "bg-subtle/15",
      )}
    >
      <span
        className={clsx(
          "inline-block h-5 w-5 rounded-full bg-main shadow transition-transform dark:bg-[#0d0d0d]",
          checked ? "translate-x-[18px]" : "translate-x-0.5",
          !checked && "dark:bg-[#ececec]",
        )}
      />
    </button>
  );
}

export const TextField = forwardRef<HTMLInputElement, ComponentPropsWithoutRef<"input"> & { invalid?: boolean }>(
  function TextField({ className, invalid, ...rest }, ref) {
    return (
      <input
        ref={ref}
        className={clsx(
          "h-10 w-full rounded-xl border bg-transparent px-3 text-sm text-fg outline-none transition-colors placeholder:text-faint focus:border-line/30",
          invalid ? "border-bad/60" : "border-line/15",
          className,
        )}
        {...rest}
      />
    );
  },
);

export function Field({ label, hint, children }: { label: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-fg">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-faint">{hint}</span>}
    </label>
  );
}

export function EmptyState({ icon, title, body, action }: { icon?: ReactNode; title: ReactNode; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      {icon && <div className="mb-3 text-faint [&>svg]:h-8 [&>svg]:w-8">{icon}</div>}
      <div className="text-[15px] font-medium">{title}</div>
      {body && <div className="mt-1 max-w-sm text-sm text-muted">{body}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse-soft rounded-lg bg-subtle/[0.06]", className)} />;
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2 mt-6 flex items-center justify-between first:mt-0">
      <h3 className="text-[13px] font-semibold text-fg">{children}</h3>
      {right}
    </div>
  );
}
