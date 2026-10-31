# Generation evaluation: starter set, subset

- Date: 2026-10-31 · Cases: 2 of 4
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                         |
|----------------------------------------|-------------------------------|
| Characteristics matched                | 20/21 (0.95)                  |
| Wrong values                           | 1                             |
| Correct citations                      | 3/3 (1.00)                    |
| Cards with all citations correct       | 2/2                           |
| Claims supported (judge)               | 36/38 (0.95)                  |
| Cards judged                           | 2/2                           |
| Listed as missing but in the documents | 0                             |
| Truly missing listed                   | 1/2                           |
| Cards without forbidden text           | 1/1                           |
| Per card, average                      | $0.0007 · 0m 48s · 1.0 rounds |

## Cases

| Case             | Result                                        | Quality                                                   | Missing fields                   | Cost · time      |
|------------------|-----------------------------------------------|-----------------------------------------------------------|----------------------------------|------------------|
| blender_passport | awaiting_approval · 1 round · confidence 0.93 | 11/12 matched · 2/2 cited · 21/22 supported               | none expected · 0 wrongly listed | $0.0008 · 1m 3s  |
| kettle_manual    | needs_review · 1 round · confidence 0.75      | 9/9 matched · 1/1 cited · 15/16 supported · 0/3 forbidden | 1/2 listed · 0 wrongly listed    | $0.0006 · 0m 33s |

## Documents that must be rejected

- boiler_scan.pdf: rejected as expected (UnreadableDocumentError: the PDF has no text layer; it may be a scan, and OCR is not supported)

## Errors

### blender_passport

- Wrong value: Гарантия «24 месяца с даты продажи», expected «24 месяца»
- Unsupported: benefit «Наличие 6 скоростей и турбо-режима позволяет подобрать нужный режим для любой задачи.» (While the sources confirm 6 speeds and a turbo mode, they do not explicitly state that these features allow for selecting the right mode for any task.)

### kettle_manual

- Truly missing not listed: Страна-производитель
- Unsupported: benefit «Закрытая нагревательная спираль изготовлена из нержавеющей стали для долговечности.» (The sources mention the heating spiral is made of stainless steel but do not state this fact regarding its purpose for durability.)

## Cost by model

| Model              | Purpose          | Calls | Tokens in | Tokens out | Cost    |
|--------------------|------------------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique         | 2     | 3416      | 26         | $0.0007 |
| gemma-4-e4b-it-mlx | detect_injection | 1     | 292       | 28         | $0.0001 |
| gemma-4-e4b-it-mlx | generate         | 2     | 2081      | 1241       | $0.0007 |
