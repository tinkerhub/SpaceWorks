import { vi } from "vitest";

/** Live transport for useSyncExternalStore: subscriptions receive real change Events. */
export function installLiveMatchMedia(initialWidth = 800) {
  let width = initialWidth;
  const lists = new Map<string, MediaQueryList>();
  const matches = (query: string) => {
    const bounds = [...query.matchAll(/(min|max)-width:\s*([\d.]+)(px|rem)/g)];
    return bounds.length > 0 && bounds.every(([, bound, raw, unit]) => {
      const limit = Number(raw) * (unit === "rem" ? 16 : 1);
      return bound === "min" ? width >= limit : width <= limit;
    });
  };
  vi.stubGlobal("matchMedia", (query: string) => {
    let list = lists.get(query);
    if (!list) {
      const target = new EventTarget();
      list = Object.assign(target, {
        media: query, get matches() { return matches(query); }, onchange: null,
        addListener(callback: EventListener) { target.addEventListener("change", callback); },
        removeListener(callback: EventListener) { target.removeEventListener("change", callback); },
      }) as MediaQueryList;
      // Object.assign evaluates getters; keep matches live when useSyncExternalStore reads it.
      Object.defineProperty(list, "matches", { get: () => matches(query) });
      lists.set(query, list);
    }
    return list;
  });
  return {
    resize(nextWidth: number) {
      const before = new Map([...lists].map(([query, list]) => [query, list.matches]));
      width = nextWidth;
      for (const [query, list] of lists) {
        if (before.get(query) === list.matches) continue;
        const event = new Event("change");
        Object.defineProperties(event, { matches: { value: list.matches }, media: { value: query } });
        list.dispatchEvent(event);
        list.onchange?.call(list, event as MediaQueryListEvent);
      }
    },
  };
}
