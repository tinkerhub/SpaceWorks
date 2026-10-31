import { getSessionGeneration } from "./apiSession";

export type UploadGuard = { assertCurrent: () => void; isCurrent: () => boolean };

// One admission survives config, every batch file, bytes and finalization.
export function admitUpload(isCurrent: () => boolean = () => true): UploadGuard {
  const generation = getSessionGeneration();
  const current = () => generation === getSessionGeneration() && isCurrent();
  return {
    isCurrent: current,
    assertCurrent() {
      if (!current()) throw new Error("This upload belongs to an earlier session or resource.");
    },
  };
}

export type StorageUpload = {
  url: string;
  method?: string;
  fields?: Record<string, string>;
  headers?: Record<string, string>;
};

export async function uploadBytes(file: File, upload: StorageUpload, guard: UploadGuard) {
  guard.assertCurrent();
  let response: Response;
  if (upload.method === "PUT") {
    response = await fetch(upload.url, { method: "PUT", body: file, headers: upload.headers });
  } else {
    const body = new FormData();
    Object.entries(upload.fields ?? {}).forEach(([key, value]) => body.append(key, value));
    body.append("file", file);
    response = await fetch(upload.url, { method: "POST", body });
  }
  guard.assertCurrent();
  if (!response.ok) throw new Error(`Storage upload failed (${response.status})`);
}
