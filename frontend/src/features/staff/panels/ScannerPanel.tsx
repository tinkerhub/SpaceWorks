import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Camera } from "lucide-react";

import { Button, Callout, Card, CardHeader, ConfirmDialog, ErrorText, Input, useToast } from "../../../components/ui";
import QrScanner from "../../../components/ui/QrScanner";
import { staffRequest, type StaffAuthUser } from "../../../lib/api";
import { errorText, Panel, StatusWord, type Makerspace, type Product, useStaffGet } from "./shared";
import { qrResolveErrorText } from "../evidenceUi";
import { invalidateInventoryViews, invalidateQrViews } from "../queryInvalidation";
import { BoxContentsList, MoveAssetForm, RebindForm, targetTitle, type BoxContents, type Rebound, type Resolved } from "./ScannerPanelForms";

type ListResponse<T> = T[] | { results: T[] };

function rows<T>(data?: ListResponse<T>) {
  if (!data) return [];
  return Array.isArray(data) ? data : data.results;
}

const HANDOUT_ACTIONS = ["checkout", "return", "direct_handout"];

// The staff scanner page existed as an orphan route with dead action badges. This wires
// the staff-reachable allowed_actions the backend returns: revoke (MANAGE_QR) and box
// contents. checkout/return/direct_handout need a borrower identifier, so we point staff
// to the Direct handout / self-checkout flows instead of faking them here.
export function ScannerPanel({ makerspace, isSuperadmin, makerspaces }: {
  makerspace: Makerspace;
  isSuperadmin: boolean;
  makerspaces: Makerspace[];
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [payload, setPayload] = useState("");
  const [scanNote, setScanNote] = useState("");
  const [showScanner, setShowScanner] = useState(false);
  const [resolved, setResolved] = useState<Resolved | null>(null);
  const [contents, setContents] = useState<BoxContents | null>(null);
  const [showRebind, setShowRebind] = useState(false);
  const [showMove, setShowMove] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [selectedProductId, setSelectedProductId] = useState("");
  const [destMakerspaceId, setDestMakerspaceId] = useState("");
  const [destProductId, setDestProductId] = useState("");
  const [newName, setNewName] = useState("");
  const [moveTag, setMoveTag] = useState("");
  const [successNote, setSuccessNote] = useState<string | null>(null);
  const resolvedQrMakerspaceId = resolved?.qr.makerspace_id ?? resolved?.qr.makerspace;
  const rebindMakerspaceId = resolvedQrMakerspaceId ?? makerspace.id;
  const rebindMakerspace = makerspaces.find((space) => space.id === rebindMakerspaceId) ?? (makerspace.id === rebindMakerspaceId ? makerspace : undefined);

  const products = useStaffGet<ListResponse<Product>>(
    ["inventory-all", rebindMakerspaceId],
    `/admin/makerspace/${rebindMakerspaceId}/inventory?page_size=1000`,
    showRebind && Boolean(resolvedQrMakerspaceId),
  );
  const destinationProducts = useStaffGet<ListResponse<Product>>(
    ["inventory-all", destMakerspaceId],
    `/admin/makerspace/${destMakerspaceId}/inventory?page_size=1000`,
    Boolean(destMakerspaceId),
  );
  const currentUser = useStaffGet<StaffAuthUser>(["staff", "me"], "/auth/me");
  const productRows = useMemo(() => rows(products.data), [products.data]);
  const destinationProductRows = useMemo(() => rows(destinationProducts.data).filter((product) => product.tracking_mode === "individual"), [destinationProducts.data]);

  const resolve = useMutation({
    mutationFn: (value: string) => staffRequest<Resolved>("/admin/qr/resolve", { method: "POST", body: JSON.stringify({ payload: value.trim() }) }),
    onSuccess: (data) => {
      setResolved(data);
      setContents(null);
      setScanNote("");
      setShowRebind(false);
      setShowMove(false);
      setSelectedProductId("");
      setDestMakerspaceId("");
      setDestProductId("");
      setNewName("");
      setMoveTag("");
      setSuccessNote(null);
      loadContents.reset();
    },
  });
  // Re-resolve after a change; when the QR left this makerspace the old card is stale.
  const reResolve = (qrPayload: string, done: string) => {
    setSuccessNote(done);
    resolve.mutate(qrPayload, {
      onSuccess: () => setSuccessNote(done),
      onError: () => {
        setResolved(null);
        setContents(null);
        setSuccessNote(`${done} Re-scan in the destination makerspace to view.`);
      },
    });
  };
  const revoke = useMutation({
    mutationFn: (qrId: number) => staffRequest(`/admin/qr/${qrId}/revoke`, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => {
      setConfirmRevoke(false);
      if (resolvedQrMakerspaceId) invalidateQrViews(queryClient, resolvedQrMakerspaceId, resolved?.qr.id);
      if (resolved) resolve.mutate(resolved.qr.payload);
      showToast("QR revoked", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Could not revoke the QR"), { tone: "error" }),
  });
  const loadContents = useMutation({
    mutationFn: (boxId: number) => staffRequest<BoxContents>(`/admin/containers/${boxId}/contents`),
    onSuccess: setContents,
    onError: (error) => showToast(errorText(error, "Could not load the box contents"), { tone: "error" }),
  });
  const rebind = useMutation({
    mutationFn: () =>
      staffRequest<Rebound>(`/admin/qr/${resolved?.qr.id}/rebind-target`, {
        method: "POST",
        body: JSON.stringify({ target_type: "product", target_id: Number(selectedProductId), new_name: newName.trim() || undefined }),
      }),
    onSuccess: (data) => {
      if (resolvedQrMakerspaceId) invalidateInventoryViews(queryClient, resolvedQrMakerspaceId);
      invalidateQrViews(queryClient, data.qr.makerspace_id ?? data.qr.makerspace, data.qr.id);
      setShowRebind(false);
      setNewName("");
      showToast("QR rebound", { tone: "success" });
      reResolve(data.qr.payload, "Rebound.");
    },
    onError: (error) => showToast(errorText(error, "Could not rebind the QR"), { tone: "error" }),
  });
  const moveAsset = useMutation({
    mutationFn: () => {
      if (!resolved) throw new Error("No QR resolved.");
      return staffRequest<Rebound>(`/admin/qr/${resolved.qr.id}/rebind-target`, {
        method: "POST",
        body: JSON.stringify({
          target_type: "asset",
          target_id: resolved.target.id,
          destination_makerspace_id: Number(destMakerspaceId),
          destination_product_id: destProductId ? Number(destProductId) : undefined,
          new_name: moveTag.trim() || undefined,
        }),
      });
    },
    onSuccess: (data) => {
      if (resolvedQrMakerspaceId) invalidateInventoryViews(queryClient, resolvedQrMakerspaceId);
      if (destMakerspaceId) invalidateInventoryViews(queryClient, Number(destMakerspaceId));
      invalidateQrViews(queryClient, data.qr.makerspace_id ?? data.qr.makerspace, data.qr.id);
      setShowMove(false);
      setDestMakerspaceId("");
      setDestProductId("");
      setMoveTag("");
      showToast("Asset moved", { tone: "success" });
      reResolve(data.qr.payload, "Moved.");
    },
    onError: (error) => showToast(errorText(error, "Could not move the asset"), { tone: "error" }),
  });

  useEffect(() => {
    if (!productRows.length) {
      setSelectedProductId("");
      return;
    }
    if (!productRows.some((product) => String(product.id) === selectedProductId)) {
      setSelectedProductId(String(productRows[0].id));
    }
  }, [productRows, selectedProductId]);

  const doResolve = (value: string) => {
    setScanNote("");
    if (value.trim()) resolve.mutate(value);
  };
  // Camera scans resolve the opaque token WITHOUT echoing it into the visible
  // input (the payload is a physical-possession token, not something to display).
  const resolveFromScan = (value: string) => {
    setShowScanner(false);
    if (!value.trim()) return;
    setScanNote("Scanned - resolving…");
    resolve.mutate(value);
  };
  const target = resolved?.target;
  const actions = resolved?.allowed_actions ?? [];
  const message = (error: unknown) => (error instanceof Error ? error.message : undefined);
  const rebindActions = currentUser.data?.makerspaces.find((item) => item.id === resolvedQrMakerspaceId)?.actions ?? [];
  const hasRebindPermissions = isSuperadmin || (rebindActions.includes("manage_qr") && rebindActions.includes("edit_inventory"));
  // Rebind UI only targets PRODUCT QRs (the cross-makerspace quantity-product
  // transfer scenario). The form always submits target_type "product", so offering
  // it for an asset QR would silently convert that QR's type - disallow it here.
  const canRebind = Boolean(resolved && target && target.type === "product" && hasRebindPermissions);
  const canMoveAsset = Boolean(resolved && target && target.type === "asset" && isSuperadmin);
  const destinationMakerspaces = makerspaces.filter((space) => space.id !== resolvedQrMakerspaceId);
  const handoutActions = actions.filter((action) => HANDOUT_ACTIONS.includes(action));

  return (
    <Panel
      title="Scanner"
      description="Scan or paste a QR payload to find a box, product or asset and act on it."
      actions={<Button variant="primary" startIcon={<Camera />} onClick={() => { setScanNote(""); setShowScanner(true); }}>Scan camera</Button>}
    >
      <div className="grid gap-4">
        <form className="flex flex-col gap-2.5 sm:flex-row" onSubmit={(event) => { event.preventDefault(); doResolve(payload); }}>
          <Input aria-label="QR payload" className="font-mono sm:flex-1" placeholder="Paste QR payload (or scan)" value={payload} onChange={(event) => setPayload(event.target.value)} />
          <Button type="submit" disabled={!payload.trim()} loading={resolve.isPending} loadingLabel="Resolving…">Resolve</Button>
        </form>
        {scanNote && resolve.isPending ? <p role="status" className="text-body-ui text-ink-muted">{scanNote}</p> : null}
        <ErrorText message={resolve.error ? qrResolveErrorText(resolve.error) : undefined} />
        {successNote ? <p role="status" className="text-body-ui text-success-fg">{successNote}</p> : null}

        {resolved && target ? (
          <Card as="section">
            <CardHeader
              title={targetTitle(target)}
              description={<span className="inline-flex flex-wrap items-center gap-2"><span className="font-mono">QR #{resolved.qr.id}{target.type === "box" ? ` · ${target.code}` : ""}</span><StatusWord status={resolved.qr.status} /></span>}
              action={target.type === "asset" ? <StatusWord status={target.status} /> : undefined}
            />
            <div className="grid gap-4">
              <div className="flex flex-wrap gap-2.5">
                {actions.includes("contents") && target.type === "box" ? (
                  <Button size="sm" loading={loadContents.isPending} onClick={() => loadContents.mutate(target.id)}>View contents</Button>
                ) : null}
                {canRebind ? <Button size="sm" aria-expanded={showRebind} onClick={() => setShowRebind((open) => !open)}>Rename & rebind</Button> : null}
                {canMoveAsset ? <Button size="sm" aria-expanded={showMove} onClick={() => setShowMove((open) => !open)}>Move to makerspace</Button> : null}
                {actions.includes("revoke") ? (
                  <Button size="sm" variant="danger" disabled={revoke.isPending} onClick={() => setConfirmRevoke(true)}>Revoke QR…</Button>
                ) : null}
              </div>
              {showRebind ? (
                <RebindForm
                  makerspaceName={rebindMakerspace?.name ?? `Makerspace #${rebindMakerspaceId}`}
                  products={productRows}
                  productsLoading={products.isLoading}
                  productId={selectedProductId}
                  onProductChange={setSelectedProductId}
                  newName={newName}
                  onNewNameChange={setNewName}
                  pending={rebind.isPending}
                  errors={[message(products.error), message(rebind.error)]}
                  onSubmit={() => rebind.mutate()}
                  onCancel={() => setShowRebind(false)}
                />
              ) : null}
              {canMoveAsset && showMove ? (
                <MoveAssetForm
                  makerspaces={destinationMakerspaces}
                  destMakerspaceId={destMakerspaceId}
                  onDestMakerspaceChange={(value) => { setDestMakerspaceId(value); setDestProductId(""); }}
                  products={destinationProductRows}
                  productsLoading={destinationProducts.isLoading}
                  destProductId={destProductId}
                  onDestProductChange={setDestProductId}
                  moveTag={moveTag}
                  onMoveTagChange={setMoveTag}
                  pending={moveAsset.isPending}
                  errors={[message(destinationProducts.error), message(moveAsset.error)]}
                  onSubmit={() => moveAsset.mutate()}
                  onCancel={() => setShowMove(false)}
                />
              ) : null}
              {handoutActions.length ? (
                <Callout tone="info">
                  This item supports {handoutActions.join(" / ").replace(/_/g, " ")}. Use the Direct handout tab (or the public self-checkout page),
                  which collects the borrower's identity.
                </Callout>
              ) : null}
              <ErrorText message={message(revoke.error)} />
              <ErrorText message={message(loadContents.error)} />
              {contents ? <BoxContentsList contents={contents} /> : null}
            </div>
          </Card>
        ) : null}
      </div>

      <ConfirmDialog
        open={confirmRevoke && Boolean(resolved)}
        title="Revoke this QR?"
        message={resolved && target ? `QR #${resolved.qr.id} for ${targetTitle(target)} will stop working. Print a new label to replace it.` : ""}
        confirmLabel="Revoke QR"
        tone="danger"
        pending={revoke.isPending}
        onCancel={() => setConfirmRevoke(false)}
        onConfirm={() => { if (resolved) revoke.mutate(resolved.qr.id); }}
      />
      {showScanner ? <QrScanner onScan={resolveFromScan} onClose={() => setShowScanner(false)} /> : null}
    </Panel>
  );
}
