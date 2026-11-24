class FlowixError(Exception):
    """Base class for every flowix exception"""
    pass

class InvalidParameterType(FlowixError, TypeError):
    """A parameter has the wrong type"""
    pass

class InvalidParameterValue(FlowixError, ValueError):
    """A parameter has the right type but a value that is not allowed"""
    pass

class IncorrectParameters(FlowixError, ValueError):
    """Parameters are missing, or not accepted by the chosen algorithm"""
    pass

class UnsupportedAlgorithm(FlowixError, ValueError):
    """The algorithm does not exist"""
    pass
