"""Truthful local history-index counts, separate from sync/time percentages."""


def progress_text(value, language="en"):
    through, target, restored = (value[k] for k in ("through", "target", "restored"))
    if any(type(v) is not int or v < 0 for v in (through, target, restored)) or through > target:
        raise ValueError("Invalid local history progress counts")
    if language.startswith("zh"):
        return (
            "\u7248\u672c\u7d22\u5f15\uff1a\u5df2\u6383\u63cf "
            f"{through}/{target} \u7b46\u5132\u5b58\u8a18\u9304\uff0c"
            f"\u88dc\u56de {restored} \u500b\u7248\u672c"
        )
    return f"Version index: {through}/{target} saved events; restored {restored} versions"
