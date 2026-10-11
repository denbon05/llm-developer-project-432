# Search evaluation: en

- Model: `intfloat/multilingual-e5-base`
- Query prefix: `query: `
- Chunk prefix: `passage: `
- Similarity threshold: 0.795
- Data: 9 indexed documents of evals/datasets/, 43 chunks

Written by `make eval-search`. Ranks are positions within the top 20, with the threshold on; `-` means not found. Similarities are measured with the threshold off.

## Recall@5

Characteristic and SKU queries with an expected chunk in the top 5, with the threshold on.

| Mode | Characteristic | SKU | All |
|------|----------------|-----|-----|
| vector | 7/7 | 3/5 | 10/12 |
| keyword | 0/7 | 5/5 | 5/12 |
| hybrid | 7/7 | 5/5 | 12/12 |

## Threshold window

A threshold above the noise ceiling, and no higher than a relevant floor, keeps those answers and drops all noise.

| Measure | Similarity | Query |
|---------|------------|-------|
| Noise ceiling: highest top-1 of a noise query | 0.794 | How do I renew my car insurance? |
| Relevant floor: lowest answer to a characteristic query | 0.807 | What is the blender's power? |
| Relevant floor: lowest answer to a sku query | 0.782 | FAN-70 |

## Characteristic and SKU queries

| Query | Kind | Vector | Keyword | Hybrid | Vector similarity | Above threshold |
|-------|------|--------|---------|--------|-------------------|-----------------|
| What is the blender's power? | characteristic | 1 | - | 1 | 0.807 | yes |
| How long does the vacuum cleaner battery last? | characteristic | 1 | - | 1 | 0.836 | yes |
| How many speeds does the VentBriz 45 fan have? | characteristic | 1 | - | 1 | 0.890 | yes |
| minimum order quantity for blenders | characteristic | 2 | - | 2 | 0.820 | yes |
| What comes in the box with the vacuum cleaner? | characteristic | 1 | - | 1 | 0.828 | yes |
| How heavy is the VentBriz 40 fan? | characteristic | 1 | - | 1 | 0.907 | yes |
| What is not covered by the vacuum cleaner warranty? | characteristic | 3 | - | 3 | 0.829 | yes |
| FAN-50 | sku | - | 1 | 1 | 0.790 | no |
| FAN-35 | sku | 1 | 1 | 1 | 0.857 | yes |
| VCS-210 | sku | 1 | 1 | 1 | 0.849 | yes |
| BLD-1200 | sku | 1 | 1 | 1 | 0.866 | yes |
| FAN-70 | sku | - | 1 | 1 | 0.782 | no |

## Noise queries

How many chunks each mode returns with the threshold on, and the top chunk's similarity with it off.

| Query | Vector | Keyword | Hybrid | Top-1 vector similarity | Above threshold |
|-------|--------|---------|--------|-------------------------|-----------------|
| smartphone screen resolution | 0 | 0 | 0 | 0.774 | no |
| weather in Paris tomorrow | 0 | 0 | 0 | 0.739 | no |
| chocolate cake recipe | 0 | 0 | 0 | 0.772 | no |
| How do I renew my car insurance? | 0 | 0 | 0 | 0.794 | no |
