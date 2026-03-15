TOKEN="eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI1MkNOVlQiLCJqdGkiOiI2OTlmNDNmOTVjNTdjODY5OTEwOTM5MTgiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc3MjA0NTMwNSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzcyMDU2ODAwfQ.X_0K9qWkEotAWVb0n_Kei4b2O2x-Wzkq-lMap2M-cvI"
curl -v -H "Accept: application/json" -H "Authorization: Bearer $TOKEN" "https://api.upstox.com/v2/historical-candle/NSE_EQ|INE002A01018/1day/2024-01-01/2023-12-02"
echo "\n"
curl -v -H "Accept: application/json" -H "Authorization: Bearer $TOKEN" "https://api.upstox.com/v2/historical-candle/NSE_EQ|INE002A01018/day/1/2024-01-01/2023-12-02"
