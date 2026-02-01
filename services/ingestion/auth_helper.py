import os
import upstox_client
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

def get_login_url():
    api_key = os.getenv('UPSTOX_API_KEY')
    redirect_uri = os.getenv('UPSTOX_REDIRECT_URI')
    
    # Properly encode the redirect_uri for the URL
    encoded_uri = urllib.parse.quote(redirect_uri, safe='')
    
    url = (
        f"https://api.upstox.com/v2/login/authorization/dialog?"
        f"response_type=code&client_id={api_key}&redirect_uri={encoded_uri}"
    )
    return url

def exchange_code(auth_code):
    api_instance = upstox_client.AuthenticationApi()
    try:
        api_response = api_instance.token(
            code=auth_code,
            client_id=os.getenv('UPSTOX_API_KEY'),
            client_secret=os.getenv('UPSTOX_API_SECRET'),
            redirect_uri=os.getenv('UPSTOX_REDIRECT_URI'),
            grant_type='authorization_code'
        )
        return api_response.access_token
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    print(f"\n1. Open this URL in your browser:\n{get_login_url()}\n")
    code = input("2. Paste the 'code=' value from the browser address bar: ")
    token = exchange_code(code.strip())
    if token:
        print(f"\n✅ SUCCESS! YOUR ACCESS TOKEN IS:\n{token}")
    else:
        print("\n❌ Failed to get token. Check your credentials again.")