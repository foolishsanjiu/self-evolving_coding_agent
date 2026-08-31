# Accepted Mutation 001: candidate-004

- Failure pattern: repeated `TARGET_TEST_FAILED` runs after early edits and limited recovery budget.
- Mutation: `max_react_steps: 15 -> 20` from `policy-v001`.
- Hypothesis: a larger step budget could give the agent enough room to inspect tests and recover.
- Validation: 18/18 valid pairwise attempts under matched conditions; resolution improved from 4/9 to 6/9.
- Decision: accepted because resolution improved, despite higher token and step cost.
- Promoted policy: `policy-v002`.

Source: `evolution/evolution-v1/candidate-004/pairwise-report.json`.
