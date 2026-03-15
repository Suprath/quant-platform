TOKEN=$(grep UPSTOX_ACCESS_TOKEN .env | cut -d '=' -f2 | xargs)
for unit in "day" "Day" "D" "d" "1day" "daily" "month" "week" "m" "M"; do
  echo "\nTesting unit=$unit interval=1"
  docker exec data_backfiller curl -s -X GET "https://api.upstox.com/v3/historical-candle/NSE_EQ%7CINE002A01018/$unit/1/2024-01-01/2023-12-02" -H "Accept: application/json" -H "Authorization: Bearer $TOKEN" | head -c 300
done
