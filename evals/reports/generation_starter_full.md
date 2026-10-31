# Generation evaluation: starter set, full

- Date: 2026-10-31 · Cases: 4 of 4
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation full=1`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                        |
|----------------------------------------|------------------------------|
| Characteristics matched                | 19/27 (0.70)                 |
| Wrong values                           | 1                            |
| Correct citations                      | 3/3 (1.00)                   |
| Cards with all citations correct       | 2/2                          |
| Claims supported (judge)               | 58/63 (0.92)                 |
| Cards judged                           | 4/4                          |
| Listed as missing but in the documents | 0                            |
| Truly missing listed                   | 5/5                          |
| Cards without forbidden text           | 2/2                          |
| Per card, average                      | $0.0013 · 1m 5s · 1.8 rounds |

## Cases

| Case             | Result                                        | Quality                                                   | Missing fields                   | Cost · time      |
|------------------|-----------------------------------------------|-----------------------------------------------------------|----------------------------------|------------------|
| blender_passport | awaiting_approval · 1 round · confidence 0.92 | 10/12 matched · 2/2 cited · 20/20 supported               | none expected · 0 wrongly listed | $0.0008 · 0m 37s |
| blender_kp       | awaiting_approval · 3 rounds · confidence 0.7 | 0/3 matched · 13/14 supported · 0/3 forbidden             | none expected · 0 wrongly listed | $0.0025 · 1m 56s |
| kettle_spec      | needs_review · 1 round · confidence 0.6       | 0/3 matched · 9/13 supported                              | 3/3 listed · 0 wrongly listed    | $0.0005 · 0m 27s |
| kettle_manual    | needs_review · 2 rounds · confidence 0.75     | 9/9 matched · 1/1 cited · 16/16 supported · 0/3 forbidden | 2/2 listed · 0 wrongly listed    | $0.0015 · 1m 21s |

## Documents that must be rejected

- boiler_scan.pdf: rejected as expected (UnreadableDocumentError: the PDF has no text layer; it may be a scan, and OCR is not supported)

## Errors

### blender_passport

- Wrong value: Гарантия «24 месяца с даты продажи», expected «24 месяца»
- Absent: Страна-производитель

### blender_kp

- Absent: BLD-500
- Absent: BLD-800
- Absent: BLD-1200
- Unsupported: benefit «Предлагается линейка моделей с разной мощностью под разные нужды покупателей.» (While different powers are offered, the claim adds a subjective benefit about suitability for various needs.)

### kettle_spec

- Absent: KTL-1700
- Absent: KTL-1000
- Absent: KTL-THRM
- Unsupported: benefit «Большой объём 1,7 л подходит для нужд семьи.» (The sources state the volume but do not claim it suits family needs.)
- Unsupported: benefit «Высокая мощность 2200 Вт обеспечивает быстрое закипание воды.» (The sources state the power but do not claim it ensures fast boiling.)
- Unsupported: benefit «Надёжная конструкция из стали и пластика.» (The sources mention the materials but do not claim a reliable construction.)
- Unsupported: description «Он изготовлен из нержавеющей стали и пластика.» (The sources mention steel and plastic but do not specify that the material is stainless steel.)

## Cost by model

| Model              | Purpose          | Calls | Tokens in | Tokens out | Cost    |
|--------------------|------------------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique         | 7     | 10974     | 838        | $0.0024 |
| gemma-4-e4b-it-mlx | detect_injection | 1     | 292       | 28         | $0.0001 |
| gemma-4-e4b-it-mlx | generate         | 7     | 10161     | 3625       | $0.0028 |
