# Generation evaluation: full

- Date: 2026-10-24 · Cases: 8 of 8
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation full=1`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                        |
|----------------------------------------|------------------------------|
| Characteristics matched                | 58/74 (0.78)                 |
| Wrong values                           | 1                            |
| Correct citations                      | 59/59 (1.00)                 |
| Cards with all citations correct       | 8/8                          |
| Claims supported (judge)               | 127/127 (1.00)               |
| Cards judged                           | 8/8                          |
| Listed as missing but in the documents | 2                            |
| Truly missing listed                   | 5/19                         |
| Per card, average                      | $0.0013 · 1m 0s · 2.1 rounds |

## Cases

| Case            | Status            | Rounds | Confidence | Matched | Citations | Supported | Missing but present | Truly missing | Cost    | Time   |
|-----------------|-------------------|--------|------------|---------|-----------|-----------|---------------------|---------------|---------|--------|
| fan-40-en       | awaiting_approval | 1      | 0.93       | 13/15   | 13/13     | 22/22     | 1                   | -             | $0.0007 | 0m 33s |
| fan-45-en       | awaiting_approval | 1      | 0.93       | 13/13   | 13/13     | 22/22     | 0                   | 1/1           | $0.0006 | 0m 33s |
| vacuum-180-en   | awaiting_approval | 3      | 1.0        | 10/14   | 10/10     | 18/18     | 0                   | -             | $0.0023 | 1m 34s |
| vacuum-210-en   | needs_review      | 2      | 0.67       | 5/6     | 5/5       | 13/13     | 0                   | 3/8           | $0.0010 | 0m 59s |
| blender-800-ru  | needs_review      | 3      | 0.67       | 3/4     | 3/3       | 11/11     | 0                   | -             | $0.0019 | 1m 24s |
| blender-500-en  | needs_review      | 3      | 0.67       | 2/4     | 2/2       | 11/11     | 0                   | -             | $0.0016 | 1m 3s  |
| coffee-1000-ru  | awaiting_approval | 1      | 0.91       | 10/14   | 10/10     | 18/18     | 1                   | -             | $0.0007 | 0m 33s |
| fan-40-offer-en | needs_review      | 3      | 0.83       | 2/4     | 3/3       | 12/12     | 0                   | 1/10          | $0.0019 | 1m 23s |

## Errors

### fan-40-en

- Absent: Sleep timer
- Absent: Package contents
- Listed as missing but in the documents: package contents

### vacuum-180-en

- Absent: Model
- Absent: SKU
- Absent: Brand
- Absent: Package contents

### vacuum-210-en

- Absent: SKU
- Truly missing not listed: Cleaning type
- Truly missing not listed: Battery runtime
- Truly missing not listed: Filter
- Truly missing not listed: Power supply
- Truly missing not listed: Package contents

### blender-800-ru

- Absent: Артикул

### blender-500-en

- Absent: Model
- Absent: SKU

### coffee-1000-ru

- Absent: Артикул
- Absent: Таймер
- Absent: Питание
- Absent: Комплект поставки
- Listed as missing but in the documents: Комплект поставки

### fan-40-offer-en

- Wrong value: Model «FAN-40», expected «VentBriz 40»
- Absent: SKU
- Truly missing not listed: Blade diameter
- Truly missing not listed: Controls
- Truly missing not listed: Speeds
- Truly missing not listed: Oscillation
- Truly missing not listed: Sleep timer
- Truly missing not listed: Power supply
- Truly missing not listed: Weight
- Truly missing not listed: Warranty
- Truly missing not listed: Package contents

## Cost by model

| Model              | Purpose  | Calls | Tokens in | Tokens out | Cost    |
|--------------------|----------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique | 17    | 23199     | 1356       | $0.0049 |
| gemma-4-e4b-it-mlx | generate | 17    | 21790     | 6818       | $0.0057 |
