# Evaluate raid mechanics from ephemeral filtered evidence

Mechanic Review is the narrow exception to ADR 0003's Complete Bundle-only coaching path. It collects one completed Boss Attempt through a ruleset-derived WCL server filter, keeps the resulting Mechanic Evidence Set only in process memory, and verifies the Report Revision after complete pagination. This avoids persisting a second event representation while trading away resumability, hashes, and reproducibility after the process exits. Personal Reviews, benchmarks, and guides continue to require Complete Bundles.

A later presentation step may persist a validated Report Document and self-contained HTML. That artifact contains only selected conclusions, counts, and flat minimal evidence excerpts. It must not contain or reconstruct the complete Mechanic Evidence Set, so this does not introduce a second persistent event representation.
