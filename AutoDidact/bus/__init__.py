"""bus — the shared plumbing of AutoDidact.

Every stage used to carry its own HTTP client, its own endpoint default, its own
retry loop and its own verdict parser; a dataset was addressed by a path copied
into five modules. The bus replaces that:

    config   roles, endpoints, decoding params, artifact paths (one place)
    llm      the ONLY code that speaks HTTP to a model (chat / judge / embed)
    registry named, hashed datasets instead of path constants        [P2]
    pipeline one entry point with a DAG and --resume                 [P2]
    round    the release record (promote/rollback + provenance)      [P3]

Import it as `from bus import llm, config`.
"""
