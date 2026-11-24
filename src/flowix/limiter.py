from .exceptions import InvalidParameterType, InvalidParameterValue


class LeakyBucketLimiter:
    def __init__(self, capacity: int, leak_rate: float) -> None:
        if not isinstance(capacity,int) or isinstance(capacity,bool):
            raise InvalidParameterType("capacity must be an integer")
        if not isinstance(leak_rate,(int,float)):
            raise InvalidParameterType("leak_rate must be a number")
        if capacity <= 0:
            raise InvalidParameterValue('capacity must be positive')
        if leak_rate <= 0:
            raise InvalidParameterValue("leak_rate must be positive")
        self.capacity = capacity
        self.leak_rate = leak_rate
