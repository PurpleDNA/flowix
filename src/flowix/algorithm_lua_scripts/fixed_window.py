fixed_window_lua = """
algorithms['fixed_window'] = function(key, limit, window)
    local data  = redis.call('HMGET', key, 'count', 'start')
    local count = tonumber(data[1])
    local start = tonumber(data[2])

    -- a window opens on the first allowed request, or the first after the last one ended
    if count == nil or now - start >= window then
        count = 0
        start = now
    end

    -- clock moved backwards (e.g. failover): restart the window from now. Saved
    -- here because a blocked request returns below without writing anything
    if start > now then
        start = now
        redis.call('HSET', key, 'start', start)
    end

    if count >= limit then
        -- seconds; rounded up so clients never retry too early
        return nil, math.ceil(window - (now - start))
    end

    return function()
        redis.call('HSET', key, 'count', count + 1, 'start', start)
        redis.call('EXPIRE', key, math.ceil(window) + 1)
    end
end
"""
