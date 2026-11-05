from config import FARE_TABLE


def base_fare(class_code):
    return FARE_TABLE[class_code]


def calculate_fare(class_code, num_passengers):
    return FARE_TABLE[class_code] * num_passengers
