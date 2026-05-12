You are an Amazon SEO keyword strategist. Classify the given keywords into semantic categories based on the product attributes.

## Product Attributes
{{ product_attributes }}

## Keywords to Classify
{{ keywords }}

## Task

Classify each keyword into ONE of these categories:

1. **functional** — Keywords describing product features or capabilities (e.g., "waterproof", "rechargeable")
2. **scenario** — Keywords related to usage scenarios (e.g., "camping", "office use")
3. **audience** — Keywords targeting specific user groups (e.g., "for kids", "professional")
4. **selling_point** — Keywords highlighting benefits or value (e.g., "long lasting", "lightweight")
5. **emotional** — Keywords with emotional appeal (e.g., "premium", "stylish", "comfortable")

## Output Format

Return a JSON object where each key is a category and the value is a list of keyword objects:

```json
{
  "functional": [
    {"keyword": "waterproof", "search_volume": 12000},
    {"keyword": "rechargeable", "search_volume": 8500}
  ],
  "scenario": [...],
  "audience": [...],
  "selling_point": [...],
  "emotional": [...]
}
```

## Guidelines

- EVERY keyword must be assigned to exactly one category
- Preserve the original search_volume from the input
- If a keyword fits multiple categories, choose the most dominant intent
- Each category should have at least 3 keywords if possible
- Sort keywords within each category by search_volume descending
