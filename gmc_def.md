# Google Merchant Center – Product Data Specification (Reference for Coding Agent)

> Source: https://support.google.com/merchants/answer/7052112 (+ individual attribute docs, see Sources at the end)
> Last updated: August 2026 (incl. 2025/2026 spec update)
> Purpose: Complete attribute reference for implementing a Google Shopping feed exporter (XML/TXT/API).
> Requirement levels: REQUIRED | CONDITIONAL (depends on product/country) | OPTIONAL | DEPRECATED (removed/replaced)

## General Formatting Rules
- Write attribute names with underscores, e.g. `image_link` (not `image-link` or `imageLink`).
- Free-text attributes (title, description) in one consistent language per feed.
- Enum values (e.g. `condition`, `availability`) ALWAYS submitted in English, regardless of feed language; case-sensitive (`in_stock`, not `In Stock`).
- One feed row = one "item"; a product with variants (size/color) = multiple items sharing one `item_group_id`.
- Sub-attributes in text feeds: header `attribute(sub1:sub2)`, value `value1:value2`; in XML nested: `<g:attribute><g:sub1>…</g:sub1></g:attribute>`.
- Repeatable attributes: multiple columns with identical headers in text feeds, multiple elements in XML.
- Prices: dot (`.`) as decimal separator, currency as ISO 4217 code, e.g. `15.00 USD`.
- Date fields: strict ISO 8601 with timezone offset (`YYYY-MM-DDThh:mm+hhmm` or `…Z`), otherwise feed rejection.

## Field Types (Legend)
| Type | Meaning | Example |
|---|---|---|
| String | Free text (Unicode, ASCII recommended) | `A2B4` |
| Enum | Fixed value set, English, case-sensitive | `in_stock` |
| URL | http/https, encoded per RFC 2396/1738 or RFC 3986 | `https://…/p1.jpg` |
| Price | Numeric + ISO 4217 | `15.00 USD` |
| Date | ISO 8601 | `2026-09-30T14:00+0200` |
| Integer | Whole number | `6` |
| Boolean | `yes`/`no` or `true`/`false` (attribute-dependent) | `yes` |
| Object | Attribute group with sub-attributes | `installment(months:amount)` |

---

## 1. Basic Product Data

| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `id` | REQUIRED | String | Unique product ID (ideally the SKU), max. 50 chars, stable across updates, valid Unicode only, identical across countries |
| `title` | REQUIRED* | String | Product name, max. 150 chars; no promotional text, no ALL CAPS, must match landing page; include distinguishing attribute (color/size) for variants |
| `structured_title` | REQUIRED* (alternative) | Object: `digital_source_type` (`default`\|`trained_algorithmic_media`, opt) + `content` (req, max. 150) | Required variant for AI-generated titles |
| `description` | REQUIRED* | String | Product description, max. 5000 chars; no links/sales info/competitor mentions; formatting allowed |
| `structured_description` | REQUIRED* (alternative) | Object like `structured_title`, `content` max. 5000 | Required variant for AI-generated descriptions |
| `link` | REQUIRED | URL | Landing page, max. 2000 chars, verified domain, http/https |
| `canonical_link` | OPTIONAL | URL | Canonical URL of the landing page (for tracking parameters/variant URLs), max. 2000 chars |
| `image_link` | REQUIRED | URL | Main image, max. 2000 chars; formats: JPEG, WebP, PNG, GIF (non-animated), BMP, TIFF; no watermarks/promo text; **min. 500×500 px from 2027-01-31** (warnings since 2026-04-14); AI images: IPTC `DigitalSourceType` metadata must be preserved |
| `additional_image_link` | OPTIONAL | URL, repeatable (up to 10×) | Additional images (staging/graphics allowed), max. 2000 chars per URL |
| `lifestyle_image_link` | OPTIONAL | URL (ASCII only, RFC 3986), NOT repeatable | Lifestyle image (product in real-world context), 1–2000 chars; formats: GIF, JPEG, PNG, BMP, TIFF |
| `video_link` | OPTIONAL | URL | Product video (serving since 2026-06-30): 6–240 s, max. 500 MB, ≥720p, aspect ratio 9:16/16:9/1:1; formats: MPG, MP4, WMV, AVI, MOV, FLV, MPEG-1, MPEGPS; direct file link (no player), publicly crawlable |
| `virtual_model_link` | OPTIONAL (US only) | URL to .gltf/.glb | 3D model, max. 15 MB, textures max. 2K |
| `mobile_link` | OPTIONAL | URL | Mobile landing page variant, max. 2000 chars; same requirements as `link` |

\* Exactly one of each pair (`title`/`structured_title`, `description`/`structured_description`) is required.

---

## 2. Price and Availability

| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `availability` | REQUIRED | Enum: `in_stock`, `out_of_stock`, `preorder`, `backorder` | Must match landing page/checkout/Schema.org markup |
| `availability_date` | CONDITIONAL | Date, max. 25 chars | Required for `preorder` (recommended for `backorder`); max. 1 year in the future; must be visible on landing page |
| `price` | REQUIRED | Price | US/CA: excl. taxes; all other countries: incl. VAT/GST; must match checkout; not 0 (exceptions: mobile device with contract, physical subscription goods); **since 2025-04-08 no longer used for installment downpayments** (use `installment(downpayment)`) |
| `sale_price` | OPTIONAL | Price | In addition to `price` (regular price stays in `price`); do not use for loyalty/member prices |
| `sale_price_effective_date` | OPTIONAL | Date interval `start/end`, max. 51 chars | Without it, `sale_price` applies permanently; start before end |
| `cost_of_goods_sold` | OPTIONAL | Price | Cost of goods for margin reporting in Merchant Center |
| `expiration_date` | OPTIONAL | Date, max. 25 chars | Stop showing the item; < 30 days in the future |
| `unit_pricing_measure` | CONDITIONAL | Number + unit, e.g. `1.5kg` | Required where legally mandated (unit pricing); units: oz, lb, mg, g, kg, floz, pt, qt, gal, ml, cl, l, cbm, in, ft, yd, cm, m, sqft, sqm, ct |
| `unit_pricing_base_measure` | CONDITIONAL | Integer + unit, e.g. `100g` | Only together with `unit_pricing_measure`; integers: 1, 10, 100, 2, 4, 8; additional allowed combos: `75cl`, `750ml`, `50kg`, `1000kg` |
| `installment` | OPTIONAL | Object: `months` (Integer, req), `amount` (Price, req), `downpayment` (Price, opt), `credit_type` (`finance`\|`lease`, opt) | Installment payment; `price` must hold the full upfront price; observe country/category restrictions |
| `subscription_cost` | OPTIONAL | Object: `period` (`week`\|`month`\|`year`), `period_length` (Integer > 0), `amount` (Price) | Only for eligible `google_product_category` IDs (wireless: 201, 267, 4745, 6030, 6544; physical subscriptions incl. 166, 491, 536, 1253, 2915, 5814, 1868, 2, 499676, 518); for physical subscriptions `price` = 0 |
| `loyalty_program` | OPTIONAL | Object with 7 sub-attributes: `program_label`, `tier_label`, `price`, `cashback_for_future_use`, `loyalty_points` (Integer), `member_price_effective_date` (Date interval), `shipping_label` | Member prices ONLY via this attribute (not via `price`/`sale_price`); must match the loyalty program settings in Merchant Center; available incl. US, UK, DE, FR, IT, ES, NL, JP (points) |
| `auto_pricing_min_price` | OPTIONAL | Price | Floor price for automated discounts/dynamic offers (MAP compliance) |
| `maximum_retail_price` | OPTIONAL (India only) | Price (INR) | Manufacturer-declared maximum retail price (MRP) for free listings in India; must match landing page/checkout |

---

## 3. Product Category

| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `google_product_category` | OPTIONAL | Integer (ID) OR String (full path) – not both | One single, most specific category from the Google Product Taxonomy; ID preferred; special rules for mobile devices (267), smartwatches (201), tablets (4745), gift cards (53), alcohol, subscription goods |
| `product_type` | OPTIONAL | String, path with `>`, repeatable (up to 5×) | Max. 750 chars; your own store categorization; only the first value is used for bidding/reporting in Ads |

---

## 4. Product Identifiers

| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `brand` | REQUIRED* | String | Max. 70 chars; exceptions: movies, books, music; do not use "N/A"/"Generic"; leave empty if truly unbranded |
| `gtin` | CONDITIONAL (strongly recommended) | String (numeric), repeatable | Max. 14 digits per value: UPC (12), EAN (13), JAN (8/13), ISBN (13), ITF-14 (14); GS1 checksum must be valid; submit only if certain it is correct |
| `mpn` | CONDITIONAL | String (alphanumeric) | Max. 70 chars; required if no GTIN; only manufacturer-assigned values |
| `identifier_exists` | OPTIONAL | Enum: `yes`/`no` | Default `yes`; set `no` when brand/GTIN/MPN do not exist (e.g. handmade goods) |

---

## 5. Detailed Product Description (Variants & Attributes)

| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `condition` | REQUIRED | Enum: `new`, `refurbished`, `used` | Product condition |
| `color` | CONDITIONAL | String, max. 40 chars | Required for apparel with color variants; up to 3 colors separated by `/` |
| `size` | CONDITIONAL | String, max. 100 chars | Required for size variants (apparel/shoes) |
| `size_type` | OPTIONAL | Enum: `regular`, `petite`, `plus`, `big and tall`, `maternity` | Cut type |
| `size_system` | OPTIONAL | Enum: `US`, `UK`, `EU`, `DE`, `FR`, `JP`, `CN`, `IT`, `BR`, `MEX`, `AU` | Default: `US` |
| `gender` | CONDITIONAL | Enum: `male`, `female`, `unisex` | Required for apparel |
| `age_group` | CONDITIONAL | Enum: `newborn`, `infant`, `toddler`, `kids`, `adult` | Required for apparel |
| `item_group_id` | CONDITIONAL | String, max. 50 chars | Groups all variants of the same base product; consistent across all variants |
| `material` | OPTIONAL | String, max. 200 chars | Material information |
| `pattern` | OPTIONAL | String, max. 100 chars | Pattern/design |
| `multipack` | CONDITIONAL | Integer (≥ 2) | Number of identical single products in a multipack |
| `is_bundle` | CONDITIONAL | Enum: `yes`/`no` | Marks a bundle of different products |
| `adult` | CONDITIONAL | Enum: `yes`/`no` | Required for adult content |
| `product_length` / `product_width` / `product_height` | OPTIONAL | Number + unit (`in`, `ft`, `yd`, `cm`, `m`) | Product dimensions (without packaging) |
| `product_weight` | OPTIONAL | Number + unit (`oz`, `lb`, `mg`, `g`, `kg`) | Product weight |
| `product_highlight` | OPTIONAL | String, repeatable | Bullet highlights: 1–150 chars each; if used, min. 2, max. 100 (recommended 4–6) |
| `product_detail` | OPTIONAL | Object: `section_name`, `attribute_name`, `attribute_value`; repeatable | Structured technical details (e.g. battery, connectivity) |
| `certification` | CONDITIONAL | Object: `certification_authority` (req, e.g. `EC`/`European_Commission`), `certification_name` (req, e.g. `EPREL`), `certification_code` (cond., e.g. EPREL code), `certification_value` (cond.); repeatable | Required for EPREL-mandated products in EU/EFTA/UK; replaces the energy efficiency attributes in the EU since 2025-04 |
| `energy_efficiency_class` | DEPRECATED (EU) | Enum: `A+++` … `G` | Replaced by `certification` in the EU; use only for CH/NO/UK |
| `min_energy_efficiency_class` / `max_energy_efficiency_class` | DEPRECATED (EU) | Enum: `A+++` … `G` | Like `energy_efficiency_class`; scale range, CH/NO/UK only |
| `consumer_notice` | OPTIONAL | Object: `notice_type` (req: `legal_disclaimer`\|`safety_warning`\|`prop_65`), `notice_message` (req, String max. 1000 chars, allowed HTML tags: `<b>`, `<br>`, `<i>`, `<a href>`); repeatable | Legally required consumer notices/safety warnings (e.g. EU GPSR, California Prop 65); format: `notice_type:notice_message` |

---

## 6. Shopping Campaigns & Destinations

| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `custom_label_0` … `custom_label_4` | OPTIONAL | String | Free labels for campaign segmentation; max. 100 chars, up to 1000 unique values per label |
| `promotion_id` | OPTIONAL | String, repeatable | Links the product to Merchant Center promotion(s) |
| `ads_redirect` | OPTIONAL | URL, max. 2000 chars | Alternative click URL for tracking (ads only, not free listings) |
| `included_destination` | OPTIONAL | Enum, repeatable: `Shopping_ads`, `Display_ads`, `Local_inventory_ads`, `Free_listings`, `Free_local_listings`, `YouTube_Shopping` (partly also `Cloud_retail`, `Local_cloud_retail`, `youtube_affiliate`, `youtube_merchandise`) | Additional serving destinations per product |
| `excluded_destination` | OPTIONAL | Enum like `included_destination`, repeatable | Exclude product from destinations; **takes precedence over `included_destination`** |
| `shopping_ads_excluded_country` | OPTIONAL | ISO 3166-1 country code, repeatable | Country exclusion specifically for Shopping ads |
| `pause` | OPTIONAL | Enum: `ads` | Pauses the product in Shopping ads without deleting it |

---

## 7. Marketplaces

| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `external_seller_id` | CONDITIONAL (required for multi-seller accounts) | String, 1–50 chars | Unique seller ID of a marketplace seller; case-sensitive; allowed: ASCII alphanumeric + `_`, `-`, `.`, `~`; must not equal the internal `seller_id` |

---

## 8. Shipping, Pickup & Returns

| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `shipping` | CONDITIONAL | Object, repeatable (up to 100×): `country`, `region`, `postal_code`, `location_id`, `location_group_name`, `service`, `price` (Price), `min_handling_time`, `max_handling_time`, `min_transit_time`, `max_transit_time` | Item-level shipping costs/times; required if not covered at account level or if deviating |
| `shipping_label` | OPTIONAL | String | Custom grouping for shipping rules (e.g. "bulky") |
| `shipping_weight` | CONDITIONAL | Number + unit (`lb`, `oz`, `g`, `kg`) | Required for weight-based/carrier-calculated shipping |
| `shipping_length` / `shipping_width` / `shipping_height` | OPTIONAL | Number + unit (`in`, `ft`, `yd`, `cm`, `m`) | Package dimensions |
| `min_handling_time` / `max_handling_time` | OPTIONAL | Integer (business days) | Processing time from order to carrier handover |
| `handling_cutoff_time` | OPTIONAL (NEW 2025/26) | Object: `cutoff_time` (req, 4-digit `HHMM`, 24h; `2359` = no cutoff), `country` (opt, ISO 3166-1), `cutoff_timezone` (opt, IANA, e.g. `Europe/Berlin`; default = destination country timezone), `disable_delivery_after_cutoff` (opt, Boolean, default `false`) | Daily order cutoff for same-day processing; at offer, country, or shipping-override level |
| `transit_time_label` | OPTIONAL | String | Label for transit time tables in Merchant Center |
| `ships_from_country` | OPTIONAL | ISO 3166-1 country code | Shipping origin country (if different from target country) |
| `free_shipping_threshold` | OPTIONAL | Price | Minimum order value for free shipping |
| `minimum_order_value` | OPTIONAL (NEW; **required from 2026-09-30** for in-store products in UK/CH/EEA) | Object, up to 100 values: `country` (req, ISO 3166-1), `service` (opt), `surface` (opt: `online`\|`local`\|`online_local`, default `online_local`), `price` (req, Price; currency = offer currency) | Minimum order value at product level |
| `pickup_cost` | OPTIONAL (NEW; **required from 2026-09-30** for in-store products in UK/CH/EEA) | Object: `pickup_cost_flat_rate` (req, Price), `pickup_cost_free_threshold` (opt, Price) | Fee for online purchase/reservation with in-store pickup; without threshold the flat rate always applies |
| `tax` | CONDITIONAL (US only) | Object: `country`, `region`, `postal_code`, `location_id`, `rate` (percent, req), `tax_ship` (Boolean) | US taxes at item level |
| `tax_category` | OPTIONAL (US) | String | Tax category mapping |
| `returns` | OPTIONAL (NEW, recommended) | Object, up to 100 overrides/offer: `country` (req), `item_condition` (req: `NEW`\|`LIKE_NEW`\|`USED`\|`DEFECTIVE_ONLY`), `window_type` (opt: `FINITE_RETURN_WINDOW`\|`NO_RETURNS`\|`LIFETIME`, default `FINITE_RETURN_WINDOW`), `window_days` (cond. Integer – required for `FINITE_RETURN_WINDOW`), `method` (req: `BY_MAIL`\|`IN_STORE`\|`AT_A_KIOSK`\|`DROP_OFF_LOCATION`), `outcome` (opt: `REFUND`\|`EXCHANGE`\|`STORE_CREDIT`), `shipping_fee` (Price, default 0), `shipping_fee_type` (cond.: `DEDUCTED_FROM_REFUND`\|`CUSTOMER_RESPONSIBILITY`), `restocking_fee` (opt, Price) OR `restocking_percentage_fee` (opt, percent) – only one of the two, `policy_url` (opt, URL) | Return policy at product level; overrides account-level policy; text feed example: header `returns(country:window_days:item_condition:method:shipping_fee)`, value `US:30:NEW:BY_MAIL:8.00 USD` |

---

## 9. Local Inventory Ads (Separate Local Inventory Feed)

These attributes belong in a separate local inventory feed (not the primary feed); `id` must match the primary feed.

| Field | Required | Type/Syntax | Description & Limits |
|---|---|---|---|
| `store_code` | REQUIRED (LIA) | String | Store code, must match the linked Business Profile |
| `quantity` | REQUIRED (LIA) | Integer | Available units in the store |
| `pickup_method` | OPTIONAL (since 2026) | Enum: `buy`, `reserve`, `ship_to_store`, `not_supported` | Pickup option (buy/reserve/ship to store) |
| `pickup_sla` | CONDITIONAL | Enum: `same day`, `next day`, `2-day`, `3-day`, `4-day`, `5-day`, `6-day`, `7-day`, `multi-week` | Pickup readiness time; required when `pickup_method` is set |
| `price` / `sale_price` / `availability` / `availability_date` | OPTIONAL (LIA) | as in primary feed | Store-specific overrides |
| `region_id` | REQUIRED (regional inventory feed only) | String | Regional price/availability overrides (RAAP; generally available since 2025-09, postal-code level in 22 countries) |

---

## 10. Vehicle Listings (Separate Feed Specification)

Source: https://developers.google.com/vehicle-listings/reference/feed-specification – vehicle feeds do NOT use the standard Shopping specification.

| Field | Required | Type/Syntax | Description |
|---|---|---|---|
| `vin` | REQUIRED | String (17 chars, NHTSA-compliant) | Vehicle identification number |
| `id` | OPTIONAL | String | Internal stock number, unique per vehicle |
| `store_code` | REQUIRED | String | Dealership/location ID |
| `dealership_name` / `dealership_address` | REQUIRED | String | Dealership name / full address |
| `place_id` / `maps_url` / `tracking_phone_number` | OPTIONAL | String / URL / phone no. | Business Profile matching; tracking number |
| `link` | RECOMMENDED | URL (UTM allowed) | Vehicle details page (VDP) |
| `image_link` / `additional_image_link` | RECOMMENDED | URL / URL, repeatable | Vehicle images |
| `price` | REQUIRED | Price (ISO 4217) | Final sales price |
| `vehicle_msrp` | RECOMMENDED (for `new`) | Price | MSRP in current configuration |
| `condition` | REQUIRED | Enum: `new`/`used` (also `n`/`u`) | Vehicle condition |
| `certified_pre_owned` | OPTIONAL | Boolean (`1`/`y`/`yes`, `0`/`n`/`no`) | OEM-certified pre-owned |
| `make` / `model` | REQUIRED | String | Make / model (without trim details) |
| `trim` | REQUIRED (where available) | String | Trim level |
| `year` | REQUIRED | Integer `YYYY` | Model year |
| `mileage` | REQUIRED (for `used`) | Integer + unit | Odometer reading (km/miles) |
| `exterior_color` / `exterior_color_generic` / `interior_color` / `interior_color_generic` | RECOMMENDED/OPTIONAL | String | Colors (OEM designation / generic) |
| `body_style` | OPTIONAL | Enum-like: `sedan`, `suv`, `coupe`, `convertible`, `crossover`, `hatchback`, `minivan`, `truck`, `station wagon`, `full size van` … | Body style |
| `vehicle_option` | RECOMMENDED | String, repeatable | Standard/optional equipment (comma-separated) |
| `drive_train` | OPTIONAL | Enum: `FWD`, `RWD`, `AWD`, `4WD` | Drivetrain |
| `engine` / `transmission` / `fuel` / `fuel_efficiency` | OPTIONAL | String | Engine / transmission / fuel type / efficiency (MPG) |
| `ev_battery` / `ev_range` | OPTIONAL | String | EV: battery / range |
| `num_doors` / `seating_capacity` / `seating_rows` | OPTIONAL | Integer | Doors / seats / seating rows |
| `co2_emission` | OPTIONAL | String | CO₂ emissions |
| `legal_disclaimer` | OPTIONAL | String, max. 3000 chars | Legal notices (taxes, fees) |
| `description` | OPTIONAL | String | Free text (e.g. accident-free) |
| `vehicle_fulfillment` | OPTIONAL | Enum: `IN_STORE`, `SHIP_TO_STORE`, `ONLINE` | Availability/fulfillment status |
| `vehicle_location` | OPTIONAL | String | Deviating vehicle location |
| `vehicle_history_report_link` / `monroney_sticker` | OPTIONAL | URL | History report / Monroney sticker |
| `date_in_stock` | OPTIONAL | Date (ISO 8601) | In stock since |

---

## 11. Deprecated / Removed Attributes (do not submit)

| Field | Status | Note |
|---|---|---|
| `energy_efficiency_class`, `min_energy_efficiency_class`, `max_energy_efficiency_class` | DEPRECATED (EU, since 2025-04-08) | Replaced by `certification` in the EU; still valid for CH/NO/UK only |
| `display_ads_id`, `display_ads_similar_ids`, `display_ads_title`, `display_ads_link`, `display_ads_value` | REMOVED | Legacy dynamic remarketing attributes; no longer part of the specification |
| `link_template`, `mobile_link_template` | REMOVED (Shopping) | No longer part of the Shopping specification; still used in vehicle feeds |
| `sell_on_google_quantity` | REMOVED | Discontinued with "Buy on Google" |
| `Buy_on_Google_listings` (destination value) | REMOVED | Discontinued destination |
| `expected_lifetime` | NOT A GMC ATTRIBUTE | Does not exist in the official specification – was incorrectly listed in the template, removed here |

---

## Implementation Notes for the Coding Agent

- Baseline required fields for EVERY product: `id`, `title`/`structured_title`, `description`/`structured_description`, `link`, `image_link`, `availability`, `price`, `condition`; `brand` in practice almost always (except movies/books/music).
- GTIN vs. MPN: if `gtin` is set, `mpn` is optional; without `gtin`, `mpn` + `brand` become required; with no identifiers at all set `identifier_exists = no`.
- Variants: `item_group_id` consistent across all variants; `color`/`size`/`gender`/`age_group` differ per variant.
- Submit enum values exactly and in English (case-sensitive).
- Validate date fields strictly as ISO 8601 with timezone offset.
- AI labeling: AI-generated titles/descriptions via `structured_title`/`structured_description` with `digital_source_type = trained_algorithmic_media`; AI images with IPTC `DigitalSourceType` metadata (do not strip) – otherwise policy violation.
- Price/installments: since 2025-04-08 downpayments only via `installment(downpayment)`; `price` = full upfront price.
- EU energy label: use `certification` with `certification_authority = EC`/`European_Commission` + `certification_name = EPREL` (+ EPREL code); legacy classes only for CH/NO/UK.
- Key deadlines: **2026-09-30** – `pickup_cost` + `minimum_order_value` required for in-store products (UK/CH/EEA); **2027-01-31** – 500×500 px minimum image size for all categories.
- Sub-attribute order in text feeds: if the header contains only the attribute name, the documented default sub-attribute order applies; send empty optional sub-attributes as empty colon positions.

## Sources
- Product data specification: https://support.google.com/merchants/answer/7052112
- Announcements change log: https://support.google.com/merchants/announcements/6192467
- consumer_notice: https://support.google.com/merchants/answer/17224374
- handling_cutoff_time: https://support.google.com/merchants/answer/16543665
- minimum_order_value: https://support.google.com/merchants/answer/16989009
- pickup_cost: https://support.google.com/merchants/answer/16988704
- returns: https://support.google.com/merchants/answer/17081382
- external_seller_id: https://support.google.com/merchants/answer/11537846
- lifestyle_image_link: https://support.google.com/merchants/answer/9103186
- certification: https://support.google.com/merchants/answer/13528839
- maximum_retail_price: https://support.google.com/merchants/answer/15972291
- Vehicle feed specification: https://developers.google.com/vehicle-listings/reference/feed-specification
