# Generation evaluation: subset

- Date: 2026-10-26 · Cases: 3 of 8
- Main model: gemma-4-e4b-it-mlx · Cheap model: gemma-4-e4b-it-mlx · Judge model: gemma-4-e4b-it-mlx
- Prices, USD per 1M tokens (input / output): gemma-4-e4b-it-mlx 0.20 / 0.20

Written by `make eval-generation`. One run per case: a case can change by several values between runs with no change in code, so compare the totals, not single cases.

## Summary

| Metric                                 | Value                         |
|----------------------------------------|-------------------------------|
| Characteristics matched                | 27/33 (0.82)                  |
| Wrong values                           | 0                             |
| Correct citations                      | 27/27 (1.00)                  |
| Cards with all citations correct       | 3/3                           |
| Claims supported (judge)               | 49/51 (0.96)                  |
| Cards judged                           | 3/3                           |
| Listed as missing but in the documents | 1                             |
| Truly missing listed                   | -                             |
| Per card, average                      | $0.0012 · 0m 57s · 1.7 rounds |

## Cases

| Case           | Status            | Rounds | Confidence | Matched | Citations | Supported | Missing but present | Truly missing | Cost    | Time   |
|----------------|-------------------|--------|------------|---------|-----------|-----------|---------------------|---------------|---------|--------|
| fan-40-en      | needs_review      | 3      | 0.93       | 12/15   | 12/12     | 21/21     | 0                   | -             | $0.0024 | 1m 53s |
| blender-800-ru | needs_review      | 1      | 0.67       | 3/4     | 3/3       | 10/11     | 0                   | -             | $0.0005 | 0m 23s |
| coffee-1000-ru | awaiting_approval | 1      | 0.92       | 12/14   | 12/12     | 18/19     | 1                   | -             | $0.0007 | 0m 34s |

## Errors

### fan-40-en

- Absent: SKU
- Absent: Sleep timer
- Absent: Package contents

### blender-800-ru

- Absent: Артикул
- Unsupported: benefit «Надежная мощность 800 Вт для ваших нужд» (The sources mention the 800 W power but do not make a claim about its reliability or suitability for needs.)

### coffee-1000-ru

- Absent: Таймер
- Absent: Комплект поставки
- Listed as missing but in the documents: Комплект поставки
- Unsupported: benefit «Колба выполнена из термостекла для долговечности» (The sources mention the carafe is made of borosilicate glass but do not state that it is for durability.)

## Cost by model

| Model              | Purpose  | Calls | Tokens in | Tokens out | Cost    |
|--------------------|----------|-------|-----------|------------|---------|
| gemma-4-e4b-it-mlx | critique | 5     | 8183      | 250        | $0.0017 |
| gemma-4-e4b-it-mlx | generate | 5     | 6963      | 2537       | $0.0019 |
