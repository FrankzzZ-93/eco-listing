You are a quality reviewer for product attribute tables. Evaluate the following draft and provide a confidence score.

## Draft to Evaluate
{{ draft }}

## Evaluation Criteria

1. **Specificity** — Are target_users, use_cases specific enough? (Not generic like "everyone", "daily use")
2. **Completeness** — Does each field have at least 3 meaningful entries?
3. **Consistency** — Do selling_points address the identified pain_points?
4. **Language Quality** — Are language_patterns drawn from actual buyer language (not marketing speak)?
5. **Actionability** — Can a copywriter directly use this to write a compelling listing?

## Output Format

Return a JSON object:

```json
{
  "confidence": 0.85,
  "notes": "Brief explanation of strengths and weaknesses. Suggest specific improvements if confidence < 0.8."
}
```

- confidence: float between 0.0 and 1.0
- notes: 1-3 sentences explaining the score
