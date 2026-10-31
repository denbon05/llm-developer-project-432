# Generation evaluation: starter set, full

- Date: 2026-10-31 · Cases: 4 of 4
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation full=1`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                         |
|----------------------------------------|-------------------------------|
| Characteristics matched                | 19/27 (0.70)                  |
| Wrong values                           | 1                             |
| Correct citations                      | 3/3 (1.00)                    |
| Cards with all citations correct       | 2/2                           |
| Claims supported (judge)               | 63/65 (0.97)                  |
| Cards judged                           | 4/4                           |
| Listed as missing but in the documents | 0                             |
| Truly missing listed                   | 5/5                           |
| Cards without forbidden text           | 2/2                           |
| Per card, average                      | $0.0015 · 1m 13s · 2.0 rounds |

## Cases

| Case             | Result                                         | Quality                                                   | Missing fields                   | Cost · time      |
|------------------|------------------------------------------------|-----------------------------------------------------------|----------------------------------|------------------|
| blender_passport | awaiting_approval · 2 rounds · confidence 0.92 | 10/12 matched · 2/2 cited · 19/20 supported               | none expected · 0 wrongly listed | $0.0017 · 1m 21s |
| blender_kp       | needs_review · 3 rounds · confidence 0.73      | 0/3 matched · 15/16 supported · 0/3 forbidden             | none expected · 0 wrongly listed | $0.0024 · 1m 54s |
| kettle_spec      | needs_review · 2 rounds · confidence 0.6       | 0/3 matched · 13/13 supported                             | 3/3 listed · 0 wrongly listed    | $0.0012 · 1m 0s  |
| kettle_manual    | needs_review · 1 round · confidence 0.75       | 9/9 matched · 1/1 cited · 16/16 supported · 0/3 forbidden | 2/2 listed · 0 wrongly listed    | $0.0006 · 0m 35s |

## Documents that must be rejected

- boiler_scan.pdf: rejected as expected (UnreadableDocumentError: the PDF has no text layer; it may be a scan, and OCR is not supported)

## Errors

### blender_passport

- Absent: Турбо-режим
- Wrong value: Гарантия «24 месяца с даты продажи», expected «24 месяца»
- Unsupported: benefit «Обеспечивает высокую производительность благодаря мощности 800 Вт.» (While the power is mentioned, the sources do not explicitly state that this power ensures high productivity.)

### blender_kp

- Absent: BLD-500
- Absent: BLD-800
- Absent: BLD-1200
- Unsupported: description «Все модели сертифицированы ЕАЭС, что подтверждает их соответствие стандартам качества.» (The sources state that the models are EAC certified but do not elaborate on this confirming quality standards.)

### kettle_spec

- Absent: KTL-1700
- Absent: KTL-1000
- Absent: KTL-THRM

## Cost by model

| Model              | Purpose          | Calls | Tokens in | Tokens out | Cost    |
|--------------------|------------------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique         | 8     | 12725     | 784        | $0.0027 |
| gemma-4-e4b-it-mlx | detect_injection | 1     | 292       | 28         | $0.0001 |
| gemma-4-e4b-it-mlx | generate         | 8     | 11873     | 4187       | $0.0032 |
