# Accepted Mutation 002: candidate-006

- Failure pattern: repeated late reactive patch attempts suggested edit/verify thrashing.
- Mutation: `max_react_steps: 20 -> 10` from `policy-v002`.
- Hypothesis: a tighter step budget could reduce unproductive late-stage work.
- Validation: 18/18 valid pairwise attempts under matched conditions; both arms resolved 6/9.
- Cost effect: average tokens fell from 40,251.11 to 28,914.00, steps from 10.89 to 9.22, and tool calls from 12.89 to 11.22.
- Decision: accepted because resolution tied while tokens and corroborating cost metrics improved by at least 10%.
- Promoted policy: `policy-v003`.

Source: `evolution/evolution-v1/candidate-006/pairwise-report.json`.
