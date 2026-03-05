# Billing / Cost Tracking

Spikee includes a billing and cost tracking system to help users monitor their LLM usage and associated costs.

## Usage

Run the `spikee init --include-billing` command, to create a `billing.json` file within your workspace. 

This file will contain the cost and token usage of tracked models, and will be updated when Spikee is used (only applies to LLM usage through the built-in LLM utility).

Currently only the following model prefixes are supported:
- `bedrock-`
- `bedrockcv-`
- `google-`
- `openai-`

## Configuration
```json
{
  "total_cost": 0,
  "models": {
    "bedrock-us.anthropic.claude-3-7-sonnet-20250219-v1:0": {
      "update_notes": "2026-03-05 | us-east-2",
      "input_cost": 3.0,
      "output_cost": 15.0,
      "input_tokens": 0,
      "output_tokens": 0
    },
  }
}
```

- `total_cost`: The cumulative cost of all LLM usage tracked by Spikee.
- `models`: A dictionary where each key is a model name and the value contains:
  - `update_notes`: Metadata about the last update.
  - `input_cost`: The cost per 1 million input tokens for that model.
  - `output_cost`: The cost per 1 million output tokens for that model.
  - `input_tokens`: The total number of input tokens used for that model.
  - `output_tokens`: The total number of output tokens generated for that model.
