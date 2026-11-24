leaky_bucket_lua = """
algorithms['leaky'] = function(key, capacity, leak_rate)
    local data      = redis.call('HMGET', key, 'level', 'last_leak')
    local level     = tonumber(data[1]) or 0
    local last_leak = tonumber(data[2]) or now

    -- clock moved backwards (e.g. failover): restart from now. Saved here
    -- because a blocked request returns below without writing anything
    if last_leak > now then
        last_leak = now
        redis.call('HSET', key, 'last_leak', last_leak)
    end

    local elapsed = now - last_leak
    level = math.max(0, level - elapsed * leak_rate)

    if level + 1 > capacity then
        -- seconds; rounded up so clients never retry too early
        return nil, math.ceil((level + 1 - capacity) / leak_rate)
    end

    return function()
        redis.call('HSET', key, 'level', level + 1, 'last_leak', now)
        redis.call('EXPIRE', key, math.ceil(capacity / leak_rate) + 1)
    end
end
"""
