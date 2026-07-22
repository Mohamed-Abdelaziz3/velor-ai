# Local artifact handling and public-repository boundary

VELOR currently has local runtime state beside its source tree. Those artifacts
are not source, are not safe to publish, and must not be deleted merely to make a
Git status look clean.

## Public-source allowlist

Source code, migrations, tests, reviewed documentation, safe `*.env.example`
files, and dependency lockfiles may enter version control after the hygiene gate
passes. The repository currently has no public license; publication does not
grant reuse rights until the owner selects one.

## Local-only classes

- `.env` and non-example environment files
- SQLite databases and their WAL/SHM companions
- WhatsApp QR session state
- logs, screenshots containing real data, and browser traces
- virtual environments, package installs, caches, and temporary test state
- provider credentials, service-account files, exports, and customer data

`.gitignore` is defense in depth, not a security boundary. Before any public
commit, run:

```powershell
python tools\check_repository_hygiene.py --inventory-local
```

The default mode scans all files Git would include. The optional inventory adds
aggregate local file counts and byte sizes while suppressing names and contents.

## Moving a sensitive artifact

Do not move or delete sessions, databases, logs, or user data during routine
repository cleanup. If relocation is later authorized:

1. Stop writers and record the exact source and approved destination privately.
2. Create a separate recoverable backup on an approved non-synced location.
3. Verify the backup by count, size, and cryptographic hashes without printing
   secret contents.
4. Copy first, validate application configuration against the copy, and only then
   obtain explicit authorization for removal of the original.
5. Record retention, access, restore test, and disposal decisions.

Because this working copy is under OneDrive, ignore rules do not stop cloud sync.
Moving runtime state out of the synced tree is a later operational decision and
requires the backup-and-authorization procedure above.

## Suspected exposure

Stop publication. Revoke or rotate the credential at its provider, preserve
minimal evidence privately, and inspect Git history and build logs. Removing a
value from the latest file does not invalidate an exposed credential.
