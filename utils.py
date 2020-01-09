import math
from datetime import datetime

def get_datetime_string():
    date_and_time = datetime.now()
    return date_and_time.strftime('%Y-%m-%d %H:%M:%S')

def flatten_dict(dictionary, exclude = [], delimiter ='_'):
    flat_dict = dict()
    for key, value in dictionary.items():
        if isinstance(value, dict) and key not in exclude:
            flatten_value_dict = flatten_dict(value, exclude, delimiter)
            for k, v in flatten_value_dict.items():
                flat_dict[f"{key}{delimiter}{k}"] = v
        else:
            flat_dict[key] = value
    return flat_dict

def unwrap_iterable(iterable):
    elements = list()
    unwrapped_list = iterable.values() if isinstance(iterable, dict) else iterable
    for value in unwrapped_list:
        if isinstance(value, (dict, list, tuple)):
            elements = elements + unwrap_iterable(value)
        else:
            elements.append(value)
    return elements

def translate(value, left_min, left_max, right_min, right_max):
    # Calculate the span of each range
    left_span = left_max - left_min
    right_span = right_max - right_min
    # normalize the value from the left range into a float between 0 and 1
    value_normalized = float(value - left_min) / float(left_span)
    # Convert the normalize value range into a value in the right range.
    return right_min + (value_normalized * right_span)

def clip(value, min_value, max_value):
    if value <= min_value:
        return min_value
    elif value >= max_value:
        return max_value
    else:
        return value

def translate_and_clip(value, left_min, left_max, right_min, right_max):
    translated_value = translate(value, left_min, left_max, right_min, right_max)
    clipped_value = clip(translated_value, right_min, right_max)
    return clipped_value

def merge_dict(dict1, dict2):
   ''' Merge dictionaries and keep values of common keys in list'''
   dict3 = {**dict1, **dict2}
   for key, value in dict3.items():
       if key in dict1 and key in dict2:
               dict3[key] = [value , dict1[key]]
   return dict3