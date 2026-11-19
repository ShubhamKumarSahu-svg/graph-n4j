from rates import discount


def quote(total):
    return discount(total)


if __name__ == "__main__":
    print(quote(100))
