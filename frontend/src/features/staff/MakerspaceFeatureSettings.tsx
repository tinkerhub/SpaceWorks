import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Card, CardHeader, Chip, SwitchRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { FEATURE_DEFINITIONS } from "../../lib/features";
import { moduleEnabled } from "../../lib/modules";
import { errorText, type Makerspace } from "./panels/shared";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
};

// Parentless features (parent_module === null) group under GENERAL: always available,
// never gated by a module.
const GENERAL = "__general__";

const MODULE_FEATURES = Object.entries(
  FEATURE_DEFINITIONS.reduce<Record<string, typeof FEATURE_DEFINITIONS>>((groups, feature) => {
    const group = feature.parent_module ?? GENERAL;
    groups[group] = [...(groups[group] ?? []), feature];
    return groups;
  }, {}),
);

export function MakerspaceFeatureSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const enabledModules = settings?.enabled_modules ?? makerspace.enabled_modules ?? [];
  const enabledFeatures = settings?.enabled_features ?? makerspace.enabled_features ?? [];
  const update = useMutation({
    mutationFn: (next: string[]) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled_features: next }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      showToast("Features updated", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't update the features"), { tone: "error" }),
  });

  const toggleFeature = (key: string, checked: boolean) => {
    const next = checked
      ? [...enabledFeatures, key]
      : enabledFeatures.filter((feature) => feature !== key);
    update.mutate(next);
  };

  return (
    <Card as="section">
      <CardHeader
        title="Features"
        description="Modules are set by the platform administrator. Turn on the sub-features this makerspace uses."
      />
      {enabledModules.length ? (
        <div className="mb-4 flex flex-wrap gap-1.5">
          {enabledModules.map((module) => <Chip key={module} tone="neutral" size="sm">{module}</Chip>)}
        </div>
      ) : null}
      {update.error ? <p className="mb-3 text-caption text-danger-fg" role="alert">{update.error.message}</p> : null}
      <div className="grid gap-3">
        {MODULE_FEATURES.map(([module, allFeatures]) => {
          const isGeneral = module === GENERAL;
          // A fieldset for a switched-off module is not rendered at all, and a `payments.*`
          // sub-feature also needs the payments module itself (capabilities.py requires it).
          if (!isGeneral && !moduleEnabled(enabledModules, module)) return null;
          const features = allFeatures.filter(
            (feature) => !feature.key.startsWith("payments.") || moduleEnabled(enabledModules, "payments"),
          );
          if (!features.length) return null;
          return (
            <fieldset key={module} className="grid gap-3 rounded-md border border-line p-4">
              <legend className="px-1 text-label text-ink">{isGeneral ? "General" : module}</legend>
              {features.map((feature) => (
                <SwitchRow
                  key={feature.key}
                  label={feature.label}
                  checked={enabledFeatures.includes(feature.key)}
                  disabled={loading || update.isPending}
                  onCheckedChange={(checked) => toggleFeature(feature.key, checked)}
                />
              ))}
            </fieldset>
          );
        })}
      </div>
    </Card>
  );
}
