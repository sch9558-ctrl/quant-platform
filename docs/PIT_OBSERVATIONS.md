# Point-in-Time observation revision policy

The ResearchDB stores externally observed facts as immutable public releases.

## Identity

A release id is derived from observation_type, source, market, symbol, and published_at.

- A later public release for the same logical observation is a normal revision and is stored as another row.
- Re-inserting the same logical observation at the same published_at is a duplicate and raises DuplicateObservationError.
- Callers do not invent observation ids.

## Historical queries

Historical-safe queries use published_at <= as_of. Later revisions never leak backward into an earlier replay.

## Corrections and restatements

Corrections never delete or mutate the original row.

1. Keep the original public release unchanged.
2. Insert the corrected release with its own later published_at.
3. Record lineage in provenance, for example correction_of, revision_of, source document id, and correction reason.
4. Replays before the correction continue to see the original release.
5. Replays after the correction see the corrected release.

If a provider silently mutates historical content without a defensible new publication timestamp, the collector must not overwrite the stored release. It should fail closed until a publication or correction timestamp can be established.
