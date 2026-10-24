# Generation evaluation: subset

- Date: 2026-10-24 · Cases: 3 of 8
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                         |
|----------------------------------------|-------------------------------|
| Characteristics matched                | 28/33 (0.85)                  |
| Wrong values                           | 0                             |
| Correct citations                      | 28/28 (1.00)                  |
| Cards with all citations correct       | 3/3                           |
| Claims supported (judge)               | 53/53 (1.00)                  |
| Cards judged                           | 3/3                           |
| Listed as missing but in the documents | 1                             |
| Truly missing listed                   | -                             |
| Per card, average                      | $0.0009 · 0m 43s · 1.3 rounds |

## Cases

| Case           | Status            | Rounds | Confidence | Matched | Citations | Supported | Missing but present | Truly missing | Cost    | Time   |
|----------------|-------------------|--------|------------|---------|-----------|-----------|---------------------|---------------|---------|--------|
| fan-40-en      | awaiting_approval | 1      | 0.92       | 12/15   | 12/12     | 21/21     | 1                   | -             | $0.0006 | 0m 32s |
| blender-800-ru | needs_review      | 1      | 0.67       | 3/4     | 3/3       | 11/11     | 0                   | -             | $0.0005 | 0m 20s |
| coffee-1000-ru | awaiting_approval | 2      | 0.93       | 13/14   | 13/13     | 21/21     | 0                   | -             | $0.0016 | 1m 16s |

## Errors

### fan-40-en

- Absent: SKU
- Absent: Sleep timer
- Absent: Package contents
- Listed as missing but in the documents: package contents

### blender-800-ru

- Absent: Артикул

### coffee-1000-ru

- Absent: Комплект поставки

## Cost by model

| Model              | Purpose  | Calls | Tokens in | Tokens out | Cost    |
|--------------------|----------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique | 4     | 6611      | 145        | $0.0014 |
| gemma-4-e4b-it-mlx | generate | 4     | 5179      | 2107       | $0.0015 |
