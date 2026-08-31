# Rejected Mutation 001: candidate-005

- Failure pattern: repeated `TARGET_TEST_FAILED` runs with multiple patch attempts.
- Mutation: `max_react_steps: 20 -> 15` from `policy-v002`.
- Hypothesis: a tighter budget could encourage earlier test inspection and more deliberate patches.
- Validation: 18/18 valid pairwise attempts under matched conditions; resolution declined from 6/9 to 5/9.
- Decision: rejected because efficiency cannot override a resolution regression.
- Champion remained: `policy-v002`.

Source: `evolution/evolution-v1/candidate-005/pairwise-report.json`.
