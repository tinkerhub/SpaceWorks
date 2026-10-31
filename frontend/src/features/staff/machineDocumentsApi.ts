import { admitUpload, uploadBytes, type UploadGuard } from "../../lib/uploadProtocol";
import { staffRequest } from '../../lib/api';
import type { MachineCollection, MachineDocument } from './machinesApi';

type MachineUpload =
  | { url: string; fields: Record<string, string>; method?: string; headers?: Record<string, string> }
  | { url: string; method: 'PUT'; headers?: Record<string, string>; fields?: Record<string, string> };
type MachinePresignResponse = { object_key: string; upload: MachineUpload };

export async function uploadMachineDocument(machineId: number, file: File, docType: string, guard: UploadGuard = admitUpload()) {
  guard.assertCurrent();
  const presigned = await staffRequest<MachinePresignResponse>(
    `/admin/machines/${machineId}/documents/presign`,
    {
      method: 'POST',
      body: JSON.stringify({
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
      }),
    },
  );

  await uploadBytes(file, presigned.upload, guard);
  guard.assertCurrent();

  const document = await staffRequest<MachineDocument>(`/admin/machines/${machineId}/documents`, {
    method: 'POST',
    body: JSON.stringify({
      object_key: presigned.object_key,
      doc_type: docType,
      original_filename: file.name,
    }),
  });
  guard.assertCurrent();
  return document;
}

export function getMachineDocuments(machineId: number) {
  return staffRequest<MachineCollection<MachineDocument>>(
    `/admin/machines/${machineId}/documents`,
  );
}

export function getMachineDocumentUrl(documentId: number) {
  return staffRequest<{ url: string }>(`/admin/machines/documents/${documentId}/url`);
}

export function deleteMachineDocument(documentId: number) {
  return staffRequest<void>(`/admin/machines/documents/${documentId}`, { method: 'DELETE' });
}
