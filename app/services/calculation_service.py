def calculate_quantity(item: dict):

    measurement_type = item.get(
        "measurement_type"
    )

    # Dimensions describe one occurrence; count says how many there are.
    count = item.get("count")
    occurrences = count if count is not None else 1

    if measurement_type == "area":
        length = item.get("length")
        width = item.get("width")
        height = item.get("height")

        if length is not None and width is not None:
            return length * width * occurrences

        if length is not None and height is not None:
            return length * height * occurrences


    if measurement_type == "linear":
        length = item.get("length")

        if length is not None:
            return length * occurrences


    if measurement_type == "count":
        return item.get("count")

    if measurement_type in [
        "window",
        "door"
    ]:
        return item.get("quantity")


    return None
