import { Component, type ErrorInfo, type ReactNode } from "react";
import { RotateCcw, TriangleAlert } from "lucide-react";

import { Button } from "./ui";

type Props = { children: ReactNode };
type State = { error: Error | null };

/**
 * Last line of defence for a render crash anywhere in the app. Staff panels have their own
 * narrower boundary; this one catches what escapes it (or never had one) and offers a
 * retry instead of a blank page.
 */
export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Space Works failed to render", error, info);
  }

  private retry = () => this.setState({ error: null });

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main className="desk-shell grid min-h-dvh place-items-center px-4 py-10">
        <section role="alert" className="flex w-full max-w-[480px] flex-col items-start gap-4 rounded-2xl border border-line bg-canvas p-6 sm:p-8">
          <span aria-hidden="true" className="inline-flex size-11 items-center justify-center rounded-full bg-warning-bg text-warning-fg">
            <TriangleAlert className="size-5" />
          </span>
          <div className="flex flex-col gap-1.5">
            <h1 className="text-h3 text-ink">Something went wrong</h1>
            <p className="text-body-ui text-ink-secondary">
              This page hit an unexpected problem and could not be shown. Try again, or reload the page if it keeps happening.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" startIcon={<RotateCcw />} onClick={this.retry}>
              Try again
            </Button>
            <Button variant="secondary" onClick={() => window.location.reload()}>
              Reload page
            </Button>
          </div>
        </section>
      </main>
    );
  }
}
