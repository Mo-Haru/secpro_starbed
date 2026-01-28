def fibonacci(value):
    lst = [0, 1]
    for i in range(2, value):
        lst.append(lst[i - 1] + lst[i - 2])
    return lst

print(fibonacci(20000))