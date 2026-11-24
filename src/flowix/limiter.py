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


class TokenBucketLimiter:
    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        refill_interval: float
    ) -> None:
        if not isinstance(refill_rate,(int,float)):
            raise InvalidParameterType("refill_rate must be a number")
        if not isinstance(refill_interval,(int,float)):
            raise InvalidParameterType("refill_interval must be a number")
        if not isinstance(capacity,int) or isinstance(capacity,bool):
            raise InvalidParameterType("capacity must be an integer")
        if capacity <= 0:
            raise InvalidParameterValue("capacity must be positive")
        if refill_rate <= 0:
            raise InvalidParameterValue("refill_rate must be positive")
        if refill_interval <= 0:
            raise InvalidParameterValue("refill_interval must be positive")

        self.capacity = capacity
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval