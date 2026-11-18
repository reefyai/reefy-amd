# Exact-subject publication recovery

After a successful OCI push, GHCR can temporarily return `not found` when
resolving the immutable subject for an SBOM. Publication now waits at most
60 seconds for that same digest and attaches the SBOM without repushing.
Authorization errors, mismatched digests and ambiguous command timeouts
stop publication. Signing and attestation still follow successful attachment.

Run the focused cases:

```sh
python3 -m unittest discover -s tests -p test_registry_attach.py -v
python3 -m unittest discover -s tests -p test_registry_workflow_visibility.py -v
```

Eight tests pass. The journey executes the actual workflow push step with a
synthetic registry that rejects the first subject read. Against the original
workflow (saved with `git show <baseline>:.github/workflows/publish.yml` and
selected through `REGISTRY_WORKFLOW_SOURCE`), that same journey fails on the
SBOM attachment. The fixed workflow makes one push, waits for the original
digest and attaches once. Unit cases also cover a second visibility race at
attachment, permanent absence, authorization failures, digest mismatch and
an ambiguous attachment timeout. No real registry writes occur in these tests.
