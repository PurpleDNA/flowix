sliding_log_lua = """
algorithms['sliding_log'] = function(key, limit, window)
    local ttl = math.ceil(window) + 1

    -- a list holding the time of every allowed request, oldest first

    -- clock moved backwards (e.g. failover): no request can be later than now
    local newest = tonumber(redis.call('LINDEX', key, -1))
    if newest and newest > now then
        local log = redis.call('LRANGE', key, 0, -1)
        redis.call('DEL', key)
        for i = 1, #log do
            redis.call('RPUSH', key, math.min(tonumber(log[i]), now))
        end
        redis.call('EXPIRE', key, ttl)
    end

    local oldest = tonumber(redis.call('LINDEX', key, 0))
    while oldest and now - oldest >= window do
        redis.call('LPOP', key)
        oldest = tonumber(redis.call('LINDEX', key, 0))
    end

    local count = redis.call('LLEN', key)

    if count >= limit then
        -- the request that must leave the window to make room: the oldest, unless
        -- the limit was lowered. Rounded up so clients never retry too early
        local blocking = tonumber(redis.call('LINDEX', key, count - limit))
        return nil, math.ceil(window - (now - blocking))
    end

    return function()
        redis.call('RPUSH', key, now)
        redis.call('EXPIRE', key, ttl)
    end
end
"""
