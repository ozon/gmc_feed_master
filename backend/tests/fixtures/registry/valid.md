# Fixture

## 1. Basic Product Data

| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `title` | REQUIRED* | String | max. 150 chars |
| `additional_image_link` | OPTIONAL | URL, repeatable (up to 10×) | max. 2000 chars |
| `installment` | OPTIONAL | Object: `months` (Integer, req), `amount` (Price, req) | payment |
| `availability` | REQUIRED | Enum: `in_stock`, `out_of_stock` | exact values |
