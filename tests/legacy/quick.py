import requests
resp = requests.get('http://api_gateway:8080/api/v1/backtest/stats/7cf8965f-dbc3-473d-8ce1-897338ceb706')
print(resp.status_code, resp.json())
