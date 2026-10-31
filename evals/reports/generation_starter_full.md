# Generation evaluation: starter set, full

- Date: 2026-10-31 · Cases: 4 of 4
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation full=1`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                         |
|----------------------------------------|-------------------------------|
| Characteristics matched                | 15/27 (0.56)                  |
| Wrong values                           | 1                             |
| Correct citations                      | 3/3 (1.00)                    |
| Cards with all citations correct       | 2/2                           |
| Claims supported (judge)               | 55/60 (0.92)                  |
| Cards judged                           | 4/4                           |
| Listed as missing but in the documents | 1                             |
| Truly missing listed                   | 5/5                           |
| Cards without forbidden text           | 2/2                           |
| Per card, average                      | $0.0010 · 0m 50s · 1.5 rounds |

## Cases

| Case             | Status            | Rounds | Confidence | Matched | Citations | Supported | Missing but present | Truly missing | Forbidden found | Cost    | Time   |
|------------------|-------------------|--------|------------|---------|-----------|-----------|---------------------|---------------|-----------------|---------|--------|
| blender_passport | awaiting_approval | 1      | 0.9        | 6/12    | 2/2       | 16/17     | 1                   | -             | -               | $0.0007 | 0m 35s |
| blender_kp       | needs_review      | 3      | 0.62       | 0/3     | -         | 14/14     | 0                   | -             | 0/3             | $0.0023 | 1m 42s |
| kettle_spec      | needs_review      | 1      | 0.5        | 0/3     | -         | 9/12      | 0                   | 3/3           | -               | $0.0005 | 0m 27s |
| kettle_manual    | needs_review      | 1      | 0.75       | 9/9     | 1/1       | 16/17     | 0                   | 2/2           | 0/3             | $0.0006 | 0m 36s |

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
- Unsupported: benefit «Наличие 6 скоростей и турбо-режима позволяет точно настроить процесс приготовления.» (While 6 speeds and a turbo mode are mentioned, the claim that they allow precise adjustment of the cooking process is an addition not stated in the sources.)

### blender_kp

- Absent: BLD-500
- Absent: BLD-800
- Absent: BLD-1200

### kettle_spec

- Absent: KTL-1700
- Absent: KTL-1000
- Absent: KTL-THRM
- Unsupported: benefit «Высокая мощность 2200 Вт обеспечивает быстрое закипание» (The sources state the power but do not claim that it ensures fast boiling.)
- Unsupported: benefit «Надёжное исполнение из стали и пластика» (The sources list the materials but do not make a claim about reliable execution.)
- Unsupported: description «Он изготовлен из нержавеющей стали и пластика.» (The sources mention steel/plastic but do not specify that the material is stainless steel.)

### kettle_manual

- Unsupported: benefit «Надежная конструкция с закрытой нагревательной спиралью.» (While the sources mention a closed heating spiral, they do not explicitly state that this constitutes a 'reliable construction.')

## Cost by model

| Model              | Purpose          | Calls | Tokens in | Tokens out | Cost    |
|--------------------|------------------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique         | 6     | 9316      | 414        | $0.0019 |
| gemma-4-e4b-it-mlx | detect_injection | 1     | 292       | 28         | $0.0001 |
| gemma-4-e4b-it-mlx | generate         | 6     | 7679      | 3009       | $0.0021 |
