import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "../../components/ui";
import { ApiClientCreateCard } from "./ApiClientCreateCard";
import { ApiClientListCard } from "./ApiClientListCard";
import { ApiClientSecretDialog } from "./ApiClientSecretDialog";
import {
  apiClientsQueryKey,
  apiClientScopesQueryKey,
  apiKeyRequestsQueryKey,
  apiSettingsQueryKey,
  createApiClient,
  deleteApiClient,
  requestApiKey,
  rotateApiClient,
  splitOrigins,
  type ApiClient,
  type ApiClientCreateResponse,
  type ApiKeyRequest,
  type ApiSettings,
  type ApiClientScopeCatalog,
  updateApiClientScopes,
} from "./apiClientsApi";
import { ApiClientsAccessSummary } from "./ApiClientsAccessSummary";
import { errorText } from "./panels/shared";
import { Panel, type Makerspace, useStaffGet } from "./StaffPanels";

export function ApiClientsPanel({
  makerspace,
  isSuperadmin,
  canManageMakerspace,
}: {
  makerspace: Makerspace;
  isSuperadmin: boolean;
  canManageMakerspace: boolean;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [label, setLabel] = useState("");
  const [reason, setReason] = useState("");
  const [origins, setOrigins] = useState("");
  const [scopes, setScopes] = useState<string[]>([]);
  const [submitted, setSubmitted] = useState(false);
  const [oneTimeSecret, setOneTimeSecret] = useState<ApiClientCreateResponse | null>(null);
  const requests = useStaffGet<{ results: ApiKeyRequest[] }>(
    apiKeyRequestsQueryKey(makerspace.id),
    `/admin/api-key-requests?makerspace=${makerspace.id}`,
    !canManageMakerspace,
  );
  const apiClients = useStaffGet<{ results: ApiClient[] }>(
    apiClientsQueryKey(makerspace.id),
    `/admin/makerspace/${makerspace.id}/api-clients`,
    canManageMakerspace,
  );
  const scopeOptions = useStaffGet<ApiClientScopeCatalog>(
    apiClientScopesQueryKey(makerspace.id),
    `/admin/makerspace/${makerspace.id}/api-client-scopes`,
    canManageMakerspace,
  );
  const settings = useStaffGet<ApiSettings>(
    apiSettingsQueryKey(makerspace.id),
    `/admin/makerspace/${makerspace.id}/api-settings`,
    isSuperadmin,
  );
  const catalog = scopeOptions.data?.results ?? [];
  const selectableCreateScopes = scopes.filter((scope) => (
    catalog.some((option) => option.value === scope && option.grantable)
  ));
  const refreshClients = () => queryClient.invalidateQueries({ queryKey: apiClientsQueryKey(makerspace.id) });
  const failed = (fallback: string) => (error: Error) => showToast(errorText(error, fallback), { tone: "error" });

  const requestKey = useMutation({
    mutationFn: () => requestApiKey(makerspace.id, label, reason, splitOrigins(origins)),
    onSuccess: () => {
      setLabel("");
      setReason("");
      setOrigins("");
      setSubmitted(true);
      queryClient.invalidateQueries({ queryKey: apiKeyRequestsQueryKey(makerspace.id) });
      showToast("Request sent", { tone: "success" });
    },
    onError: failed("Couldn't send the request"),
  });
  const createClient = useMutation({
    mutationFn: () => createApiClient(makerspace.id, label, splitOrigins(origins), selectableCreateScopes),
    onSuccess: (created) => {
      setLabel("");
      setOrigins("");
      setScopes([]);
      setOneTimeSecret(created);
      refreshClients();
      showToast("API client created", { tone: "success" });
    },
    onError: failed("Couldn't create the client"),
  });
  const deleteClient = useMutation({
    mutationFn: deleteApiClient,
    onSuccess: () => {
      refreshClients();
      showToast("API client deleted", { tone: "success" });
    },
    onError: failed("Couldn't delete the client"),
  });
  const rotateClient = useMutation({
    mutationFn: rotateApiClient,
    onSuccess: (rotated) => {
      setOneTimeSecret(rotated);
      refreshClients();
      showToast("Secret rotated", { tone: "success" });
    },
    onError: failed("Couldn't rotate the secret"),
  });
  const updateScopes = useMutation({
    mutationFn: ({ clientId, nextScopes }: { clientId: number; nextScopes: string[] }) => (
      updateApiClientScopes(clientId, nextScopes)
    ),
    onSuccess: () => {
      refreshClients();
      showToast("Scopes saved", { tone: "success" });
    },
    onError: failed("Couldn't save the scopes"),
  });

  const handleLabelChange = (value: string) => {
    setLabel(value);
    if (!canManageMakerspace) setSubmitted(false);
  };
  const handleReasonChange = (value: string) => {
    setReason(value);
    setSubmitted(false);
  };
  const handleOriginsChange = (value: string) => {
    setOrigins(value);
    if (!canManageMakerspace) setSubmitted(false);
  };

  return (
    <Panel
      title="API access"
      description={canManageMakerspace
        ? "Give other systems scoped, rotatable access to this makerspace."
        : "Ask for a key when another system needs to read this makerspace."}
    >
      <div className="grid gap-6">
        <ApiClientsAccessSummary makerspace={makerspace} isSuperadmin={isSuperadmin} settings={settings.data} />
        <ApiClientCreateCard
          canManageMakerspace={canManageMakerspace}
          label={label}
          reason={reason}
          origins={origins}
          submitted={submitted}
          isPending={canManageMakerspace ? createClient.isPending : requestKey.isPending}
          error={canManageMakerspace ? createClient.error : requestKey.error}
          scopeOptions={catalog}
          scopes={selectableCreateScopes}
          scopesLoading={scopeOptions.isLoading}
          scopesError={scopeOptions.error}
          onLabelChange={handleLabelChange}
          onReasonChange={handleReasonChange}
          onOriginsChange={handleOriginsChange}
          onScopesChange={setScopes}
          onSubmit={() => canManageMakerspace ? createClient.mutate() : requestKey.mutate()}
        />
        <ApiClientListCard
          canManageMakerspace={canManageMakerspace}
          clients={apiClients.data?.results}
          clientsLoading={apiClients.isLoading}
          clientsError={apiClients.error}
          requests={requests.data?.results}
          requestsLoading={requests.isLoading}
          deletePending={deleteClient.isPending}
          deleteError={deleteClient.error}
          rotatePending={rotateClient.isPending}
          rotateError={rotateClient.error}
          scopeOptions={catalog}
          scopesLoading={scopeOptions.isLoading}
          scopesError={scopeOptions.error}
          scopeUpdatePending={updateScopes.isPending}
          scopeUpdateError={updateScopes.error}
          onDelete={(clientId) => deleteClient.mutateAsync(clientId).catch(() => undefined)}
          onRotate={(clientId) => rotateClient.mutateAsync(clientId).catch(() => undefined)}
          onScopesUpdate={(clientId, nextScopes) => updateScopes.mutate({ clientId, nextScopes })}
        />
      </div>
      <ApiClientSecretDialog secret={oneTimeSecret} onClose={() => setOneTimeSecret(null)} />
    </Panel>
  );
}
