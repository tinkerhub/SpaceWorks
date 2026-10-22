import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button, EmptyState } from "../../components/ui";

type Props = {
  children: ReactNode;
  resetKey: string;
};

type State = {
  error: Error | null;
};

export class StaffPanelErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Staff panel render failed", error, info);
  }

  componentDidUpdate(previous: Props) {
    if (previous.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div role="alert">
        <EmptyState
          tone="error"
          title="This page couldn't be displayed"
          description="The rest of Space Works is still available. Reload this page to try again."
          action={<Button variant="primary" onClick={() => window.location.reload()}>Reload page</Button>}
        />
      </div>
    );
  }
}
