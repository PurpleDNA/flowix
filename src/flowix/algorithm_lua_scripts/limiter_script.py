from .fixed_window import fixed_window_lua
from .leaky_bucket import leaky_bucket_lua
from .sliding_counter import sliding_counter_lua
from .sliding_log import sliding_log_lua
from .token_bucket import token_bucket_lua

# Runs any number of limiters, and charges either all of them or none.
#
# Each algorithm adds a function to `algorithms`. Given a key and its parameters, it
# returns a function that charges the request or, when there is no room for it,
# nil and the seconds to wait. It must not charge anything itself.
limiter_script = (
    """
local t   = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1e6

local algorithms = {}
"""
    + token_bucket_lua
    + leaky_bucket_lua
    + fixed_window_lua
    + sliding_log_lua
    + sliding_counter_lua
    + """
local charges = {}
local results = {}
local all_allowed = true

-- ARGV holds four values per key: the algorithm, then its parameters
for i, key in ipairs(KEYS) do
    local at = (i - 1) * 4
    local check = algorithms[ARGV[at + 1]]
    local charge, retry_after = check(
        key, tonumber(ARGV[at + 2]), tonumber(ARGV[at + 3]), tonumber(ARGV[at + 4])
    )
    if charge then
        charges[i] = charge
        results[i] = {1, 0}
    else
        all_allowed = false
        results[i] = {0, math.max(1, retry_after)}
    end
end

if all_allowed then
    for i = 1, #KEYS do
        charges[i]()
    end
end

return results
"""
)
