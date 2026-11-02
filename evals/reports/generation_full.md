# Generation evaluation: full

- Date: 2026-11-02 · Cases: 9 of 9
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation full=1`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                         |
|----------------------------------------|-------------------------------|
| Characteristics matched                | 59/83 (0.71)                  |
| Wrong values                           | 0                             |
| Correct citations                      | 59/59 (1.00)                  |
| Cards with all citations correct       | 9/9                           |
| Claims supported (judge)               | 126/131 (0.96)                |
| Cards judged                           | 9/9                           |
| Listed as missing but in the documents | 2                             |
| Truly missing listed                   | 10/21                         |
| Cards without forbidden text           | 2/2                           |
| Per card, average                      | $0.0010 · 0m 48s · 1.6 rounds |

## Cases

| Case            | Result                                         | Quality                                                   | Missing fields                   | Cost · time      |
|-----------------|------------------------------------------------|-----------------------------------------------------------|----------------------------------|------------------|
| fan-40-en       | awaiting_approval · 2 rounds · confidence 0.92 | 12/15 matched · 12/12 cited · 20/20 supported             | none expected · 1 wrongly listed | $0.0015 · 1m 3s  |
| fan-45-en       | awaiting_approval · 1 round · confidence 0.93  | 12/13 matched · 12/12 cited · 21/21 supported             | 1/1 listed · 0 wrongly listed    | $0.0006 · 0m 35s |
| vacuum-180-en   | awaiting_approval · 1 round · confidence 0.91  | 10/14 matched · 10/10 cited · 18/18 supported             | none expected · 0 wrongly listed | $0.0007 · 0m 32s |
| vacuum-210-en   | needs_review · 1 round · confidence 0.6        | 5/6 matched · 5/5 cited · 10/13 supported                 | 4/8 listed · 0 wrongly listed    | $0.0004 · 0m 21s |
| blender-800-ru  | needs_review · 1 round · confidence 0.44       | 3/4 matched · 3/3 cited · 11/11 supported                 | none expected · 0 wrongly listed | $0.0005 · 0m 23s |
| blender-500-en  | needs_review · 3 rounds · confidence 0.5       | 3/4 matched · 3/3 cited · 10/10 supported · 0/3 forbidden | none expected · 0 wrongly listed | $0.0016 · 1m 9s  |
| coffee-1000-ru  | awaiting_approval · 1 round · confidence 0.83  | 5/14 matched · 5/5 cited · 12/13 supported                | none expected · 1 wrongly listed | $0.0007 · 0m 49s |
| fan-40-offer-en | needs_review · 3 rounds · confidence 0.43      | 2/4 matched · 2/2 cited · 10/10 supported                 | 3/10 listed · 0 wrongly listed   | $0.0021 · 1m 49s |
| kettle-1700-en  | needs_review · 1 round · confidence 0.73       | 7/9 matched · 7/7 cited · 14/15 supported · 0/3 forbidden | 2/2 listed · 0 wrongly listed    | $0.0006 · 0m 29s |

## Errors

### fan-40-en

- Absent: SKU
- Absent: Sleep timer
- Absent: Package contents
- Listed as missing but in the documents: package contents

### fan-45-en

- Absent: Model

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
- Unsupported: characteristic «Power supply: Not specified» (The sources specify the power but do not mention anything about the power supply being unspecified.)
- Unsupported: benefit «Powerful 550W motor for effective cleaning.» (The sources state the power but do not claim it is a powerful motor for effective cleaning.)
- Unsupported: description «It features a powerful 550W motor to handle your cleaning tasks effectively.» (The sources state the power but do not describe it as a powerful motor for effective cleaning.)

### blender-800-ru

- Absent: Артикул

### blender-500-en

- Absent: SKU

### coffee-1000-ru

- Absent: Колба
- Absent: Плита подогрева
- Absent: Таймер
- Absent: Питание
- Absent: Вес
- Absent: Цвет
- Absent: Гарантия
- Absent: Страна-производитель
- Absent: Комплект поставки
- Listed as missing but in the documents: Комплект поставки
- Unsupported: benefit «Имеет многоразовый фильтр, что удобно и экологично.» (While the sources mention it has a reusable filter, they do not state that this is convenient or ecological.)

### fan-40-offer-en

- Absent: Model
- Absent: SKU
- Truly missing not listed: Blade diameter
- Truly missing not listed: Controls
- Truly missing not listed: Speeds
- Truly missing not listed: Oscillation
- Truly missing not listed: Sleep timer
- Truly missing not listed: Power supply
- Truly missing not listed: Weight

### kettle-1700-en

- Absent: Model
- Absent: SKU
- Unsupported: benefit «High-power 2200W ensures fast boiling times.» (The sources mention the 2200W power but do not claim this ensures fast boiling times.)

## Cost by model

| Model              | Purpose          | Calls | Tokens in | Tokens out | Cost    |
|--------------------|------------------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique         | 14    | 18834     | 1440       | $0.0041 |
| gemma-4-e4b-it-mlx | detect_injection | 1     | 277       | 32         | $0.0001 |
| gemma-4-e4b-it-mlx | generate         | 14    | 17176     | 5671       | $0.0046 |
