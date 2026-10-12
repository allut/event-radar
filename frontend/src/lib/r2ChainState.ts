/**
 * Thin S3-compatible client wrapper for Cloudflare R2 (issue #366), backing
 * the prerender chain-state manifest (issue #365) — a parallel, optional
 * cache that lets a resumed prerender round skip re-fetching production
 * HTML for targets already resolved earlier in the same burst. Accessed via
 * the S3-compatible API rather than a Workers/Functions `[[r2_buckets]]`
 * binding, since scripts/prerender.ts runs as a Node build script in the
 * Cloudflare Pages build container, not as a Worker.
 *
 * R2 is an optimization only, never a correctness dependency (#365's locked
 * fallback posture): every function here fails open exactly like
 * commitRoundMarker (scripts/prerender.ts) — a missing env var logs and
 * returns a "nothing happened" result rather than throwing, and any error
 * thrown by the underlying S3 call is caught and logged here rather than
 * propagated. Callers (the read/write integration in a later ticket) treat
 * every falsy/null result as "fall back to today's behavior", never as a
 * build failure.
 *
 * This module only wraps the generic get/put/delete-by-prefix primitives —
 * it has no knowledge of the manifest's key format (burstId/locale/eventId)
 * or schema; that's the read/write integration's job, kept separate so this
 * primitive stays independently reasoned-about and testable.
 */
import {
  DeleteObjectsCommand,
  GetObjectCommand,
  ListObjectsV2Command,
  PutObjectCommand,
  S3Client,
} from '@aws-sdk/client-s3';
import { S3_MAX_KEYS_PER_PAGE } from '../constants/prerender';

let cachedClient: { credsKey: string; client: S3Client } | null = null;

/** Returns the R2 client for the current env vars, or `null` (logged) if any
 * of the three required credentials are unset — e.g. local dev builds that
 * never populated `.env.local`'s R2_* vars, mirroring commitRoundMarker's
 * missing-token no-op. Memoized on the credential tuple so a round's
 * thousands of get/put calls share one client (Big-O audit M14) while a
 * changed env still yields a fresh one. */
function buildClient(): S3Client | null {
  const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
  const accessKeyId = process.env.R2_ACCESS_KEY_ID;
  const secretAccessKey = process.env.R2_SECRET_ACCESS_KEY;
  if (!accountId || !accessKeyId || !secretAccessKey) {
    console.log(
      'prerender: CLOUDFLARE_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY not set — skipping R2 chain-state operation',
    );
    return null;
  }
  const credsKey = `${accountId}\0${accessKeyId}\0${secretAccessKey}`;
  if (cachedClient?.credsKey === credsKey) return cachedClient.client;
  const client = new S3Client({
    region: 'auto',
    endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
    credentials: { accessKeyId, secretAccessKey },
  });
  cachedClient = { credsKey, client };
  return client;
}

/** Separate from buildClient's credential check since the bucket name is a
 * distinct env var (R2_BUCKET_NAME) that could be unset independently. */
function resolveBucket(): string | null {
  const bucket = process.env.R2_BUCKET_NAME;
  if (!bucket) {
    console.log('prerender: R2_BUCKET_NAME not set — skipping R2 chain-state operation');
    return null;
  }
  return bucket;
}

/** Reads `key` from the chain-state bucket, returning its body as a string,
 * or `null` if R2 isn't configured, the object doesn't exist, or the read
 * failed for any other reason — every case degrades identically to "treat
 * as absent", which is exactly the fallback #365 asks for at both call
 * sites (an index-read miss means "no manifest yet, full re-classify this
 * round"; a content-read miss for an index-resolved target means "fall
 * back to a fresh production fetch for that one target"). */
export async function getR2Object(key: string): Promise<string | null> {
  const client = buildClient();
  const bucket = resolveBucket();
  if (!client || !bucket) return null;
  try {
    const res = await client.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
    return (await res.Body?.transformToString()) ?? null;
  } catch (error) {
    console.error(`prerender: R2 get failed for ${key} — treating as absent:`, error);
    return null;
  }
}

/** Writes `body` to `key` in the chain-state bucket. Returns `false` (never
 * throws) if R2 isn't configured or the write fails — per #365, a lost
 * write only costs this round's/burst's savings, never correctness, so
 * callers only need to log and move on. */
export async function putR2Object(
  key: string,
  body: string,
  contentType: string,
): Promise<boolean> {
  const client = buildClient();
  const bucket = resolveBucket();
  if (!client || !bucket) return false;
  try {
    await client.send(
      new PutObjectCommand({ Bucket: bucket, Key: key, Body: body, ContentType: contentType }),
    );
    return true;
  } catch (error) {
    console.error(`prerender: R2 put failed for ${key} — continuing without persisting:`, error);
    return false;
  }
}

/** Deletes every object under `prefix` (list, then batch-delete), used on a
 * `done` round to clean up a finished burst's manifest in one shot instead
 * of relying solely on the bucket's lifecycle-rule backstop
 * (CHAIN_STATE_LIFECYCLE_DAYS). Pages through ListObjectsV2's continuation
 * token — a burst's target count (thousands, per #365) can exceed a single
 * page's S3_MAX_KEYS_PER_PAGE cap — deleting each page's keys immediately
 * rather than accumulating the full key list first. Returns `false` (never
 * throws) if R2 isn't configured or any step fails; a failed cleanup is
 * swept later by the lifecycle rule, never a build failure. */
export async function deleteR2ObjectsByPrefix(prefix: string): Promise<boolean> {
  const client = buildClient();
  const bucket = resolveBucket();
  if (!client || !bucket) return false;
  try {
    let continuationToken: string | undefined;
    let allSucceeded = true;
    do {
      const listed = await client.send(
        new ListObjectsV2Command({
          Bucket: bucket,
          Prefix: prefix,
          MaxKeys: S3_MAX_KEYS_PER_PAGE,
          ContinuationToken: continuationToken,
        }),
      );
      const keys = (listed.Contents ?? [])
        .map((object) => object.Key)
        .filter((key): key is string => key !== undefined);
      if (keys.length > 0) {
        // DeleteObjectsCommand doesn't throw for a partial failure — a
        // per-object error (e.g. a transient lock) comes back as HTTP 200
        // with an `Errors` array alongside `Deleted`, so it must be checked
        // explicitly rather than inferred from the absence of a thrown
        // error.
        const deleted = await client.send(
          new DeleteObjectsCommand({
            Bucket: bucket,
            Delete: { Objects: keys.map((Key) => ({ Key })) },
          }),
        );
        if (deleted.Errors && deleted.Errors.length > 0) {
          console.error(
            `prerender: R2 delete-by-prefix had ${deleted.Errors.length} per-object failure(s) under ${prefix} — swept later by the lifecycle rule:`,
            deleted.Errors,
          );
          allSucceeded = false;
        }
      }
      continuationToken = listed.IsTruncated ? listed.NextContinuationToken : undefined;
    } while (continuationToken);
    return allSucceeded;
  } catch (error) {
    console.error(`prerender: R2 delete-by-prefix failed for ${prefix} — continuing:`, error);
    return false;
  }
}
