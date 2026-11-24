leaky_bucket_script= """
local key       = KEYS[1]
local capacity  = tonumber(ARGV[1])
local leak_rate = tonumber(ARGV[2])

local t   = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1e6

local data      = redis.call('HGETALL', key)
local level     = 0
local last_leak = now

if #data > 0 then
    for i = 1, #data, 2 do
        if data[i] == 'level' then
            level = tonumber(data[i+1])
        elseif data[i] == 'last_leak' then
            last_leak = tonumber(data[i+1])
        end
    end
end

if now < last_leak then
    -- clock moved backwards (e.g. failover): restart from now. Saved here
    -- because a blocked request returns below without writing anything
    last_leak = now
    redis.call('HSET', key, 'last_leak', last_leak)
end

local elapsed = now - last_leak
level = math.max(0, level - elapsed * leak_rate)

if level + 1 > capacity then
    -- seconds; rounded up so clients never retry too early
    return {0, math.ceil((level + 1 - capacity) / leak_rate)}
end

level = level + 1
local ttl = math.ceil(capacity / leak_rate) + 1

redis.call('HSET', key, 'level', level, 'last_leak', now)
redis.call('EXPIRE', key, ttl)

return {1, 0}
"""
