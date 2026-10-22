import { FilterChip } from "../../../components/ui";

export type MachineTypeOption = {
  id: number;
  name: string;
  is_active: boolean;
  is_overridden: boolean;
};

/** Which copy of the template to edit: the space default or one machine type's override. */
export function EmailTemplateTypeSelector({
  canEditSpaceDefault,
  types,
  selectedTypeId,
  onSelect,
}: {
  canEditSpaceDefault: boolean;
  types: MachineTypeOption[];
  selectedTypeId: number | null;
  onSelect: (machineType: MachineTypeOption | null) => void;
}) {
  // No per-type copy to pick (machines off, or a stream no machine type overrides): a
  // selector holding only "Space default" would name a module the space may not run.
  if (!types.length) return null;
  return (
    <div role="group" aria-labelledby="email-template-type-label" className="grid gap-2">
      <p id="email-template-type-label" className="text-label text-ink">Machine type</p>
      <div className="flex flex-wrap gap-2">
        {canEditSpaceDefault ? (
          <FilterChip selected={selectedTypeId === null} onClick={() => onSelect(null)}>
            Space default
          </FilterChip>
        ) : null}
        {types.map((machineType) => (
          <FilterChip
            key={machineType.id}
            selected={selectedTypeId === machineType.id}
            onClick={() => onSelect(machineType)}
          >
            {machineType.name}
            {machineType.is_overridden ? <span className="text-caption opacity-80">· Edited</span> : null}
          </FilterChip>
        ))}
      </div>
    </div>
  );
}
