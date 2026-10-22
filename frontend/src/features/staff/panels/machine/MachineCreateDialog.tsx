import { useRef, useState } from "react";
import { Plus } from "lucide-react";

import { Button, Modal } from "../../../../components/ui";
import type { MachineType } from "../../machinesApi";
import { MachineCreateForm } from "./MachineCreateForm";

/**
 * The machine type page's one primary action. Creating keeps the dialog open for the optional
 * photo and warranty step; closing it (Done, Cancel after creating, Escape) then opens the new
 * machine's drawer, so the drawer never lands on top of a half-finished dialog.
 */
export function MachineCreateDialog({ makerspaceId, machineType, onCreated }: {
  makerspaceId: number;
  machineType: MachineType;
  onCreated: (machineId: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const createdId = useRef<number | null>(null);

  const close = () => {
    setOpen(false);
    const id = createdId.current;
    createdId.current = null;
    if (id !== null) onCreated(id);
  };

  return (
    <>
      <Button variant="primary" startIcon={<Plus />} onClick={() => setOpen(true)}>
        Add machine
      </Button>
      <Modal
        open={open}
        onClose={close}
        title={`Add ${machineType.name}`}
        description="Name it now; a photo and warranty details can follow."
      >
        <MachineCreateForm
          makerspaceId={makerspaceId}
          machineType={machineType}
          onCreated={(id) => { createdId.current = id; }}
          onCancel={close}
          onDone={close}
        />
      </Modal>
    </>
  );
}
