import { AuthLayout } from "../../components/chrome/AuthLayout";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Button, Callout } from "../../components/ui";

export function StaffAccessDenied({ makerspaceName, onSignOut }: { makerspaceName?: string; onSignOut: () => void }) {
  return (
    <AuthLayout
      kicker="Access denied"
      title="You do not have access to this makerspace."
      description="Sign in with an account that has a membership for it."
    >
      <div className="flex flex-col gap-4">
        <Callout tone="warning">
          This branded admin dashboard is locked to {makerspaceName ?? "this makerspace"}.
        </Callout>
        <Button variant="primary" fullWidth onClick={onSignOut}>
          Sign out
        </Button>
        <div className="flex justify-center">
          <ThemeToggle />
        </div>
      </div>
    </AuthLayout>
  );
}
