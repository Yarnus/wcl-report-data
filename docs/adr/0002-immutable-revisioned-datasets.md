# Keep completed datasets immutable by report revision

Report indexes and Fight Bundles are stored under the WCL report revision that produced them, while a separate pointer identifies the latest revision. Re-exporting a report creates a new dataset rather than overwriting old evidence, trading disk space for reproducible downstream review.
