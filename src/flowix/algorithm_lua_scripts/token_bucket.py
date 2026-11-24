token_bucket_script = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local refill_interval = tonumber(ARGV[3])

local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1e6

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

-- clock moved backwards (e.g. failover): restart the interval from now
if last_refill > now then
    last_refill = now
end

local time_passed = now - last_refill
local refills = math.floor(time_passed / refill_interval)

if refills > 0 then
    tokens = math.min(capacity, tokens + (refills * refill_rate))
    last_refill = last_refill + (refills * refill_interval)
end

local allowed = 0
local retry_after = 0

if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    -- seconds until the bucket holds a full token again; a refill_rate below 1
    -- can need several intervals. Rounded up: Redis truncates decimals on return
    local refills_needed = math.ceil((1 - tokens) / refill_rate)
    retry_after = math.ceil(last_refill + (refills_needed * refill_interval) - now)
end

redis.call('HSET', key, 'tokens', tokens, 'last_refill', last_refill)

local ttl = math.ceil(capacity / refill_rate * refill_interval) + 10
redis.call('EXPIRE',key,ttl)

return {allowed, retry_after}
"""
