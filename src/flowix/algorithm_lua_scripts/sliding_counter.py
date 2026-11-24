sliding_counter_lua = """
algorithms['sliding_counter'] = function(key, limit, window)
    local current = math.floor(now / window)
    local elapsed = now / window - current

    local data  = redis.call('HMGET', key, 'window', 'curr', 'prev')
    local saved = tonumber(data[1])
    local curr  = tonumber(data[2]) or 0
    local prev  = tonumber(data[3]) or 0

    if saved == nil or saved < current - 1 then
        curr = 0
        prev = 0
    elseif saved == current - 1 then
        prev = curr
        curr = 0
    elseif saved > current then
        -- clock moved backwards (e.g. failover): the counts carry over, so moving
        -- the clock never resets a limit. Saved here because a blocked request
        -- returns below without writing anything
        redis.call('HSET', key, 'window', current)
    end

    if prev * (1 - elapsed) + curr >= limit then
        -- how many windows until the estimate drops to the limit
        local wait
        if curr < limit then
            wait = 1 - (limit - curr) / prev - elapsed
        else
            -- not in this window: in the next one, curr becomes the fading prev
            wait = 1 - elapsed + 1 - limit / curr
        end
        -- seconds; the next whole one, as the estimate must be below the limit. The
        -- extra millisecond covers float error in a wait just under a whole second
        return nil, math.floor(wait * window + 0.001) + 1
    end

    return function()
        redis.call('HSET', key, 'window', current, 'curr', curr + 1, 'prev', prev)
        redis.call('EXPIRE', key, math.ceil(window * 2) + 1)
    end
end
"""
