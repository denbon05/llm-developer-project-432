# Generation evaluation: starter set, subset

- Date: 2026-10-31 · Cases: 2 of 4
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                         |
|----------------------------------------|-------------------------------|
| Characteristics matched                | 14/21 (0.67)                  |
| Wrong values                           | 1                             |
| Correct citations                      | 3/3 (1.00)                    |
| Cards with all citations correct       | 2/2                           |
| Claims supported (judge)               | 30/32 (0.94)                  |
| Cards judged                           | 2/2                           |
| Listed as missing but in the documents | 1                             |
| Truly missing listed                   | 2/2                           |
| Cards without forbidden text           | 1/1                           |
| Per card, average                      | $0.0007 · 0m 34s · 1.0 rounds |

## Cases

| Case             | Status            | Rounds | Confidence | Matched | Citations | Supported | Missing but present | Truly missing | Forbidden found | Cost    | Time   |
|------------------|-------------------|--------|------------|---------|-----------|-----------|---------------------|---------------|-----------------|---------|--------|
| blender_passport | awaiting_approval | 1      | 0.9        | 6/12    | 2/2       | 16/17     | 1                   | -             | -               | $0.0007 | 0m 37s |
| kettle_manual    | needs_review      | 1      | 0.73       | 8/9     | 1/1       | 14/15     | 0                   | 2/2           | 0/3             | $0.0006 | 0m 31s |

## Documents that must be rejected

- boiler_scan.pdf: rejected as expected (UnreadableDocumentError: the PDF has no text layer; it may be a scan, and OCR is not supported)

## Errors

### blender_passport

- Absent: Артикул
- Absent: Турбо-режим
- Absent: Материал ножки
- Absent: Питание
- Wrong value: Гарантия «24 месяца с даты продажи», expected «24 месяца»
- Absent: Страна-производитель
- Listed as missing but in the documents: Страна-производитель
- Unsupported: benefit «Наличие 6 скоростей и турбо-режима обеспечивает широкий диапазон возможностей.» (While the sources mention 6 speeds and a turbo mode, they do not explicitly state that these features provide a wide range of possibilities.)

### kettle_manual

- Absent: Артикул
- Unsupported: benefit «Большой объем 1,7 л подходит для нужд большой семьи.» (While the volume is 1.7 L, the sources do not state that this size is suitable for a large family.)

## Cost by model

| Model              | Purpose          | Calls | Tokens in | Tokens out | Cost    |
|--------------------|------------------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique         | 2     | 3193      | 26         | $0.0006 |
| gemma-4-e4b-it-mlx | detect_injection | 1     | 292       | 28         | $0.0001 |
| gemma-4-e4b-it-mlx | generate         | 2     | 2001      | 1089       | $0.0006 |
