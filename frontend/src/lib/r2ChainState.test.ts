import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockSend = vi.fn();

function makeCommandClass(name: string) {
  return class {
    __command = name;
    input: unknown;
    constructor(input: unknown) {
      this.input = input;
    }
  };
}

vi.mock('@aws-sdk/client-s3', () => ({
  S3Client: class {
    send = mockSend;
  },
  GetObjectCommand: makeCommandClass('Get'),
  PutObjectCommand: makeCommandClass('Put'),
  ListObjectsV2Command: makeCommandClass('List'),
  DeleteObjectsCommand: makeCommandClass('Delete'),
}));

import { deleteR2ObjectsByPrefix, getR2Object, putR2Object } from './r2ChainState';

const ORIGINAL_ENV = { ...process.env };

function setR2Env(): void {
  process.env.CLOUDFLARE_ACCOUNT_ID = 'test-account';
  process.env.R2_ACCESS_KEY_ID = 'test-key-id';
  process.env.R2_SECRET_ACCESS_KEY = 'test-secret';
  process.env.R2_BUCKET_NAME = 'event-radar-prerender-chain-state';
}

describe('getR2Object', () => {
  beforeEach(() => {
    process.env = { ...ORIGINAL_ENV };
    mockSend.mockReset();
  });
  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it('returns null and never calls send when R2 credentials are unset (fail-open)', async () => {
    delete process.env.CLOUDFLARE_ACCOUNT_ID;
    delete process.env.R2_ACCESS_KEY_ID;
    delete process.env.R2_SECRET_ACCESS_KEY;

    const result = await getR2Object('prerender-chain-state/foo/index.json');

    expect(result).toBeNull();
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('returns null and never calls send when R2_BUCKET_NAME is unset', async () => {
    setR2Env();
    delete process.env.R2_BUCKET_NAME;

    const result = await getR2Object('prerender-chain-state/foo/index.json');

    expect(result).toBeNull();
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('returns the object body as a string on success', async () => {
    setR2Env();
    mockSend.mockResolvedValueOnce({
      Body: { transformToString: vi.fn().mockResolvedValue('{"a:1":{"resolvedAtRound":1}}') },
    });

    const result = await getR2Object('prerender-chain-state/foo/index.json');

    expect(result).toBe('{"a:1":{"resolvedAtRound":1}}');
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it('returns null when the underlying S3 call throws (treated as absent, never propagated)', async () => {
    setR2Env();
    mockSend.mockRejectedValueOnce(new Error('NoSuchKey'));

    const result = await getR2Object('prerender-chain-state/foo/index.json');

    expect(result).toBeNull();
  });
});

describe('putR2Object', () => {
  beforeEach(() => {
    process.env = { ...ORIGINAL_ENV };
    mockSend.mockReset();
  });
  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it('returns false and never calls send when R2 credentials are unset (fail-open)', async () => {
    delete process.env.R2_ACCESS_KEY_ID;

    const result = await putR2Object('prerender-chain-state/foo/index.json', '{}', 'application/json');

    expect(result).toBe(false);
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('writes the body/content-type and returns true on success', async () => {
    setR2Env();
    mockSend.mockResolvedValueOnce({});

    const result = await putR2Object('prerender-chain-state/foo/index.json', '{"a":1}', 'application/json');

    expect(result).toBe(true);
    expect(mockSend).toHaveBeenCalledTimes(1);
    const sentCommand = mockSend.mock.calls[0][0] as { __command: string; input: Record<string, unknown> };
    expect(sentCommand.__command).toBe('Put');
    expect(sentCommand.input).toMatchObject({
      Bucket: 'event-radar-prerender-chain-state',
      Key: 'prerender-chain-state/foo/index.json',
      Body: '{"a":1}',
      ContentType: 'application/json',
    });
  });

  it('returns false (never throws) when the underlying S3 call fails', async () => {
    setR2Env();
    mockSend.mockRejectedValueOnce(new Error('AccessDenied'));

    const result = await putR2Object('prerender-chain-state/foo/index.json', '{}', 'application/json');

    expect(result).toBe(false);
  });
});

describe('deleteR2ObjectsByPrefix', () => {
  beforeEach(() => {
    process.env = { ...ORIGINAL_ENV };
    mockSend.mockReset();
  });
  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it('returns false and never calls send when R2 credentials are unset (fail-open)', async () => {
    delete process.env.CLOUDFLARE_ACCOUNT_ID;

    const result = await deleteR2ObjectsByPrefix('prerender-chain-state/foo/');

    expect(result).toBe(false);
    expect(mockSend).not.toHaveBeenCalled();
  });

  it('lists then batch-deletes every found key and returns true', async () => {
    setR2Env();
    mockSend
      .mockResolvedValueOnce({
        Contents: [{ Key: 'prerender-chain-state/foo/index.json' }, { Key: 'prerender-chain-state/foo/targets/en-1.html' }],
        IsTruncated: false,
      })
      .mockResolvedValueOnce({});

    const result = await deleteR2ObjectsByPrefix('prerender-chain-state/foo/');

    expect(result).toBe(true);
    expect(mockSend).toHaveBeenCalledTimes(2);
    const listCommand = mockSend.mock.calls[0][0] as { __command: string };
    const deleteCommand = mockSend.mock.calls[1][0] as { __command: string; input: { Delete: { Objects: { Key: string }[] } } };
    expect(listCommand.__command).toBe('List');
    expect(deleteCommand.__command).toBe('Delete');
    expect(deleteCommand.input.Delete.Objects).toEqual([
      { Key: 'prerender-chain-state/foo/index.json' },
      { Key: 'prerender-chain-state/foo/targets/en-1.html' },
    ]);
  });

  it('skips the delete call entirely when the prefix has no objects', async () => {
    setR2Env();
    mockSend.mockResolvedValueOnce({ Contents: [], IsTruncated: false });

    const result = await deleteR2ObjectsByPrefix('prerender-chain-state/empty/');

    expect(result).toBe(true);
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it('pages through a truncated listing, deleting each page before requesting the next', async () => {
    setR2Env();
    mockSend
      .mockResolvedValueOnce({
        Contents: [{ Key: 'prerender-chain-state/foo/targets/en-1.html' }],
        IsTruncated: true,
        NextContinuationToken: 'token-2',
      })
      .mockResolvedValueOnce({}) // delete page 1
      .mockResolvedValueOnce({
        Contents: [{ Key: 'prerender-chain-state/foo/targets/en-2.html' }],
        IsTruncated: false,
      })
      .mockResolvedValueOnce({}); // delete page 2

    const result = await deleteR2ObjectsByPrefix('prerender-chain-state/foo/');

    expect(result).toBe(true);
    expect(mockSend).toHaveBeenCalledTimes(4);
    const secondListCommand = mockSend.mock.calls[2][0] as { __command: string; input: { ContinuationToken?: string } };
    expect(secondListCommand.__command).toBe('List');
    expect(secondListCommand.input.ContinuationToken).toBe('token-2');
  });

  it('returns false when the batch delete reports a per-object error, even though the call itself did not throw', async () => {
    setR2Env();
    mockSend
      .mockResolvedValueOnce({
        Contents: [{ Key: 'prerender-chain-state/foo/index.json' }, { Key: 'prerender-chain-state/foo/targets/en-1.html' }],
        IsTruncated: false,
      })
      .mockResolvedValueOnce({
        Deleted: [{ Key: 'prerender-chain-state/foo/index.json' }],
        Errors: [{ Key: 'prerender-chain-state/foo/targets/en-1.html', Code: 'InternalError' }],
      });

    const result = await deleteR2ObjectsByPrefix('prerender-chain-state/foo/');

    expect(result).toBe(false);
  });

  it('returns false (never throws) when the listing call fails', async () => {
    setR2Env();
    mockSend.mockRejectedValueOnce(new Error('AccessDenied'));

    const result = await deleteR2ObjectsByPrefix('prerender-chain-state/foo/');

    expect(result).toBe(false);
  });

  it('returns false (never throws) when a delete-batch call fails', async () => {
    setR2Env();
    mockSend
      .mockResolvedValueOnce({ Contents: [{ Key: 'prerender-chain-state/foo/index.json' }], IsTruncated: false })
      .mockRejectedValueOnce(new Error('AccessDenied'));

    const result = await deleteR2ObjectsByPrefix('prerender-chain-state/foo/');

    expect(result).toBe(false);
  });
});
