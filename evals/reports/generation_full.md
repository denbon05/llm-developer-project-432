# Generation evaluation: full

- Date: 2026-10-26 · Cases: 8 of 8
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation full=1`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                         |
|----------------------------------------|-------------------------------|
| Characteristics matched                | 58/74 (0.78)                  |
| Wrong values                           | 1                             |
| Correct citations                      | 59/59 (1.00)                  |
| Cards with all citations correct       | 8/8                           |
| Claims supported (judge)               | 121/123 (0.98)                |
| Cards judged                           | 8/8                           |
| Listed as missing but in the documents | 1                             |
| Truly missing listed                   | 4/19                          |
| Per card, average                      | $0.0013 · 0m 59s · 2.0 rounds |

## Cases

| Case            | Status            | Rounds | Confidence | Matched | Citations | Supported | Missing but present | Truly missing | Cost    | Time   |
|-----------------|-------------------|--------|------------|---------|-----------|-----------|---------------------|---------------|---------|--------|
| fan-40-en       | awaiting_approval | 2      | 1.0        | 12/15   | 12/12     | 20/20     | 0                   | -             | $0.0015 | 1m 4s  |
| fan-45-en       | awaiting_approval | 1      | 0.92       | 11/13   | 11/11     | 19/19     | 0                   | 1/1           | $0.0006 | 0m 28s |
| vacuum-180-en   | awaiting_approval | 3      | 1.0        | 11/14   | 11/11     | 19/19     | 0                   | -             | $0.0024 | 1m 47s |
| vacuum-210-en   | needs_review      | 2      | 0.62       | 5/6     | 5/5       | 12/12     | 0                   | 3/8           | $0.0010 | 1m 0s  |
| blender-800-ru  | needs_review      | 1      | 0.67       | 3/4     | 3/3       | 12/12     | 0                   | -             | $0.0005 | 0m 26s |
| blender-500-en  | needs_review      | 3      | 0.5        | 2/4     | 2/2       | 9/10      | 0                   | -             | $0.0016 | 1m 13s |
| coffee-1000-ru  | awaiting_approval | 1      | 0.93       | 12/14   | 12/12     | 20/21     | 1                   | -             | $0.0007 | 0m 42s |
| fan-40-offer-en | needs_review      | 3      | 0.75       | 2/4     | 3/3       | 10/10     | 0                   | 0/10          | $0.0017 | 1m 10s |

## Errors

### fan-40-en

- Absent: SKU
- Absent: Sleep timer
- Absent: Package contents

### fan-45-en

- Absent: Model
- Absent: SKU

### vacuum-180-en

- Absent: Model
- Absent: SKU
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
- Unsupported: benefit «Equipped with 500W of power for blending tasks.» (While the power is mentioned, the sources do not explicitly state that this power is equipped for blending tasks.)

### coffee-1000-ru

- Absent: Таймер
- Absent: Комплект поставки
- Listed as missing but in the documents: Таймер
- Unsupported: benefit «Колба выполнена из термостекла для долговечности» (The sources mention the carafe is made of borosilicate glass but do not claim it is for durability.)

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
- Truly missing not listed: Country of origin
- Truly missing not listed: Package contents

## Cost by model

| Model              | Purpose  | Calls | Tokens in | Tokens out | Cost    |
|--------------------|----------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique | 16    | 22220     | 988        | $0.0046 |
| gemma-4-e4b-it-mlx | generate | 16    | 20504     | 6420       | $0.0054 |
