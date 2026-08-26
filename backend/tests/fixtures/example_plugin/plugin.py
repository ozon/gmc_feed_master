class UpperPlugin:
    def validate_config(self, config):
        if not isinstance(config, dict) or "suffix" not in config:
            raise ValueError("suffix is required")

    def process(self, product, config, data, ctx):
        title = product.get("title")
        if product.get("id") == "drop-me":
            return None
        if isinstance(title, str):
            product["title"] = title.upper()
        product["title_suffix"] = config["suffix"]
        return product
