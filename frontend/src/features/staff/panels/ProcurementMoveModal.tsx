import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Dialog, ErrorText, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { invalidateInventoryViews, invalidatePrintingViews } from "../queryInvalidation";
import type { Machine } from "../machinesApi";
import {
  HardwareMoveForm,
  PrintingMoveForm,
  type ContainerOption,
  type HardwareForm,
  type PrintingForm,
} from "./ProcurementMoveForms";
import type { ToBuyItem } from "./ProcurementPanelRows";
import { categoryResults, errorText, type CategoryListResponse, type Makerspace, type Product, useStaffGet } from "./shared";

type ListResponse<T> = { results: T[] };
type PrinterOption = Pick<Machine, "id" | "name">;

export function ProcurementMoveModal({ item, makerspace, onClose, onMoved }: {
  item: ToBuyItem | null;
  makerspace: Makerspace;
  onClose: () => void;
  onMoved: () => void;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const open = Boolean(item);
  const isHardware = item?.kind === "hardware";
  const [hardware, setHardware] = useState<HardwareForm>(() => hardwareDefaults(null));
  const [printing, setPrinting] = useState<PrintingForm>(printingDefaults);

  useEffect(() => {
    setHardware(hardwareDefaults(item));
    setPrinting(printingDefaults());
  }, [item]);

  const products = useStaffGet<ListResponse<Product>>(["inventory-all", makerspace.id], `/admin/makerspace/${makerspace.id}/inventory?page_size=1000`, open && isHardware);
  const categories = useStaffGet<CategoryListResponse>(["categories", makerspace.id], `/admin/makerspace/${makerspace.id}/categories`, open && isHardware);
  const containers = useStaffGet<ListResponse<ContainerOption>>(["containers-all", makerspace.id], `/admin/makerspace/${makerspace.id}/containers?page_size=1000`, open && isHardware);
  const printers = useStaffGet<ListResponse<PrinterOption>>(["printer-machines", makerspace.id], `/admin/makerspace/${makerspace.id}/machines?machine_type=3d_printer`, open && !isHardware);

  const moveHardware = useMutation({
    mutationFn: () => {
      if (!item) return Promise.reject(new Error("Select an item first."));
      return staffRequest(`/procurement/to-buy/${item.id}/move-to-inventory`, { method: "POST", body: JSON.stringify(hardwarePayload(hardware)) });
    },
    onSuccess: () => {
      invalidateInventoryViews(queryClient, makerspace.id, makerspace.slug);
      queryClient.invalidateQueries({ queryKey: ["procurement", makerspace.id] });
      showToast(`${item?.name ?? "Item"} moved to inventory.`, { tone: "success" });
      onMoved();
      onClose();
    },
    onError: (error) => showToast(errorText(error, "Could not move item."), { tone: "error" }),
  });
  const movePrinting = useMutation({
    mutationFn: () => {
      if (!item) return Promise.reject(new Error("Select an item first."));
      return staffRequest(`/procurement/to-buy/${item.id}/move-to-printing`, { method: "POST", body: JSON.stringify(printingPayload(printing)) });
    },
    onSuccess: () => {
      invalidatePrintingViews(queryClient, makerspace.id);
      queryClient.invalidateQueries({ queryKey: ["procurement", makerspace.id] });
      showToast(`${item?.name ?? "Item"} moved to printing.`, { tone: "success" });
      onMoved();
      onClose();
    },
    onError: (error) => showToast(errorText(error, "Could not move item."), { tone: "error" }),
  });

  const resetHardware = moveHardware.reset;
  const resetPrinting = movePrinting.reset;
  // A failed move for one item must not greet the next item opened in this dialog.
  useEffect(() => {
    resetHardware();
    resetPrinting();
  }, [item, resetHardware, resetPrinting]);

  const pending = moveHardware.isPending || movePrinting.isPending;
  const error = moveHardware.error ?? movePrinting.error;
  const canSubmit = isHardware ? canSubmitHardware(hardware) : canSubmitPrinting(printing);

  return (
    <Dialog
      open={open}
      onClose={() => { if (!pending) onClose(); }}
      title={item?.kind === "printing" ? "Move to printing" : "Move to inventory"}
      description={item ? `${item.name} · received quantity ${item.quantity}` : undefined}
      size="lg"
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button disabled={pending} onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={pending} loadingLabel="Moving…" disabled={!canSubmit} onClick={() => (isHardware ? moveHardware.mutate() : movePrinting.mutate())}>Move</Button>
        </div>
      )}
    >
      <div className="grid gap-4">
        {item?.kind === "hardware" ? (
          <HardwareMoveForm form={hardware} setForm={setHardware} products={products.data?.results ?? []} categories={categoryResults(categories.data)} containers={containers.data?.results ?? []} />
        ) : (
          <PrintingMoveForm form={printing} setForm={setPrinting} printers={printers.data?.results ?? []} />
        )}
        {error ? <ErrorText message={errorText(error, "Could not move item.")} /> : null}
      </div>
    </Dialog>
  );
}

function hardwareDefaults(item: ToBuyItem | null): HardwareForm {
  return {
    mode: "create",
    quantity: String(item?.quantity ?? 1),
    productId: "",
    name: item?.name ?? "",
    description: "",
    category: "",
    box: "",
    trackingMode: "quantity",
    isPublic: true,
    publicAvailabilityMode: "status_only",
    showPublicCount: false,
    publicSelfCheckoutEnabled: false,
  };
}

function printingDefaults(): PrintingForm {
  return {
    target: "spool",
    printerId: "",
    material: "PLA",
    color: "",
    brand: "",
    initialWeight: "1000",
    remainingWeight: "1000",
    printerName: "",
    printerModel: "",
    printerStatus: "active",
  };
}

function hardwarePayload(form: HardwareForm) {
  if (form.mode === "topup") return { mode: "topup", product_id: Number(form.productId), quantity: Number(form.quantity) || 1 };
  return {
    mode: "create",
    quantity: Number(form.quantity) || 1,
    name: form.name.trim(),
    description: form.description,
    category: form.category ? Number(form.category) : null,
    box: form.box ? Number(form.box) : null,
    tracking_mode: form.trackingMode,
    is_public: form.isPublic,
    public_availability_mode: form.publicAvailabilityMode,
    show_public_count: form.showPublicCount,
    public_self_checkout_enabled: form.publicSelfCheckoutEnabled,
  };
}

function printingPayload(form: PrintingForm) {
  if (form.target === "printer") {
    return { target: "printer", name: form.printerName.trim(), model: form.printerModel.trim(), status: form.printerStatus, is_active: true };
  }
  return {
    target: "spool",
    printer: form.printerId ? Number(form.printerId) : null,
    material: form.material.trim(),
    color: form.color.trim(),
    brand: form.brand.trim(),
    initial_weight_grams: form.initialWeight,
    remaining_weight_grams: form.remainingWeight,
    is_active: true,
  };
}

function canSubmitHardware(form: HardwareForm) {
  if (Number(form.quantity) < 1) return false;
  if (form.mode === "topup") return Boolean(form.productId);
  return Boolean(form.name.trim());
}

function canSubmitPrinting(form: PrintingForm) {
  if (form.target === "printer") return Boolean(form.printerName.trim());
  return Boolean(form.material.trim()) && Number(form.initialWeight) >= 0 && Number(form.remainingWeight) >= 0;
}
