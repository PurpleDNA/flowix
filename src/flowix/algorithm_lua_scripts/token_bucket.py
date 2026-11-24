token_bucket_lua = """
algorithms['token'] = function(key, capacity, refill_rate, refill_interval)
    local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
    local tokens = tonumber(bucket[1])
    local last_refill = tonumber(bucket[2])

    if tokens == nil then
        tokens = capacity
        last_refill = now
    end

    -- clock moved backwards (e.g. failover): restart the interval from now. Saved
    -- here because a blocked request returns below without writing anything
    if last_refill > now then
        last_refill = now
        redis.call('HSET', key, 'last_refill', last_refill)
    end

    local time_passed = now - last_refill
    local refills = math.floor(time_passed / refill_interval)

    if refills > 0 then
        tokens = math.min(capacity, tokens + (refills * refill_rate))
        last_refill = last_refill + (refills * refill_interval)
    end

    if tokens < 1 then
        -- seconds until the bucket holds a full token again; a refill_rate below 1
        -- can need several intervals. Rounded up: Redis truncates decimals on return
        local refills_needed = math.ceil((1 - tokens) / refill_rate)
        return nil, math.ceil(last_refill + (refills_needed * refill_interval) - now)
    end

    return function()
        redis.call('HSET', key, 'tokens', tokens - 1, 'last_refill', last_refill)
        -- tokens only arrive in whole intervals
        local ttl = math.ceil(math.ceil(capacity / refill_rate) * refill_interval) + 10
        redis.call('EXPIRE', key, ttl)
    end
end
"""
