import { machineTypeSegment, parseMachineTypeSegment } from "./staffTabs";

/** The first segment's ID owns the selection; the slug remains decoration. */
export function machineTypeRoute(subPath: string) {
  const [segment, ...rest] = subPath.split("/");
  const typeId = parseMachineTypeSegment(segment);
  return { typeId, queue: typeId !== null && rest.join("/") === "queue" };
}

export function machineTypeQueueSegment(type: { id: number; slug?: string | null }) {
  return `${machineTypeSegment(type)}/queue`;
}
