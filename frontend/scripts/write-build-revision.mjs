import { writeFile } from "node:fs/promises";

// Netlify supplies COMMIT_REF. An explicit revision may supplement it, never override it.
const netlifyRevision = process.env.COMMIT_REF;
const explicitRevision = process.env.SPACEWORKS_BUILD_REVISION;
const supplied = [netlifyRevision, explicitRevision].filter((value) => value !== undefined);

try {
  if (supplied.some((value) => value.length !== 40 || !/^[0-9a-f]{40}$/.test(value))) {
    throw new Error("Build revisions must be 40 lowercase hexadecimal characters.");
  }
  if (supplied.length === 2 && netlifyRevision !== explicitRevision) {
    throw new Error("Build revision sources disagree.");
  }
  await writeFile(
    new URL("../dist/deployment.json", import.meta.url),
    `${JSON.stringify({ revision: netlifyRevision ?? explicitRevision ?? null })}\n`,
    "utf8",
  );
  console.log("Wrote frontend deployment metadata.");
} catch {
  console.error("Could not write deployment metadata: check revision configuration and build output.");
  process.exitCode = 1;
}
