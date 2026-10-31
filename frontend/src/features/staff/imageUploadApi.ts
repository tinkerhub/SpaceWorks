import { publicV1Request, staffRequest } from "../../lib/api";
import { admitUpload, uploadBytes, type UploadGuard } from "../../lib/uploadProtocol";

type PresignResponse = {
  object_key: string;
  url: string;
  fields?: Record<string, string>;
  method?: string;
  headers?: Record<string, string>;
};

type PublicConfigResponse = {
  public_image_max_bytes: number;
};

let publicImageMaxBytesPromise: Promise<number> | null = null;

async function getPublicImageMaxBytes() {
  if (!publicImageMaxBytesPromise) {
    const pending = publicV1Request<PublicConfigResponse>("/config").then(
      (config) => {
        const cap = Number(config.public_image_max_bytes);
        if (!Number.isFinite(cap) || cap <= 0) {
          throw new Error("Image upload limit is unavailable.");
        }
        return cap;
      },
    );
    publicImageMaxBytesPromise = pending;
    void pending.catch(() => {
      if (publicImageMaxBytesPromise === pending) publicImageMaxBytesPromise = null;
    });
  }
  return publicImageMaxBytesPromise;
}

async function rejectOversizePublicImage(file: File) {
  const cap = await getPublicImageMaxBytes();
  if (file.size > cap) {
    throw new Error(`Image too large (max ${Math.round(cap / 1048576)} MB).`);
  }
}

export async function uploadPublicImage(
  endpoint: string,
  file: File,
  // Extra fields carried on BOTH the presign and the attach — the member profile
  // endpoints use one triple for the avatar and for each project image, discriminated
  // by `project_id`, and the attach needs it as much as the presign does.
  extraBody: Record<string, unknown> = {},
  guard: UploadGuard = admitUpload(),
) {
  const body = JSON.parse(JSON.stringify(extraBody)) as Record<string, unknown>;
  guard.assertCurrent();
  await rejectOversizePublicImage(file);
  guard.assertCurrent();
  const presigned = await staffRequest<PresignResponse>(endpoint, {
    method: "POST",
    body: JSON.stringify({
      content_type: file.type || "application/octet-stream",
      filename: file.name,
      ...body,
    }),
  });

  await uploadBytes(file, presigned, guard);
  guard.assertCurrent();
  await staffRequest(endpoint, {
    method: "PUT",
    body: JSON.stringify({ object_key: presigned.object_key, ...body }),
  });
  guard.assertCurrent();
}
