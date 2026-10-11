# Search evaluation: ru

- Model: `intfloat/multilingual-e5-base`
- Query prefix: `query: `
- Chunk prefix: `passage: `
- Similarity threshold: 0.795
- Data: 9 indexed documents of evals/datasets/, 43 chunks

Written by `make eval-search lang=ru`. Ranks are positions within the top 20, with the threshold on; `-` means not found. Similarities are measured with the threshold off.

## Recall@5

Characteristic and SKU queries with an expected chunk in the top 5, with the threshold on.

| Mode | Characteristic | SKU | All |
|------|----------------|-----|-----|
| vector | 6/6 | 2/2 | 8/8 |
| keyword | 0/6 | 2/2 | 2/8 |
| hybrid | 6/6 | 2/2 | 8/8 |

## Threshold window

A threshold above the noise ceiling, and no higher than a relevant floor, keeps those answers and drops all noise.

| Measure | Similarity | Query |
|---------|------------|-------|
| Noise ceiling: highest top-1 of a noise query | 0.785 | рецепт борща |
| Relevant floor: lowest answer to a characteristic query | 0.798 | Как часто чистить кофеварку от накипи? |
| Relevant floor: lowest answer to a sku query | 0.846 | CFE-1000 |

## Characteristic and SKU queries

| Query | Kind | Vector | Keyword | Hybrid | Vector similarity | Above threshold |
|-------|------|--------|---------|--------|-------------------|-----------------|
| Какая мощность у блендера? | characteristic | 1 | - | 1 | 0.825 | yes |
| Какой объём у колбы кофеварки? | characteristic | 2 | - | 2 | 0.830 | yes |
| Сколько чашек кофе готовит кофеварка за раз? | characteristic | 1 | - | 1 | 0.861 | yes |
| Какая минимальная партия заказа блендеров? | characteristic | 1 | - | 1 | 0.821 | yes |
| Как часто чистить кофеварку от накипи? | characteristic | 2 | - | 2 | 0.798 | yes |
| Что входит в комплект кофеварки? | characteristic | 1 | - | 1 | 0.865 | yes |
| CFE-1000 | sku | 1 | 1 | 1 | 0.846 | yes |
| BLD-800 | sku | 2 | 2 | 2 | 0.850 | yes |

## Noise queries

How many chunks each mode returns with the threshold on, and the top chunk's similarity with it off.

| Query | Vector | Keyword | Hybrid | Top-1 vector similarity | Above threshold |
|-------|--------|---------|--------|-------------------------|-----------------|
| рецепт борща | 0 | 0 | 0 | 0.785 | no |
| прогноз погоды в Париже на завтра | 0 | 0 | 0 | 0.758 | no |
| разрешение экрана смартфона | 0 | 0 | 0 | 0.779 | no |
