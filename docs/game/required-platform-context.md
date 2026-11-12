# Integration hardening request: trusted event context

The public generic platform event endpoint must not let a browser copy a legitimate signed game payload to another owner's otherwise identical initial world and reuse its `mode=real` label without a corresponding model audit. The signature already rejects modified tools and obvious unsigned writes, but its provenance needs an owner/save/branch binding.

Requested coordinated platform change (only after public `EventProposal` validation, in `Store.append_event`):

```python
self.rules.check('game', current['state'], proposal['state'], proposal | {
    '_context': {'owner_id': owner, 'save_id': save_id, 'branch_id': branch_id}
})
```

`EventProposal.additionalProperties=false` prevents a browser supplying `_context`. This is internal validation context, not a public schema change or a persisted event field. The game can then include the binding in its signed payload and reject any mismatch. Parent coordinates `store.py` ownership with the plans line; the game line does not independently modify that shared file.
