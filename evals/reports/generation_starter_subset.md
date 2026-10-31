# Generation evaluation: starter set, subset

- Date: 2026-10-31 · Cases: 2 of 4
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                         |
|----------------------------------------|-------------------------------|
| Characteristics matched                | 20/21 (0.95)                  |
| Wrong values                           | 0                             |
| Correct citations                      | 3/3 (1.00)                    |
| Cards with all citations correct       | 2/2                           |
| Claims supported (judge)               | 37/38 (0.97)                  |
| Cards judged                           | 2/2                           |
| Listed as missing but in the documents | 1                             |
| Truly missing listed                   | 2/2                           |
| Cards without forbidden text           | 1/1                           |
| Per card, average                      | $0.0007 · 0m 41s · 1.0 rounds |

## Cases

| Case             | Result                                        | Quality                                                   | Missing fields                   | Cost · time      |
|------------------|-----------------------------------------------|-----------------------------------------------------------|----------------------------------|------------------|
| blender_passport | awaiting_approval · 1 round · confidence 0.92 | 11/12 matched · 2/2 cited · 20/21 supported               | none expected · 1 wrongly listed | $0.0008 · 0m 49s |
| kettle_manual    | needs_review · 1 round · confidence 0.75      | 9/9 matched · 1/1 cited · 17/17 supported · 0/3 forbidden | 2/2 listed · 0 wrongly listed    | $0.0006 · 0m 32s |

## Documents that must be rejected

- boiler_scan.pdf: rejected as expected (UnreadableDocumentError: the PDF has no text layer; it may be a scan, and OCR is not supported)

## Errors

### blender_passport

- Absent: Страна-производитель
- Listed as missing but in the documents: Страна-производитель
- Unsupported: benefit «Обеспечивает универсальность благодаря 6 скоростям и турбо-режиму.» (While the sources mention 6 speeds and turbo mode, they do not explicitly state that these features ensure versatility.)

## Cost by model

| Model              | Purpose          | Calls | Tokens in | Tokens out | Cost    |
|--------------------|------------------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique         | 2     | 3376      | 26         | $0.0007 |
| gemma-4-e4b-it-mlx | detect_injection | 1     | 292       | 28         | $0.0001 |
| gemma-4-e4b-it-mlx | generate         | 2     | 2081      | 1210       | $0.0007 |
