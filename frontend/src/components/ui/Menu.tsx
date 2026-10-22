import { cloneElement, forwardRef, isValidElement, type ComponentPropsWithoutRef, type ElementRef, type ReactElement, type ReactNode } from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";

import { cn } from "../../lib/cn";

/* Action menu (the "⋯" button): arrow keys, typeahead, Escape returns focus to the trigger. */
export const Menu = DropdownMenuPrimitive.Root;
export const MenuTrigger = DropdownMenuPrimitive.Trigger;
export const MenuGroup = DropdownMenuPrimitive.Group;

export const MenuContent = forwardRef<ElementRef<typeof DropdownMenuPrimitive.Content>, ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>>(
  function MenuContent({ className, sideOffset = 6, align = "end", ...props }, ref) {
    return (
      <DropdownMenuPrimitive.Portal>
        <DropdownMenuPrimitive.Content
          ref={ref}
          sideOffset={sideOffset}
          align={align}
          className={cn("z-[120] min-w-[200px] overflow-hidden rounded-lg border border-line bg-canvas p-1.5 text-ink shadow-float", className)}
          {...props}
        />
      </DropdownMenuPrimitive.Portal>
    );
  },
);

type MenuItemProps = ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & {
  /** Destructive items go last, in the danger colour. */
  danger?: boolean;
  icon?: ReactNode;
  description?: ReactNode;
};

export const MenuItem = forwardRef<ElementRef<typeof DropdownMenuPrimitive.Item>, MenuItemProps>(function MenuItem(
  { className, danger, icon, description, children, asChild, ...props },
  ref,
) {
  const content = (inner: ReactNode) => (
    <>
      {icon ? <span aria-hidden="true" className="inline-flex text-current">{icon}</span> : null}
      <span className="min-w-0 flex-1">
        {inner}
        {description ? <span className="block text-caption text-ink-muted">{description}</span> : null}
      </span>
    </>
  );
  // With asChild (e.g. a <Link>), Radix needs exactly one element child, so the icon and
  // label go inside that element instead of beside it.
  const slotted = asChild && isValidElement(children) ? (children as ReactElement<{ children?: ReactNode }>) : null;
  return (
    <DropdownMenuPrimitive.Item
      ref={ref}
      asChild={Boolean(slotted)}
      className={cn(
        "flex min-h-10 cursor-pointer select-none items-center gap-2.5 rounded-md px-3 py-2 text-body-ui focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus data-[disabled]:pointer-events-none data-[disabled]:text-ink-disabled data-[highlighted]:bg-emphasis [&_svg]:size-[18px] [&_svg]:shrink-0",
        danger ? "text-danger-fg" : "text-ink",
        className,
      )}
      {...props}
    >
      {slotted ? cloneElement(slotted, undefined, content(slotted.props.children)) : content(children)}
    </DropdownMenuPrimitive.Item>
  );
});

export function MenuLabel({ children }: { children: ReactNode }) {
  return <DropdownMenuPrimitive.Label className="px-3 pb-1 pt-2 text-overline text-ink-muted">{children}</DropdownMenuPrimitive.Label>;
}

export function MenuSeparator() {
  return <DropdownMenuPrimitive.Separator className="my-1.5 h-px bg-line" />;
}
