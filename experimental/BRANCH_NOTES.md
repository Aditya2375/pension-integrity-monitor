# Detection branch handoff

Owner scope: detection features, private model development, independent validation, identity matching, experimental/v3 and experimental/v4. Other branches own integration/, portal/, docs/ and bench/. Merge tested changes through the repository owner; do not change the frozen candidate during a blind run.

The V4 candidate at972d2b3 is awaiting a fresh blind round. It is not a production release. Private model weights and datasets are excluded. Review scores never authorize payment cancellation. All pension schemes are in design scope; testing does not establish scheme-wide coverage.

## Unfinished transferred prototypes

An offline CSV mapping adapter and eight tests were transferred separately for integration review. They are not part of the frozen detector. Open issues include atomic publication of output plus manifest, configuration validation, idempotency and sensitive-field policy.

A disk-backed CSV shard router was transferred separately for scale review. Measured25k-row shard aggregation peaks were319MB core and436MB activity. Global greedy identity ownership differs when computed independently in each shard: two review decisions differed from a full50k run. Resolve global ownership before claiming equivalent shard results. These small development measurements are not population-scale proof.

An adverse development scenario with greater missingness and more difficult populations reduced V4 accuracy. Development success does not establish blind accuracy. No claim of98/98, billion-record scale, government acceptance or legal compliance is made.
