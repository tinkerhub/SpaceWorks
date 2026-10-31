import { useLayoutEffect, useRef } from "react";
import { getSessionGeneration } from "../../lib/apiSession";

type Context = { scope: unknown; epoch: number };
export type AuthAction = { context: Context; lifetime: symbol; sequence: number; epoch: number };

// Publication belongs to one mounted lifetime, scope visit, session and action sequence.
// Context identity changes even for A → B → A; token installation adopts only our own epoch.
export function useAuthActionOwner(scope: unknown) {
  const contextRef = useRef<Context>({ scope, epoch: getSessionGeneration() });
  const lifetime = useRef<symbol | null>(null);
  const sequence = useRef(0);
  const active = useRef<AuthAction | null>(null);
  if (contextRef.current.scope !== scope || contextRef.current.epoch !== getSessionGeneration()) {
    contextRef.current = { scope, epoch: getSessionGeneration() };
    active.current = null;
    sequence.current += 1;
  }
  const context = contextRef.current;
  const intent = sequence.current;
  useLayoutEffect(() => {
    const mounted = Symbol();
    lifetime.current = mounted;
    return () => {
      if (lifetime.current === mounted) {
        lifetime.current = null;
        active.current = null;
      }
    };
  }, []);
  function isContextCurrent(candidate = context) {
    return lifetime.current !== null && contextRef.current === candidate && candidate.epoch === getSessionGeneration();
  }
  function isIntentCurrent() { return isContextCurrent() && sequence.current === intent; }
  function capture(): AuthAction | null {
    return isContextCurrent() && lifetime.current ? {
      context, lifetime: lifetime.current, sequence: sequence.current, epoch: context.epoch,
    } : null;
  }
  function isLive(action: AuthAction | null): action is AuthAction {
    return Boolean(action && isContextCurrent(action.context) && lifetime.current === action.lifetime &&
      action.epoch === getSessionGeneration());
  }
  function isCurrent(action: AuthAction | null): action is AuthAction {
    return isLive(action) && sequence.current === action.sequence;
  }
  function isPending() { return isCurrent(active.current); }
  function begin() {
    if (!isContextCurrent() || (active.current && isCurrent(active.current))) return null;
    sequence.current += 1;
    const action = capture();
    active.current = action;
    return action;
  }
  function finish(action: AuthAction) {
    // Cleanup only: an external epoch may change before settlement. This releases only
    // this exact mounted action; it never grants permission to publish its result.
    if (lifetime.current !== action.lifetime || contextRef.current !== action.context ||
      sequence.current !== action.sequence || active.current !== action) return false;
    active.current = null;
    return true;
  }
  function cancel() {
    sequence.current += 1;
    active.current = null;
  }
  function install(action: AuthAction, access: string, publish: (access: string) => void) {
    if (!isCurrent(action)) return false;
    publish(access);
    action.epoch = getSessionGeneration();
    action.context.epoch = action.epoch;
    return true;
  }
  return { context, capture, begin, isCurrent, isContextCurrent, isIntentCurrent, isLive, isPending, finish, cancel, install };
}
