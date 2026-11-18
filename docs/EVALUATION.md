# Importing structured observations

No automatic connection to an external product is claimed. Transcribe authorised observations into JSON:

```json
{
  "provenance": "Tool name, test date, original output reference, transcription method",
  "observations": [
    {
      "quote_id": "Q0001",
      "contract_ex_gst_cents": 10000000,
      "gst_cents": 1000000,
      "optional_ex_gst_cents": 0,
      "deposit_cents": 3300000,
      "flags": [{"kind": "excluded", "scope_item_id": "MB03"}]
    }
  ]
}
```

The figures above illustrate the schema only; they are not the ground truth for Q0001. Run:

```sh
python3 -m earthworks.evaluate observations.json
```

Missing numeric fields count as incorrect. Missing commercially material flags are counted as false negatives by quote and canonical scope item. Metrics show denominators. Semantic judgment is separate and is not performed by this deterministic evaluator. `--demo` creates a deliberately flawed synthetic transcription to exercise failure reporting.

## Question-policy evaluation

The current planner computes an illustrative sensitivity score, not a learned expected value of information. Next validation should compare it with sensible fixed sequences (including an experienced estimator's preferred order) on held-out cases. Measure questions asked, estimate range width, whether the range covers the eventual comparable award, time to a reviewable scope and requests for unjustified certainty. Do not train and test on the same synthetic price-generation rules and call the result real predictive accuracy.
