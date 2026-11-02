# Generation evaluation: subset

- Date: 2026-11-02 · Cases: 4 of 9
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                         |
|----------------------------------------|-------------------------------|
| Characteristics matched                | 36/42 (0.86)                  |
| Wrong values                           | 0                             |
| Correct citations                      | 36/36 (1.00)                  |
| Cards with all citations correct       | 4/4                           |
| Claims supported (judge)               | 71/71 (1.00)                  |
| Cards judged                           | 4/4                           |
| Listed as missing but in the documents | 1                             |
| Truly missing listed                   | 2/2                           |
| Cards without forbidden text           | 1/1                           |
| Per card, average                      | $0.0010 · 0m 47s · 1.5 rounds |

## Cases

| Case           | Result                                        | Quality                                                   | Missing fields                   | Cost · time      |
|----------------|-----------------------------------------------|-----------------------------------------------------------|----------------------------------|------------------|
| fan-40-en      | awaiting_approval · 2 rounds · confidence 1.0 | 13/15 matched · 13/13 cited · 21/21 supported             | none expected · 0 wrongly listed | $0.0015 · 1m 19s |
| blender-800-ru | needs_review · 2 rounds · confidence 0.57     | 3/4 matched · 3/3 cited · 11/11 supported                 | none expected · 0 wrongly listed | $0.0012 · 0m 45s |
| coffee-1000-ru | awaiting_approval · 1 round · confidence 0.93 | 13/14 matched · 13/13 cited · 21/21 supported             | none expected · 1 wrongly listed | $0.0007 · 0m 34s |
| kettle-1700-en | needs_review · 1 round · confidence 0.77      | 7/9 matched · 7/7 cited · 18/18 supported · 0/3 forbidden | 2/2 listed · 0 wrongly listed    | $0.0006 · 0m 30s |

## Errors

### fan-40-en

- Absent: SKU
- Absent: Sleep timer

### blender-800-ru

- Absent: Артикул

### coffee-1000-ru

- Absent: Комплект поставки
- Listed as missing but in the documents: Комплектация

### kettle-1700-en

- Absent: Model
- Absent: SKU

## Cost by model

| Model              | Purpose          | Calls | Tokens in | Tokens out | Cost    |
|--------------------|------------------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique         | 6     | 9118      | 266        | $0.0019 |
| gemma-4-e4b-it-mlx | detect_injection | 1     | 277       | 32         | $0.0001 |
| gemma-4-e4b-it-mlx | generate         | 6     | 7632      | 2829       | $0.0021 |
